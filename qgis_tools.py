# -*- coding: utf-8 -*-
"""
Módulo de Geoprocesamiento, Simbología Temática y Diseño Cartográfico en PyQGIS.

Proporciona herramientas de nivel senior para:
1. Inspección profunda de datos espaciales y estadísticas de atributos.
2. Simbología temática avanzada (Simple, Categorizada, Graduada/Coropletas) y etiquetado con halo.
3. Ejecución de geoprocesos nativos de QGIS mediante Processing (Buffers, Clips, Centroides, Disolver).
4. Creación automatizada de composiciones de impresión profesionales (QgsPrintLayout) con mapa,
   título, subtítulo, leyenda dinámica, barra de escala gráfica y flecha de norte.
Compatible con QGIS 3 y QGIS 4.
"""

from typing import Dict, Any, List, Optional
import datetime
import os

from qgis.core import (
    QgsProject,
    QgsMapLayer,
    QgsMapLayerType,
    QgsVectorLayer,
    QgsWkbTypes,
    QgsSingleSymbolRenderer,
    QgsCategorizedSymbolRenderer,
    QgsRendererCategory,
    QgsGraduatedSymbolRenderer,
    QgsRendererRange,
    QgsClassificationQuantile,
    QgsClassificationEqualInterval,
    QgsStyle,
    QgsColorRamp,
    QgsMarkerSymbol,
    QgsLineSymbol,
    QgsFillSymbol,
    QgsSymbol,
    QgsPalLayerSettings,
    QgsVectorLayerSimpleLabeling,
    QgsTextFormat,
    QgsTextBufferSettings,
    QgsPrintLayout,
    QgsLayoutItemMap,
    QgsLayoutItemLabel,
    QgsLayoutItemLegend,
    QgsLayoutItemScaleBar,
    QgsLayoutItemPicture,
    QgsLayoutMeasurement,
    QgsLayoutSize,
    QgsLayoutPoint,
    QgsUnitTypes,
    QgsApplication,
    QgsMessageLog,
    Qgis
)
from qgis.utils import iface

try:
    from qgis.PyQt.QtCore import Qt
    from qgis.PyQt.QtGui import QColor, QFont
except ImportError:
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QColor, QFont

try:
    import processing
except ImportError:
    try:
        from qgis import processing
    except ImportError:
        processing = None

LOG_TAG = "CartoAICopilot"


def find_layer_by_name(layer_name: str, project: Optional[QgsProject] = None) -> Optional[QgsVectorLayer]:
    """Busca una capa vectorial por coincidencia exacta o parcial insensible a mayúsculas."""
    if project is None:
        project = QgsProject.instance()

    layers = project.mapLayers().values()
    target_clean = layer_name.strip().lower()

    for lyr in layers:
        if lyr.name().strip().lower() == target_clean and isinstance(lyr, QgsVectorLayer):
            return lyr

    for lyr in layers:
        if target_clean in lyr.name().strip().lower() and isinstance(lyr, QgsVectorLayer):
            return lyr

    return None


def get_active_layers_summary(project: Optional[QgsProject] = None) -> List[Dict[str, Any]]:
    """
    Inspecciona todas las capas cargadas en el proyecto y extrae un resumen analítico
    con nombres de campos, tipos y muestras de valores para que el LLM entienda el contenido.
    """
    if project is None:
        project = QgsProject.instance()

    summary: List[Dict[str, Any]] = []

    for layer_id, layer in project.mapLayers().items():
        if not layer.isValid():
            continue

        is_vector = (layer.type() == QgsMapLayerType.VectorLayer)
        crs_auth = layer.crs().authid() if layer.crs().isValid() else "Sin CRS"

        info: Dict[str, Any] = {
            "name": layer.name(),
            "id": layer_id,
            "type": "Vector" if is_vector else "Raster",
            "crs": crs_auth
        }

        if is_vector and isinstance(layer, QgsVectorLayer):
            is_spatial = layer.isSpatial()
            geom_str = QgsWkbTypes.displayString(layer.wkbType()) if is_spatial else "Tabla alfanumérica"
            feature_count = layer.featureCount()

            # Extraer campos y muestra de valores de los primeros registros
            fields_data = []
            sample_features = list(layer.getFeatures())[:3]

            for field in layer.fields()[:25]:
                field_name = field.name()
                sample_values = [str(f[field_name]) for f in sample_features if f[field_name] is not None]
                fields_data.append({
                    "name": field_name,
                    "type": field.typeName(),
                    "samples": sample_values[:2]
                })

            info.update({
                "is_spatial": is_spatial,
                "geometry": geom_str,
                "feature_count": feature_count,
                "fields": fields_data
            })

        summary.append(info)

    return summary


