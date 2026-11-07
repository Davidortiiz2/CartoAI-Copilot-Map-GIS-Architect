# -*- coding: utf-8 -*-
"""
Módulo de integración con la plataforma de Datos Abiertos de Colombia (datos.gov.co).

Implementa la comunicación con la API de Catálogo Socrata v2 y la API SODA
para la búsqueda, filtrado, descarga y carga directa de capas geoespaciales GeoJSON
dentro del lienzo de QGIS 3.
"""

import json
import os
import tempfile
from typing import Dict, Any, List, Optional
import requests

from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsMessageLog,
    Qgis
)

# Constantes del servicio Socrata Colombia
SOCRATA_CATALOG_URL = "https://api.us.socrata.com/api/catalog/v1"
SOCRATA_FALLBACK_URL = "https://www.datos.gov.co/api/catalog/v1"
SOCRATA_RESOURCE_BASE = "https://www.datos.gov.co/resource"
LOG_TAG = "ColombiaCartoAgent"
DEFAULT_TIMEOUT = 25  # segundos


class ColombiaDataAPIException(Exception):
    """Excepción personalizada para errores al interactuar con datos.gov.co."""
    pass


def search_colombia_catalog(query: str, limit: int = 6) -> List[Dict[str, Any]]:
    """
    Busca datasets en el catálogo oficial de Datos Abiertos de Colombia (datos.gov.co).

    Args:
        query (str): Término de búsqueda (ej. 'vías', 'colegios', 'humedales', 'seguridad').
        limit (int): Número máximo de resultados a retornar.

    Returns:
        List[Dict[str, Any]]: Lista de metadatos de los datasets encontrados:
            id, name, description, category, type, updated_at, permalink.
    """
    params = {
        "q": query,
        "limit": limit,
        "domains": "www.datos.gov.co"
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)",
        "Accept": "application/json"
    }

    data = None
    last_exc = None
    for url in [SOCRATA_CATALOG_URL, SOCRATA_FALLBACK_URL]:
        try:
            response = requests.get(url, params=params, headers=headers, timeout=DEFAULT_TIMEOUT)
            if response.status_code == 200:
                data = response.json()
                break
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            continue

    if data is None:
        msg = f"Error al conectar con el catálogo de datos.gov.co: {str(last_exc or 'Servicio no disponible')}"
        QgsMessageLog.logMessage(msg, LOG_TAG, Qgis.Critical)
        raise ColombiaDataAPIException(msg)

    results: List[Dict[str, Any]] = []
    for item in data.get("results", []):
        resource = item.get("resource", {})
        classification = item.get("classification", {})
        metadata = item.get("metadata", {})

        resource_id = resource.get("id")
        name = resource.get("name", "Dataset sin nombre")
        desc = resource.get("description", "Sin descripción")
        categories = classification.get("categories", [])
        domain_category = classification.get("domain_category", "General")
        data_type = resource.get("type", "dataset")
        permalink = item.get("permalink", f"https://www.datos.gov.co/d/{resource_id}")

        results.append({
            "id": resource_id,
            "name": name,
            "description": desc[:300] + ("..." if len(desc) > 300 else ""),
            "category": domain_category or (categories[0] if categories else "General"),
            "type": data_type,
            "updated_at": resource.get("updatedAt", "N/A"),
            "url": permalink
        })

    return results


