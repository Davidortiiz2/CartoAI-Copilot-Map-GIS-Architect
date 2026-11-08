# -*- coding: utf-8 -*-
"""
Módulo de Geoprocesamiento, Simbología Temática y Diseño Cartográfico en PyQGIS.

Proporciona herramientas de nivel senior para:
1. Inspección profunda de datos espaciales y estadísticas de atributos.
2. Simbología temática avanzada (Simple, Categorizada, Graduada/Coropletas) y etiquetado con halo.
3. Ejecución de geoprocesos nativos de QGIS mediante Processing (Buffers, Clips, Centroides, Disolver).
4. Creación automatizada de composiciones de impresión profesionales (QgsPrintLayout) con mapa,
   título, subtítulo, leyenda dinámica, barra de escala gráfica y flecha de norte.
Compatible con QGIS 3 (PyQt5) y QGIS 4 (PyQt6).
"""

from typing import Dict, Any, List, Optional, Union
import datetime
import os

from qgis.core import (
    QgsProject,
    QgsMapLayer,
    QgsVectorLayer,
    QgsRasterLayer,
    QgsWkbTypes,
    QgsSingleSymbolRenderer,
    QgsCategorizedSymbolRenderer,
    QgsRendererCategory,
    QgsGraduatedSymbolRenderer,
    QgsRendererRange,
    QgsStyle,
    QgsMarkerSymbol,
    QgsLineSymbol,
    QgsFillSymbol,
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

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QFont

try:
    import processing
except ImportError:
    try:
        from qgis import processing
    except ImportError:
        processing = None

LOG_TAG = "CartoAICopilot"


def _enum_val(cls, scoped_name: str, member_name: str):
    """Obtiene un valor de enumeración de forma compatible entre PyQt5/QGIS3 y PyQt6/QGIS4."""
    if hasattr(cls, member_name):
        return getattr(cls, member_name)
    scoped = getattr(cls, scoped_name, None)
    if scoped is not None and hasattr(scoped, member_name):
        return getattr(scoped, member_name)
    return None


LAYOUT_MM = QgsUnitTypes.LayoutUnit.LayoutMillimeters
DIST_KM = QgsUnitTypes.DistanceUnit.DistanceKilometers
POINT_GEOM = QgsWkbTypes.GeometryType.PointGeometry
LINE_GEOM = QgsWkbTypes.GeometryType.LineGeometry
POLYGON_GEOM = QgsWkbTypes.GeometryType.PolygonGeometry


def find_layer_by_name(
    layer_or_name: Union[str, QgsMapLayer, None] = None,
    project: Optional[QgsProject] = None
) -> Optional[QgsVectorLayer]:
    """
    Resuelve una capa vectorial ya sea desde un objeto QgsMapLayer, un nombre parcial/exacto,
    o devuelve la capa activa en QGIS si no se especifica.
    """
    if project is None:
        project = QgsProject.instance()

    if isinstance(layer_or_name, QgsVectorLayer):
        return layer_or_name
    if isinstance(layer_or_name, QgsMapLayer):
        return None

    if not layer_or_name or not str(layer_or_name).strip():
        active = iface.activeLayer() if iface else None
        if isinstance(active, QgsVectorLayer):
            return active
        for lyr in project.mapLayers().values():
            if isinstance(lyr, QgsVectorLayer):
                return lyr
        return None

    target_clean = str(layer_or_name).strip().lower()
    layers = list(project.mapLayers().values())

    for lyr in layers:
        if lyr.name().strip().lower() == target_clean and isinstance(lyr, QgsVectorLayer):
            return lyr

    for lyr in layers:
        if target_clean in lyr.name().strip().lower() and isinstance(lyr, QgsVectorLayer):
            return lyr

    active = iface.activeLayer() if iface else None
    if isinstance(active, QgsVectorLayer):
        return active

    return None


def get_active_layers_summary(project: Optional[QgsProject] = None) -> List[Dict[str, Any]]:
    """
    Inspecciona todas las capas cargadas en el proyecto y extrae un resumen analítico
    con nombres de campos, tipos y muestras de valores para que el LLM entienda el contenido.
    """
    if project is None:
        project = QgsProject.instance()

    summary: List[Dict[str, Any]] = []
    active_layer = iface.activeLayer() if iface else None
    active_id = active_layer.id() if active_layer else None

    for layer_id, layer in project.mapLayers().items():
        if not layer.isValid():
            continue

        is_vector = isinstance(layer, QgsVectorLayer)
        crs_auth = layer.crs().authid() if layer.crs().isValid() else "Sin CRS"

        info: Dict[str, Any] = {
            "name": layer.name(),
            "id": layer_id,
            "is_active": (layer_id == active_id),
            "type": "Vector" if is_vector else "Raster",
            "crs": crs_auth
        }

        if is_vector:
            is_spatial = layer.isSpatial()
            geom_str = QgsWkbTypes.displayString(layer.wkbType()) if is_spatial else "Tabla alfanumérica"
            feature_count = layer.featureCount()

            fields_data = []
            sample_features = []
            for idx, feat in enumerate(layer.getFeatures()):
                if idx >= 3:
                    break
                sample_features.append(feat)

            for i, field in enumerate(layer.fields()):
                if i >= 25:
                    break
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
    layer_name: Union[str, QgsMapLayer, None] = None,
    color: Optional[str] = None,
    outline_color: Optional[str] = None,
    size_or_width: float = 2.0,
    opacity: float = 0.85,
    project: Optional[QgsProject] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Aplica una simbología única con color armonizado y grosor adaptativo.
    Soporta alias de argumentos: color_hex, stroke_color, stroke_width, layer.
    """
    target = layer_name or kwargs.get("layer")
    layer = find_layer_by_name(target, project)
    if not layer:
        return {"success": False, "error": f"No se encontró la capa '{target}'."}

    if not layer.isSpatial():
        return {"success": True, "message": f"La capa '{layer.name()}' es una tabla de datos sin geometría espacial."}

    fill_hex = color or kwargs.get("color_hex") or kwargs.get("fill_color") or "#2563EB"
    border_hex = outline_color or kwargs.get("stroke_color") or kwargs.get("border_color") or "#1E3A8A"
    width_val = kwargs.get("stroke_width", size_or_width)

    q_color = QColor(fill_hex)
    q_outline = QColor(border_hex)
    layer.setOpacity(max(0.0, min(float(opacity), 1.0)))

    geom_type = layer.geometryType()

    if geom_type == POINT_GEOM:
        symbol = QgsMarkerSymbol.createSimple({
            "name": "circle",
            "color": q_color.name(),
            "outline_color": q_outline.name(),
            "outline_width": "0.4",
            "size": str(width_val if width_val >= 1.5 else 3.0)
        })
    elif geom_type == LINE_GEOM:
        symbol = QgsLineSymbol.createSimple({
            "line_color": q_color.name(),
            "line_width": str(width_val)
        })
    elif geom_type == POLYGON_GEOM:
        symbol = QgsFillSymbol.createSimple({
            "color": q_color.name(),
            "outline_color": q_outline.name(),
            "outline_width": str(width_val if width_val < 1.5 else 0.5)
        })
    else:
        return {"success": False, "error": f"Geometría no soportada en '{layer.name()}'."}

    layer.setRenderer(QgsSingleSymbolRenderer(symbol))
    layer.triggerRepaint()
    if iface and iface.mapCanvas():
        iface.mapCanvas().refresh()

    return {"success": True, "message": f"Estilo aplicado a '{layer.name()}' (Color: {fill_hex})."}


def apply_categorized_style(
    layer_name: Union[str, QgsMapLayer, None] = None,
    field_name: Optional[str] = None,
    color_ramp_name: str = "Spectral",
    project: Optional[QgsProject] = None,
    **kwargs
) -> Dict[str, Any]:
    """Aplica una clasificación cualitativa/categorizada con una rampa de color estilizada."""
    target = layer_name or kwargs.get("layer")
    layer = find_layer_by_name(target, project)
    if not layer or not layer.isSpatial():
        return {"success": False, "error": f"Capa vectorial espacial '{target}' no encontrada."}

    if not field_name:
        field_name = kwargs.get("field") or (layer.fields()[0].name() if len(layer.fields()) > 0 else "")

    field_idx = layer.fields().indexOf(field_name)
    if field_idx == -1:
        return {"success": False, "error": f"El campo '{field_name}' no existe en la capa '{layer.name()}'."}

    unique_vals = list(layer.uniqueValues(field_idx))[:30]
    if not unique_vals:
        return {"success": False, "error": f"El campo '{field_name}' no contiene valores para categorizar."}

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

        if geom_type == POINT_GEOM:
            sym = QgsMarkerSymbol.createSimple({"name": "circle", "color": color.name(), "outline_color": "#333333", "size": "3"})
        elif geom_type == LINE_GEOM:
            sym = QgsLineSymbol.createSimple({"line_color": color.name(), "line_width": "1.2"})
        else:
            sym = QgsFillSymbol.createSimple({"color": color.name(), "outline_color": "#444444", "outline_width": "0.3"})

        categories.append(QgsRendererCategory(val, sym, str(val)))

    renderer = QgsCategorizedSymbolRenderer(field_name, categories)
    layer.setRenderer(renderer)
    layer.triggerRepaint()
    if iface and iface.mapCanvas():
        iface.mapCanvas().refresh()

    return {"success": True, "message": f"Simbología categorizada aplicada a '{layer.name()}' sobre '{field_name}' ({len(categories)} categorías)."}


def enable_labels(
    layer_name: Union[str, QgsMapLayer, None] = None,
    field_name: Optional[str] = None,
    font_size: int = 9,
    font_color: str = "#1E293B",
    halo_color: str = "#FFFFFF",
    halo_size: float = 1.0,
    project: Optional[QgsProject] = None,
    **kwargs
) -> Dict[str, Any]:
    """Activa etiquetas tipográficas con halo protector para legibilidad profesional."""
    target = layer_name or kwargs.get("layer")
    layer = find_layer_by_name(target, project)
    if not layer or not layer.isSpatial():
        return {"success": False, "error": f"Capa '{target}' no válida para etiquetar."}

    field_names = [f.name() for f in layer.fields()]
    if not field_names:
        return {"success": False, "error": f"La capa '{layer.name()}' no tiene campos de atributos."}

    if not field_name or field_name not in field_names:
        field_name = field_names[0]
        for cand in ["nombre", "name", "nom", "municipio", "departamento", "titulo", "label", "codigo"]:
            for fn in field_names:
                if cand in fn.lower():
                    field_name = fn
                    break

    font_family = kwargs.get("font_family", "Segoe UI")
    buffer_col = kwargs.get("buffer_color", halo_color)

    settings = QgsPalLayerSettings()
    settings.fieldName = field_name
    settings.isExpression = False

    text_format = QgsTextFormat()
    font = QFont(font_family, int(font_size))
    font.setBold(True)
    text_format.setFont(font)
    text_format.setColor(QColor(font_color))

    buffer_settings = QgsTextBufferSettings()
    buffer_settings.setEnabled(True)
    buffer_settings.setSize(float(halo_size))
    buffer_settings.setColor(QColor(buffer_col))
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
    project: Optional[QgsProject] = None,
    **kwargs
) -> Dict[str, Any]:
    """Ejecuta un geoproceso nativo de QGIS (Processing) y añade la capa resultante al proyecto."""
    global processing
    if processing is None:
        try:
            import processing
        except ImportError:
            return {"success": False, "error": "El módulo Processing no está disponible."}

    if project is None:
        project = QgsProject.instance()

    try:
        params = dict(parameters)
        if "OUTPUT" not in params:
            params["OUTPUT"] = "memory:"

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
                "message": f"Geoproceso '{algorithm_id}' ejecutado con éxito. Capa '{name}' generada ({output_obj.featureCount()} entidades).",
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
        QgsMessageLog.logMessage(msg, LOG_TAG, Qgis.MessageLevel.Critical)
        return {"success": False, "error": msg}


def create_professional_layout(
    layout_name: str = "Mapa Oficial CartoAI",
    title: Optional[str] = None,
    map_title: Optional[str] = None,
    subtitle: str = "Composición generada por CartoAI Copilot",
    author: str = "David Ortiz (Estudiante de Geografía)",
    page_format: str = "A4",
    orientation: str = "landscape",
    include_legend: bool = True,
    include_scalebar: bool = True,
    include_north: bool = True,
    open_designer: bool = True,
    project: Optional[QgsProject] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Construye una composición cartográfica de nivel profesional (QgsPrintLayout)
    con mapa principal, encabezado estilizado, leyenda dinámica, barra de escala y norte.
    Acepta tanto `title` como `map_title` y cualquier argumento adicional vía `**kwargs`.
    """
    if project is None:
        project = QgsProject.instance()

    final_title = map_title or title or kwargs.get("header") or "MAPA TEMÁTICO OFICIAL"

    layout_manager = project.layoutManager()
    existing = layout_manager.layoutByName(layout_name)
    if existing:
        layout_manager.removeLayout(existing)

    layout = QgsPrintLayout(project)
    layout.initializeDefaults()
    layout.setName(layout_name)

    is_landscape = (str(orientation).lower() != "portrait")
    if str(page_format).upper() == "A3":
        page_w, page_h = (420, 297) if is_landscape else (297, 420)
    else:
        page_w, page_h = (297, 210) if is_landscape else (210, 297)

    page = layout.pageCollection().pages()[0]
    page.setPageSize(QgsLayoutSize(page_w, page_h, LAYOUT_MM))
    layout_manager.addLayout(layout)

    # 1. Mapa Principal
    map_margin_x = 12
    map_top = 26
    map_w = page_w - (map_margin_x * 2)
    map_h = page_h - map_top - 18

    map_item = QgsLayoutItemMap(layout)
    map_item.attemptMove(QgsLayoutPoint(map_margin_x, map_top, LAYOUT_MM))
    map_item.attemptResize(QgsLayoutSize(map_w, map_h, LAYOUT_MM))

    if iface and iface.mapCanvas():
        ext = iface.mapCanvas().extent()
        if not ext.isEmpty():
            map_item.setExtent(ext)

    map_item.setFrameEnabled(True)
    map_item.setFrameStrokeWidth(QgsLayoutMeasurement(0.4, LAYOUT_MM))
    layout.addLayoutItem(map_item)

    # 2. Encabezado: Título y Subtítulo
    title_item = QgsLayoutItemLabel(layout)
    title_item.setText(final_title)
    txt_fmt_title = QgsTextFormat()
    font_title = QFont("Segoe UI", 16)
    font_title.setBold(True)
    txt_fmt_title.setFont(font_title)
    txt_fmt_title.setColor(QColor("#0F172A"))
    title_item.setTextFormat(txt_fmt_title)
    title_item.adjustSizeToText()
    title_item.attemptMove(QgsLayoutPoint(map_margin_x, 7, LAYOUT_MM))
    layout.addLayoutItem(title_item)

    if subtitle:
        sub_item = QgsLayoutItemLabel(layout)
        sub_item.setText(subtitle)
        txt_fmt_sub = QgsTextFormat()
        font_sub = QFont("Segoe UI", 10)
        font_sub.setItalic(True)
        txt_fmt_sub.setFont(font_sub)
        txt_fmt_sub.setColor(QColor("#475569"))
        sub_item.setTextFormat(txt_fmt_sub)
        sub_item.adjustSizeToText()
        sub_item.attemptMove(QgsLayoutPoint(map_margin_x, 16, LAYOUT_MM))
        layout.addLayoutItem(sub_item)

    # 3. Barra de Escala Gráfica
    if include_scalebar:
        scale_item = QgsLayoutItemScaleBar(layout)
        scale_item.setStyle("Single Box")
        scale_item.setLinkedMap(map_item)
        if DIST_KM is not None:
            scale_item.setUnits(DIST_KM)
        scale_item.setNumberOfSegments(2)
        scale_item.setNumberOfSegmentsLeft(0)
        scale_item.setUnitsPerSegment(2)
        scale_item.update()
        scale_pos_y = map_top + map_h - 15
        scale_item.attemptMove(QgsLayoutPoint(map_margin_x + 4, scale_pos_y, LAYOUT_MM))
        scale_item.setBackgroundEnabled(True)
        scale_item.setBackgroundColor(QColor(255, 255, 255, 215))
        layout.addLayoutItem(scale_item)

    # 4. Flecha de Norte
    if include_north:
        north_item = QgsLayoutItemPicture(layout)
        svg_paths = QgsApplication.svgPaths()
        north_svg = None
        for p in svg_paths:
            cand = os.path.join(p, "arrows", "NorthArrow_02.svg")
            if os.path.exists(cand):
                north_svg = cand
                break
        if north_svg:
            north_item.setPicturePath(north_svg)
        north_item.attemptResize(QgsLayoutSize(14, 14, LAYOUT_MM))
        north_item.attemptMove(QgsLayoutPoint(page_w - map_margin_x - 18, map_top + 4, LAYOUT_MM))
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
        legend_item.attemptMove(QgsLayoutPoint(page_w - map_margin_x - 55, map_top + 22, LAYOUT_MM))
        legend_item.attemptResize(QgsLayoutSize(50, 60, LAYOUT_MM))
        layout.addLayoutItem(legend_item)

    # 6. Cajetín inferior con Metadatos
    crs_str = project.crs().authid() if project.crs().isValid() else "EPSG:4326"
    date_str = datetime.datetime.now().strftime("%d/%m/%Y")
    meta_text = f"Autor: {author}  |  CRS: {crs_str}  |  Fecha: {date_str}"

    meta_item = QgsLayoutItemLabel(layout)
    meta_item.setText(meta_text)
    txt_fmt_meta = QgsTextFormat()
    txt_fmt_meta.setFont(QFont("Segoe UI", 8))
    txt_fmt_meta.setColor(QColor("#334155"))
    meta_item.setTextFormat(txt_fmt_meta)
    meta_item.adjustSizeToText()
    meta_item.attemptMove(QgsLayoutPoint(map_margin_x, page_h - 10, LAYOUT_MM))
    layout.addLayoutItem(meta_item)

    if open_designer and iface:
        try:
            iface.openLayoutDesigner(layout)
        except Exception:  # nosec B110
            pass

    msg = f"Composición '{layout_name}' ({page_format} {orientation}) creada y abierta exitosamente con mapa, título '{final_title}', leyenda, escala y norte."
    print(msg)
    return {
        "success": True,
        "layout_name": layout_name,
        "message": msg
    }


def zoom_to_layer(layer_name: Union[str, QgsMapLayer, None] = None, project: Optional[QgsProject] = None) -> Dict[str, Any]:
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


def apply_filter(layer_name: Union[str, QgsMapLayer, None], sql_expression: str, project: Optional[QgsProject] = None) -> Dict[str, Any]:
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


def add_osm_basemap(layer_name: str = "OpenStreetMap Standard", basemap_type: str = "osm", project: Optional[QgsProject] = None) -> Dict[str, Any]:
    """
    Carga mapas base mundiales vía XYZ Tiles:
    - 'osm': OpenStreetMap Standard
    - 'satellite': Esri World Imagery (Satélite de alta resolución)
    - 'dark': CartoDB Dark Matter (Ideal para mapas temáticos oscuros)
    - 'positron': CartoDB Positron (Minimalista claro para cartografía)
    - 'topo': OpenTopoMap (Topográfico con relieve)
    """
    if project is None:
        project = QgsProject.instance()

    catalog = {
        "osm": (
            "OpenStreetMap Standard",
            "type=xyz&url=https://tile.openstreetmap.org/{z}/{x}/{y}.png&zmax=19&zmin=0"
        ),
        "satellite": (
            "Esri World Imagery (Satélite)",
            "type=xyz&url=https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}&zmax=19&zmin=0"
        ),
        "dark": (
            "CartoDB Dark Matter",
            "type=xyz&url=https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png&zmax=20&zmin=0"
        ),
        "positron": (
            "CartoDB Positron (Minimalista)",
            "type=xyz&url=https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png&zmax=20&zmin=0"
        ),
        "topo": (
            "OpenTopoMap Relieve",
            "type=xyz&url=https://tile.opentopomap.org/{z}/{x}/{y}.png&zmax=17&zmin=0"
        ),
    }

    key = str(basemap_type).lower().strip()
    default_title, url_with_params = catalog.get(key, catalog["osm"])
    final_name = layer_name if layer_name != "OpenStreetMap Standard" else default_title

    osm_layer = QgsRasterLayer(url_with_params, final_name, "wms")

    if osm_layer.isValid():
        project.addMapLayer(osm_layer)
        if iface and iface.mapCanvas():
            iface.mapCanvas().refresh()
        print(f"Mapa base '{final_name}' cargado en el lienzo.")
        return {"success": True, "message": f"Capa '{final_name}' añadida exitosamente.", "layer_id": osm_layer.id()}
    else:
        return {"success": False, "error": f"No se pudo inicializar el mapa base '{final_name}'."}