def apply_vector_style(
    layer_name: str,
    color: str = "#2A9D8F",
    outline_color: str = "#1D3557",
    size_or_width: float = 2.0,
    opacity: float = 1.0,
    project: Optional[QgsProject] = None
) -> Dict[str, Any]:
    """Aplica una simbología única con color armonizado y grosor adaptativo."""
    layer = find_layer_by_name(layer_name, project)
    if not layer:
        return {"success": False, "error": f"No se encontró la capa '{layer_name}'."}

    if not layer.isSpatial():
        return {"success": True, "message": f"La capa '{layer.name()}' es una tabla de datos sin geometría espacial."}

    q_color = QColor(color)
    q_outline = QColor(outline_color)
    q_color.setAlphaF(max(0.0, min(opacity, 1.0)))

    geom_type = layer.geometryType()

    if geom_type == QgsWkbTypes.PointGeometry:
        symbol = QgsMarkerSymbol.createSimple({
            "name": "circle",
            "color": q_color.name(QColor.HexArgb),
            "outline_color": q_outline.name(QColor.HexArgb),
            "outline_width": "0.4",
            "size": str(size_or_width)
        })
    elif geom_type == QgsWkbTypes.LineGeometry:
        symbol = QgsLineSymbol.createSimple({
            "line_color": q_color.name(QColor.HexArgb),
            "line_width": str(size_or_width)
        })
    elif geom_type == QgsWkbTypes.PolygonGeometry:
        symbol = QgsFillSymbol.createSimple({
            "color": q_color.name(QColor.HexArgb),
            "outline_color": q_outline.name(QColor.HexArgb),
            "outline_width": str(size_or_width if size_or_width < 1.5 else 0.6)
        })
    else:
        return {"success": False, "error": f"Geometría no soportada en '{layer_name}'."}

    layer.setRenderer(QgsSingleSymbolRenderer(symbol))
    layer.triggerRepaint()
    if iface and iface.mapCanvas():
        iface.mapCanvas().refresh()

    return {"success": True, "message": f"Estilo aplicado a '{layer.name()}' (Color: {color})."}


def apply_categorized_style(
    layer_name: str,
    field_name: str,
    color_ramp_name: str = "Spectral",
    project: Optional[QgsProject] = None
) -> Dict[str, Any]:
    """Aplica una clasificación cualitativa/categorizada con una rampa de color estilizada."""
    layer = find_layer_by_name(layer_name, project)
    if not layer or not layer.isSpatial():
        return {"success": False, "error": f"Capa vectorial espacial '{layer_name}' no encontrada."}

    field_idx = layer.fields().indexOf(field_name)
    if field_idx == -1:
        return {"success": False, "error": f"El campo '{field_name}' no existe en la capa '{layer.name()}'."}

    # Obtener valores únicos del campo
    unique_vals = list(layer.uniqueValues(field_idx))[:30]  # Máximo 30 categorías para legibilidad
    if not unique_vals:
        return {"success": False, "error": f"El campo '{field_name}' no contiene valores para categorizar."}

    # Cargar rampa de color de QGIS
    style = QgsStyle.defaultStyle()
    ramp = style.colorRamp(color_ramp_name)
    if not ramp:
        ramp = style.colorRamp("Spectral") or style.colorRamp("Viridis")

    categories = []
    num_vals = len(unique_vals)
    geom_type = layer.geometryType()

    for i, val in enumerate(unique_vals):
        factor = i / max(1, num_vals - 1)
        color = ramp.color(factor) if ramp else QColor.fromHsv(int(factor * 360), 180, 220)

        if geom_type == QgsWkbTypes.PointGeometry:
            sym = QgsMarkerSymbol.createSimple({"name": "circle", "color": color.name(), "outline_color": "#333", "size": "3"})
        elif geom_type == QgsWkbTypes.LineGeometry:
            sym = QgsLineSymbol.createSimple({"line_color": color.name(), "line_width": "1.2"})
        else:
            sym = QgsFillSymbol.createSimple({"color": color.name(), "outline_color": "#444", "outline_width": "0.3"})

        categories.append(QgsRendererCategory(val, sym, str(val)))

    renderer = QgsCategorizedSymbolRenderer(field_name, categories)
    layer.setRenderer(renderer)
    layer.triggerRepaint()
    if iface and iface.mapCanvas():
        iface.mapCanvas().refresh()

    return {"success": True, "message": f"Simbología categorizada aplicada a '{layer.name()}' sobre el campo '{field_name}' ({len(categories)} categorías)."}