def fetch_geojson_from_socrata(
    resource_id: str,
    where_clause: Optional[str] = None,
    limit: int = 2000,
    select_clause: Optional[str] = None,
    app_token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Descarga entidades geoespaciales de un recurso de datos.gov.co en formato GeoJSON.
    Implementa tolerancia a fallos: si un filtro SoQL falla por nombre de columna inválido,
    reintenta automáticamente sin el filtro para garantizar la descarga.
    """
    clean_id = resource_id.strip()
    if "." in clean_id:
        clean_id = clean_id.split(".")[0]

    endpoint = f"{SOCRATA_RESOURCE_BASE}/{clean_id}.geojson"

    params: Dict[str, Any] = {
        "$limit": max(1, min(limit, 50000))
    }
    if where_clause and where_clause.strip():
        params["$where"] = where_clause.strip()
    if select_clause and select_clause.strip():
        params["$select"] = select_clause.strip()

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/vnd.geo+json, application/json"
    }
    if app_token and app_token.strip():
        headers["X-App-Token"] = app_token.strip()

    try:
        response = requests.get(endpoint, params=params, headers=headers, timeout=DEFAULT_TIMEOUT * 2)

        # Si da 400 Bad Request por columna no existente en $where, reintentar sin $where
        if response.status_code == 400 and "$where" in params:
            QgsMessageLog.logMessage(
                f"Filtro SoQL '{where_clause}' no coincide con las columnas de '{clean_id}'. Reintentando descarga sin filtro...",
                LOG_TAG,
                Qgis.Warning
            )
            del params["$where"]
            response = requests.get(endpoint, params=params, headers=headers, timeout=DEFAULT_TIMEOUT * 2)

        if response.status_code == 404:
            raise ColombiaDataAPIException(
                f"El recurso '{clean_id}' no existe en datos.gov.co."
            )

        response.raise_for_status()
        geojson_data = response.json()
    except requests.exceptions.RequestException as exc:
        msg = f"Error en la petición a la API SODA ({endpoint}): {str(exc)}"
        QgsMessageLog.logMessage(msg, LOG_TAG, Qgis.Critical)
        raise ColombiaDataAPIException(msg) from exc
    except json.JSONDecodeError as exc:
        msg = f"La respuesta recibida para '{clean_id}' no es un GeoJSON válido."
        QgsMessageLog.logMessage(msg, LOG_TAG, Qgis.Critical)
        raise ColombiaDataAPIException(msg) from exc

    features = geojson_data.get("features", [])

    # Intentar reconstruir geometrías si vienen como None pero existen campos lat/lon en properties
    valid_geoms = 0
    for feat in features:
        if feat.get("geometry"):
            valid_geoms += 1
            continue

        props = feat.get("properties") or {}
        lat_val = None
        lon_val = None
        for k, v in props.items():
            k_lower = k.lower()
            if not lat_val and any(x in k_lower for x in ["latitud", "latitude", "lat_"]):
                try: lat_val = float(str(v).replace(",", "."))
                except (ValueError, TypeError): pass
            if not lon_val and any(x in k_lower for x in ["longitud", "longitude", "lon_", "long_"]):
                try: lon_val = float(str(v).replace(",", "."))
                except (ValueError, TypeError): pass

        if lat_val is not None and lon_val is not None and -90 <= lat_val <= 90 and -180 <= lon_val <= 180:
            feat["geometry"] = {
                "type": "Point",
                "coordinates": [lon_val, lat_val]
            }
            valid_geoms += 1

    if not features:
        raise ColombiaDataAPIException(
            f"El recurso '{clean_id}' no contiene registros disponibles para descargar."
        )

    geojson_data["_is_spatial"] = (valid_geoms > 0)
    return geojson_data


def load_geojson_to_qgis(
    geojson_data: Dict[str, Any],
    layer_name: str,
    target_project: Optional[QgsProject] = None
) -> QgsVectorLayer:
    """
    Convierte un diccionario GeoJSON en un archivo temporal seguro y lo inyecta como
    QgsVectorLayer en el proyecto activo de QGIS.

    Args:
        geojson_data (dict): Diccionario FeatureCollection GeoJSON.
        layer_name (str): Nombre deseado para la capa en el panel de capas.
        target_project (QgsProject, optional): Instancia del proyecto QGIS. Por defecto QgsProject.instance().

    Returns:
        QgsVectorLayer: La capa vectorial cargada y añadida al proyecto.

    Raises:
        ColombiaDataAPIException: Si la capa no es válida o no se pudo cargar.
    """
    if target_project is None:
        target_project = QgsProject.instance()

    features = geojson_data.get("features", [])
    if not isinstance(features, list) or len(features) == 0:
        raise ColombiaDataAPIException(
            f"No se puede crear la capa '{layer_name}': el GeoJSON no contiene entidades (features)."
        )

    # Creamos un archivo temporal para que el proveedor OGR de QGIS lea nativamente los atributos y proyecciones
    temp_dir = tempfile.gettempdir()
    safe_name = "".join(c for c in layer_name if c.isalnum() or c in (" ", "_", "-")).rstrip()
    temp_file_path = os.path.join(temp_dir, f"colombia_{safe_name}_{os.getpid()}.geojson")

    try:
        with open(temp_file_path, "w", encoding="utf-8") as f:
            json.dump(geojson_data, f, ensure_ascii=False)
    except IOError as exc:
        raise ColombiaDataAPIException(f"Error escribiendo archivo temporal GeoJSON: {str(exc)}") from exc

    # Crear la capa vectorial con el driver OGR
    layer = QgsVectorLayer(temp_file_path, layer_name, "ogr")

    if not layer.isValid():
        # Intentar remover archivo temporal en caso de fallo
        if os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except OSError:
                pass
        raise ColombiaDataAPIException(
            f"QGIS no pudo interpretar el GeoJSON para la capa '{layer_name}'. "
            "Es posible que las geometrías sean inválidas o el formato esté corrupto."
        )

    # Añadir al proyecto QGIS
    target_project.addMapLayer(layer)
    layer_type_desc = "vectorial" if layer.isSpatial() else "tabla de atributos"
    QgsMessageLog.logMessage(
        f"Capa '{layer_name}' añadida con éxito ({layer_type_desc}, {layer.featureCount()} entidades).",
        LOG_TAG,
        Qgis.Info
    )

    return layer