def enable_labels(
    layer_name: str,
    field_name: str,
    font_size: int = 9,
    font_color: str = "#1E293B",
    halo_color: str = "#FFFFFF",
    halo_size: float = 1.0,
    project: Optional[QgsProject] = None
) -> Dict[str, Any]:
    """Activa etiquetas tipográficas con halo protector para legibilidad profesional."""
    layer = find_layer_by_name(layer_name, project)
    if not layer or not layer.isSpatial():
        return {"success": False, "error": f"Capa '{layer_name}' no válida para etiquetar."}

    if layer.fields().indexOf(field_name) == -1:
        return {"success": False, "error": f"Campo '{field_name}' no encontrado en '{layer.name()}'."}

    settings = QgsPalLayerSettings()
    settings.fieldName = field_name
    settings.isExpression = False

    text_format = QgsTextFormat()
    font = QFont("Helvetica", font_size)
    font.setBold(True)
    text_format.setFont(font)
    text_format.setColor(QColor(font_color))

    # Configuración de Halo (Buffer blanco alrededor del texto)
    buffer_settings = QgsTextBufferSettings()
    buffer_settings.setEnabled(True)
    buffer_settings.setSize(halo_size)
    buffer_settings.setColor(QColor(halo_color))
    text_format.setBuffer(buffer_settings)

    settings.setFormat(text_format)
    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    layer.setLabelsEnabled(True)
    layer.triggerRepaint()

    if iface and iface.mapCanvas():
        iface.mapCanvas().refresh()

    return {"success": True, "message": f"Etiquetas activadas en '{layer.name()}' con el campo '{field_name}'."}


def run_geoprocessing(
    algorithm_id: str,
    parameters: Dict[str, Any],
    output_layer_name: Optional[str] = None,
    project: Optional[QgsProject] = None
) -> Dict[str, Any]:
    global processing
    if processing is None:
        try:
            import processing
        except ImportError:
            return {"success": False, "error": "El proveedor de Geoprocesamiento (Processing) no está inicializado."}
    """
    Ejecuta un geoproceso nativo de QGIS (Processing) y añade la capa resultante al proyecto.
    Algoritmos frecuentes:
      - 'native:buffer' (INPUT, DISTANCE, OUTPUT='memory:')
      - 'native:clip' (INPUT, OVERLAY, OUTPUT='memory:')
      - 'native:centroids' (INPUT, OUTPUT='memory:')
      - 'native:dissolve' (INPUT, FIELD=[], OUTPUT='memory:')
    """
    if project is None:
        project = QgsProject.instance()

    try:
        # Asegurar que OUTPUT sea en memoria si no se especificó ruta
        params = dict(parameters)
        if "OUTPUT" not in params:
            params["OUTPUT"] = "memory:"

        # Resolver nombres de capas a objetos QgsVectorLayer si se pasaron como strings
        for k in ["INPUT", "OVERLAY", "INPUT_LAYER"]:
            if k in params and isinstance(params[k], str):
                resolved = find_layer_by_name(params[k], project)
                if resolved:
                    params[k] = resolved

        result = processing.run(algorithm_id, params)
        output_obj = result.get("OUTPUT")

        if isinstance(output_obj, QgsVectorLayer) and output_obj.isValid():
            name = output_layer_name or f"Resultado_{algorithm_id.split(':')[-1]}"
            output_obj.setName(name)
            project.addMapLayer(output_obj)
            return {
                "success": True,
                "message": f"Geoproceso '{algorithm_id}' ejecutado con éxito. Capa '{name}' generada con {output_obj.featureCount()} entidades.",
                "feature_count": output_obj.featureCount()
            }
        elif isinstance(output_obj, str) and os.path.exists(output_obj):
            layer = QgsVectorLayer(output_obj, output_layer_name or "Geoproceso_Output", "ogr")
            if layer.isValid():
                project.addMapLayer(layer)
                return {"success": True, "message": f"Geoproceso '{algorithm_id}' finalizado y cargado al mapa."}

        return {"success": True, "result": str(result), "message": f"Algoritmo '{algorithm_id}' ejecutado exitosamente."}

    except Exception as exc:
        msg = f"Error ejecutando geoproceso '{algorithm_id}': {str(exc)}"
        QgsMessageLog.logMessage(msg, LOG_TAG, Qgis.Critical)
        return {"success": False, "error": msg}


def create_professional_layout(
    layout_name: str = "Composicion_Cartografica",
    title: str = "Mapa de Análisis Geoespacial",
    subtitle: str = "Generado por CartoAI Copilot",
    author: str = "David Ortiz (Geografía)",
    orientation: str = "landscape",
    include_legend: bool = True,
    include_scalebar: bool = True,
    include_north: bool = True,
    project: Optional[QgsProject] = None
) -> Dict[str, Any]:
    """
    Construye una composición cartográfica de nivel profesional (QgsPrintLayout)
    con mapa principal, encabezado estilizado, leyenda dinámica, barra de escala y norte.
    """
    if project is None:
        project = QgsProject.instance()

    layout_manager = project.layoutManager()
    existing = layout_manager.layoutByName(layout_name)
    if existing:
        layout_manager.removeLayout(existing)

    layout = QgsPrintLayout(project)
    layout.initializeDefaults()
    layout.setName(layout_name)

    is_landscape = (orientation.lower() != "portrait")
    page_w = 297 if is_landscape else 210  # A4 mm
    page_h = 210 if is_landscape else 297

    # Ajustar dimensiones de página A4
    page = layout.pageCollection().pages()[0]
    page.setPageSize(QgsLayoutSize(page_w, page_h, QgsUnitTypes.LayoutMillimeters))
    layout_manager.addLayout(layout)

    # 1. Mapa Principal
    map_margin_x = 12
    map_top = 26
    map_w = page_w - (map_margin_x * 2)
    map_h = page_h - map_top - 18

    map_item = QgsLayoutItemMap(layout)
    map_item.attemptMove(QgsLayoutPoint(map_margin_x, map_top, QgsUnitTypes.LayoutMillimeters))
    map_item.attemptResize(QgsLayoutSize(map_w, map_h, QgsUnitTypes.LayoutMillimeters))

    if iface and iface.mapCanvas():
        map_item.setExtent(iface.mapCanvas().extent())

    map_item.setFrameEnabled(True)
    map_item.setFrameStrokeWidth(QgsLayoutMeasurement(0.4, QgsUnitTypes.LayoutMillimeters))
    layout.addLayoutItem(map_item)

    # 2. Encabezado: Título y Subtítulo
    title_item = QgsLayoutItemLabel(layout)
    title_item.setText(title)
    font_title = QFont("Helvetica", 16)
    font_title.setBold(True)
    title_item.setFont(font_title)
    title_item.adjustSizeToText()
    title_item.attemptMove(QgsLayoutPoint(map_margin_x, 8, QgsUnitTypes.LayoutMillimeters))
    layout.addLayoutItem(title_item)

    if subtitle:
        sub_item = QgsLayoutItemLabel(layout)
        sub_item.setText(subtitle)
        font_sub = QFont("Helvetica", 10)
        font_sub.setItalic(True)
        sub_item.setFont(font_sub)
        sub_item.adjustSizeToText()
        sub_item.attemptMove(QgsLayoutPoint(map_margin_x, 16, QgsUnitTypes.LayoutMillimeters))
        layout.addLayoutItem(sub_item)

    # 3. Barra de Escala Gráfica
    if include_scalebar:
        scale_item = QgsLayoutItemScaleBar(layout)
        scale_item.setStyle("Single Box")
        scale_item.setLinkedMap(map_item)
        scale_item.setUnits(QgsUnitTypes.DistanceKilometers)
        scale_item.setNumberOfSegments(2)
        scale_item.setNumberOfSegmentsLeft(0)
        scale_item.setUnitsPerSegment(2)
        scale_item.update()
        scale_pos_y = map_top + map_h - 14
        scale_item.attemptMove(QgsLayoutPoint(map_margin_x + 4, scale_pos_y, QgsUnitTypes.LayoutMillimeters))
        scale_item.setBackgroundEnabled(True)
        scale_item.setBackgroundColor(QColor(255, 255, 255, 210))
        layout.addLayoutItem(scale_item)

    # 4. Flecha de Norte
    if include_north:
        north_item = QgsLayoutItemPicture(layout)
        # Buscar ícono SVG de norte estándar en QGIS
        svg_paths = QgsApplication.svgPaths()
        north_svg = None
        for p in svg_paths:
            cand = os.path.join(p, "arrows", "NorthArrow_02.svg")
            if os.path.exists(cand):
                north_svg = cand
                break
        if north_svg:
            north_item.setPicturePath(north_svg)
        north_item.attemptResize(QgsLayoutSize(14, 14, QgsUnitTypes.LayoutMillimeters))
        north_item.attemptMove(QgsLayoutPoint(page_w - map_margin_x - 18, map_top + 4, QgsUnitTypes.LayoutMillimeters))
        north_item.setBackgroundEnabled(True)
        north_item.setBackgroundColor(QColor(255, 255, 255, 190))
        layout.addLayoutItem(north_item)

    # 5. Leyenda Automática
    if include_legend:
        legend_item = QgsLayoutItemLegend(layout)
        legend_item.setLinkedMap(map_item)
        legend_item.setTitle("Leyenda")
        legend_item.setAutoUpdateModel(True)
        legend_item.setBackgroundEnabled(True)
        legend_item.setBackgroundColor(QColor(255, 255, 255, 225))
        legend_item.attemptMove(QgsLayoutPoint(page_w - map_margin_x - 55, map_top + 22, QgsUnitTypes.LayoutMillimeters))
        legend_item.attemptResize(QgsLayoutSize(50, 60, QgsUnitTypes.LayoutMillimeters))
        layout.addLayoutItem(legend_item)

    # 6. Cajetín inferior con Metadatos
    crs_str = project.crs().authid() if project.crs().isValid() else "WGS84"
    date_str = datetime.datetime.now().strftime("%d/%m/%Y")
    meta_text = f"Autor: {author}  |  Sistema de Referencia: {crs_str}  |  Fecha: {date_str}"

    meta_item = QgsLayoutItemLabel(layout)
    meta_item.setText(meta_text)
    font_meta = QFont("Helvetica", 8)
    meta_item.setFont(font_meta)
    meta_item.adjustSizeToText()
    meta_item.attemptMove(QgsLayoutPoint(map_margin_x, page_h - 10, QgsUnitTypes.LayoutMillimeters))
    layout.addLayoutItem(meta_item)

    return {
        "success": True,
        "message": f"Composición '{layout_name}' creada exitosamente con mapa, título, leyenda, escala y norte. Puedes abrirla en Proyecto ➔ Diseños."
    }


def zoom_to_layer(layer_name: str, project: Optional[QgsProject] = None) -> Dict[str, Any]:
    """Ajusta el zoom del mapa a la extensión de la capa indicada."""
    layer = find_layer_by_name(layer_name, project)
    if not layer:
        return {"success": False, "error": f"No se encontró la capa '{layer_name}'."}

    if not layer.isSpatial():
        return {"success": True, "message": f"La capa '{layer.name()}' es una tabla alfanumérica sin geometría espacial."}

    extent = layer.extent()
    if extent.isEmpty() or extent.isNull():
        return {"success": False, "error": f"La capa '{layer.name()}' no posee una extensión válida."}

    if iface and iface.mapCanvas():
        canvas = iface.mapCanvas()
        if layer.crs() != canvas.mapSettings().destinationCrs():
            from qgis.core import QgsCoordinateTransform
            xform = QgsCoordinateTransform(layer.crs(), canvas.mapSettings().destinationCrs(), project or QgsProject.instance())
            extent = xform.transformBoundingBox(extent)

        extent.scale(1.10)
        canvas.setExtent(extent)
        canvas.refresh()
        return {"success": True, "message": f"Zoom aplicado a la extensión de '{layer.name()}'."}

    return {"success": False, "error": "Lienzo de mapa no disponible."}


def apply_filter(layer_name: str, sql_expression: str, project: Optional[QgsProject] = None) -> Dict[str, Any]:
    """Aplica o remueve un filtro SQL sobre los atributos de la capa vectorial."""
    layer = find_layer_by_name(layer_name, project)
    if not layer:
        return {"success": False, "error": f"No se encontró la capa '{layer_name}'."}

    expr = "" if sql_expression.strip().upper() in ("CLEAR", "NONE", "") else sql_expression.strip()
    ok = layer.setSubsetString(expr)
    if not ok and expr != "":
        return {"success": False, "error": f"Filtro SQL inválido: '{expr}'."}

    layer.triggerRepaint()
    if iface and iface.mapCanvas():
        iface.mapCanvas().refresh()

    return {"success": True, "message": f"Filtro aplicado a '{layer.name()}'. Entidades visibles: {layer.featureCount()}."}
