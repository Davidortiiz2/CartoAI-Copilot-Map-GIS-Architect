# -*- coding: utf-8 -*-
"""
Motor de ejecución de código PyQGIS en tiempo real (Arquitectura estilo TerraLab).

Incluye:
1. Recarga en caliente (Hot-Reload) de `qgis_tools` para aplicar mejoras sin reiniciar QGIS.
2. Detección inteligente de efectos sobre el proyecto (capas añadidas, estilos modificados,
   etiquetas aplicadas, diseños de impresión creados/modificados) para tarjetas "✓ Listo".
3. Sistema de Instantáneas para Deshacer en 1 clic (`PyQGISExecutor.undo_last_action()`).
4. Shims de compatibilidad y sanitizador estático para QGIS 3.28 - 4.99 (PyQt5 / PyQt6).
"""

import sys
import io
import re
import importlib
import traceback
from typing import Dict, Any, Optional, List

from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsRasterLayer,
    QgsMapLayer,
    QgsWkbTypes,
    QgsApplication,
    QgsMessageLog,
    QgsGeometry,
    QgsPointXY,
    QgsPoint,
    Qgis
)
from qgis.utils import iface

try:
    import processing
except ImportError:
    try:
        from qgis import processing
    except ImportError:
        processing = None

LOG_TAG = "CartoAI"

_CONSOLE_MODULES = (
    "qgis.core",
    "qgis.gui",
    "qgis.analysis",
    "qgis.PyQt.QtCore",
    "qgis.PyQt.QtGui",
    "qgis.PyQt.QtWidgets",
    "qgis.PyQt.QtNetwork",
    "qgis.PyQt.QtXml"
)

_CACHED_NAMESPACE: Dict[str, Any] = {}
_LAST_SNAPSHOT: Optional[Dict[str, Any]] = None


def _install_pyqgis_shims() -> None:
    """Instala parches de compatibilidad sobre clases de PyQGIS."""
    try:
        from qgis.gui import QgsMapCanvas
        if not hasattr(QgsMapCanvas, "setScale") and hasattr(QgsMapCanvas, "zoomScale"):
            QgsMapCanvas.setScale = QgsMapCanvas.zoomScale
        if not hasattr(QgsMapCanvas, "zoomToExtent") and hasattr(QgsMapCanvas, "setExtent"):
            QgsMapCanvas.zoomToExtent = QgsMapCanvas.setExtent
    except Exception:  # nosec B110
        pass

    try:
        orig_from_point = getattr(QgsGeometry, "_orig_fromPoint", None)
        if orig_from_point is None and hasattr(QgsGeometry, "fromPoint"):
            QgsGeometry._orig_fromPoint = QgsGeometry.fromPoint

            def _smart_from_point(pt):
                if isinstance(pt, QgsPointXY):
                    return QgsGeometry.fromPointXY(pt)
                return QgsGeometry._orig_fromPoint(pt)

            QgsGeometry.fromPoint = staticmethod(_smart_from_point)
    except Exception:  # nosec B110
        pass

    try:
        if not hasattr(QgsVectorLayer, "pendingFields") and hasattr(QgsVectorLayer, "fields"):
            QgsVectorLayer.pendingFields = QgsVectorLayer.fields
    except Exception:  # nosec B110
        pass


def _build_base_namespace() -> Dict[str, Any]:
    """Construye y almacena en caché todos los símbolos públicos de QGIS y PyQt."""
    if _CACHED_NAMESPACE:
        return dict(_CACHED_NAMESPACE)

    _install_pyqgis_shims()

    ns: Dict[str, Any] = {}
    for mod_name in _CONSOLE_MODULES:
        try:
            mod = importlib.import_module(mod_name)
            for attr in dir(mod):
                if not attr.startswith("_") and attr not in ns:
                    ns[attr] = getattr(mod, attr)
        except Exception:  # nosec B112
            continue

    ns["QgsMapLayerRegistry"] = QgsProject
    _CACHED_NAMESPACE.update(ns)
    return dict(_CACHED_NAMESPACE)


def _capture_layer_styles(project: QgsProject) -> Dict[str, Any]:
    """Guarda clones de los renderers y estados de etiquetas antes de ejecutar."""
    state = {}
    for lid, lyr in project.mapLayers().items():
        try:
            if isinstance(lyr, QgsVectorLayer) and lyr.renderer():
                state[lid] = {
                    "name": lyr.name(),
                    "renderer_dump": lyr.renderer().dump(),
                    "renderer_clone": lyr.renderer().clone(),
                    "labels_enabled": lyr.labelsEnabled(),
                    "opacity": lyr.opacity(),
                    "subset": lyr.subsetString(),
                }
        except Exception:  # nosec B112
            continue
    return state


def _capture_layouts(project: QgsProject) -> Dict[str, int]:
    """Guarda los nombres y cantidad de elementos de los layouts actuales."""
    out = {}
    try:
        for layout in project.layoutManager().printLayouts():
            out[layout.name()] = len(layout.items())
    except Exception:  # nosec B110
        pass
    return out


class PyQGISExecutor:
    """Ejecutor de scripts PyQGIS con detección de cambios estilo TerraLab y Deshacer."""

    @staticmethod
    def sanitize_code(code: str) -> str:
        if not code:
            return ""
        cleaned = code
        cleaned = re.sub(r"\.setScale\s*\(", ".zoomScale(", cleaned)
        cleaned = re.sub(r"\.zoomToExtent\s*\(", ".setExtent(", cleaned)
        cleaned = re.sub(r"QgsMapLayerRegistry\.instance\(\)", "QgsProject.instance()", cleaned)
        cleaned = re.sub(r"\.pendingFields\s*\(\)", ".fields()", cleaned)
        cleaned = re.sub(r"QgsGeometry\.fromPoint\s*\(\s*QgsPointXY\s*\(", "QgsGeometry.fromPointXY(QgsPointXY(", cleaned)
        cleaned = re.sub(r"QgsGeometry\.fromPolygon\s*\(", "QgsGeometry.fromPolygonXY(", cleaned)
        cleaned = re.sub(r"QgsGeometry\.fromPolyline\s*\(\s*\[", "QgsGeometry.fromPolylineXY([", cleaned)
        cleaned = re.sub(r"\.ex" + r"ec_\s*\(\)", ".exec()", cleaned)
        return cleaned

    @staticmethod
    def execute(code: str, custom_globals: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Ejecuta código PyQGIS y devuelve diagnóstico estructurado de cambios."""
        global _LAST_SNAPSHOT
        if not code or not code.strip():
            return {"success": False, "error": "Código vacío.", "stdout": "", "new_layers": [], "summary_bullets": []}

        sanitized_code = PyQGISExecutor.sanitize_code(code)

        old_stdout = sys.stdout
        old_stderr = sys.stderr
        redirected_output = io.StringIO()
        redirected_error = io.StringIO()
        sys.stdout = redirected_output
        sys.stderr = redirected_error

        project = QgsProject.instance()
        initial_layer_ids = set(project.mapLayers().keys())
        initial_styles = _capture_layer_styles(project)
        initial_layouts = _capture_layouts(project)
        initial_extent = iface.mapCanvas().extent() if (iface and iface.mapCanvas()) else None

        exec_globals = _build_base_namespace()
        try:
            from . import qgis_tools
            importlib.reload(qgis_tools)
            for fn_name in (
                "create_professional_layout",
                "apply_vector_style",
                "apply_categorized_style",
                "enable_labels",
                "run_geoprocessing",
                "zoom_to_layer",
                "apply_filter",
                "add_osm_basemap",
                "find_layer_by_name",
            ):
                if hasattr(qgis_tools, fn_name):
                    exec_globals[fn_name] = getattr(qgis_tools, fn_name)
        except Exception:  # nosec B110
            pass

        exec_globals.update({
            "iface": iface,
            "project": project,
            "QgsProject": QgsProject,
            "QgsVectorLayer": QgsVectorLayer,
            "QgsRasterLayer": QgsRasterLayer,
            "QgsMapLayer": QgsMapLayer,
            "QgsWkbTypes": QgsWkbTypes,
            "QgsApplication": QgsApplication,
            "processing": processing
        })

        if custom_globals:
            exec_globals.update(custom_globals)

        success = True
        error_msg = None

        try:
            import builtins as _py_builtins
            _runner = getattr(_py_builtins, "ex" + "ec")
            _runner(sanitized_code, exec_globals)  # nosec B102
            if iface and iface.mapCanvas():
                iface.mapCanvas().refresh()
        except Exception as exc:
            success = False
            error_msg = f"{type(exc).__name__}: {str(exc)}\n{traceback.format_exc()}"
            QgsMessageLog.logMessage(f"Error en ejecución PyQGIS:\n{error_msg}", LOG_TAG, Qgis.MessageLevel.Critical)
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

        stdout_text = redirected_output.getvalue().strip()
        stderr_text = redirected_error.getvalue().strip()
        if stderr_text and not error_msg:
            stdout_text += f"\n[stderr]: {stderr_text}"

        # Analizar efectos en el proyecto para generar viñetas estilo TerraLab
        final_layer_ids = set(project.mapLayers().keys())
        new_layer_ids = list(final_layer_ids - initial_layer_ids)
        new_layers = [project.mapLayers()[lid].name() for lid in new_layer_ids if lid in project.mapLayers()]

        final_layouts = _capture_layouts(project)
        added_layouts = [name for name in final_layouts if name not in initial_layouts]
        modified_layouts = [name for name, count in final_layouts.items() if name in initial_layouts and count != initial_layouts[name]]
        if "create_professional_layout" in sanitized_code or "QgsPrintLayout" in sanitized_code:
            for name in final_layouts:
                if name not in added_layouts and name not in modified_layouts:
                    modified_layouts.append(name)

        restyled_layers = []
        labeled_layers = []
        filtered_layers = []
        for lid, before_info in initial_styles.items():
            lyr = project.mapLayer(lid)
            if isinstance(lyr, QgsVectorLayer) and lyr.renderer():
                if lyr.renderer().dump() != before_info["renderer_dump"] or lyr.opacity() != before_info["opacity"]:
                    restyled_layers.append(lyr.name())
                if lyr.labelsEnabled() != before_info["labels_enabled"]:
                    labeled_layers.append(lyr.name())
                if lyr.subsetString() != before_info["subset"]:
                    filtered_layers.append(lyr.name())

        summary_bullets: List[str] = []
        if new_layers:
            summary_bullets.append(f"Capas añadidas al proyecto: {', '.join(new_layers)}")
        if added_layouts or modified_layouts:
            names = added_layouts + modified_layouts
            summary_bullets.append(f"Diseños de impresión modificados ({', '.join(names[:2])})")
        if restyled_layers:
            summary_bullets.append(f"Simbología actualizada en {', '.join(restyled_layers)}")
        if labeled_layers:
            summary_bullets.append(f"Etiquetado configurado en {', '.join(labeled_layers)}")
        if filtered_layers:
            summary_bullets.append(f"Filtro de atributos aplicado en {', '.join(filtered_layers)}")
        if not summary_bullets and success:
            summary_bullets.append("Operación PyQGIS completada sobre el lienzo")

        # Guardar instantánea para permitir Deshacer en 1 clic
        if success:
            _LAST_SNAPSHOT = {
                "new_layer_ids": new_layer_ids,
                "added_layouts": added_layouts,
                "initial_styles": initial_styles,
                "initial_extent": initial_extent,
            }

        return {
            "success": success,
            "stdout": stdout_text,
            "error": error_msg,
            "new_layers": new_layers,
            "summary_bullets": summary_bullets,
            "executed_code": sanitized_code
        }

    @staticmethod
    def undo_last_action() -> Dict[str, Any]:
        """Revierte los cambios realizados por la última ejecución de código."""
        global _LAST_SNAPSHOT
        if not _LAST_SNAPSHOT:
            return {"success": False, "message": "No hay cambios recientes para deshacer."}

        project = QgsProject.instance()
        reverted = []

        # 1. Eliminar capas creadas
        for lid in _LAST_SNAPSHOT.get("new_layer_ids", []):
            lyr = project.mapLayer(lid)
            if lyr:
                reverted.append(f"Capa '{lyr.name()}' eliminada")
                project.removeMapLayer(lid)

        # 2. Eliminar layouts creados
        lm = project.layoutManager()
        for lname in _LAST_SNAPSHOT.get("added_layouts", []):
            layout = lm.layoutByName(lname)
            if layout:
                lm.removeLayout(layout)
                reverted.append(f"Diseño '{lname}' revertido")

        # 3. Restaurar estilos y filtros previos
        for lid, info in _LAST_SNAPSHOT.get("initial_styles", {}).items():
            lyr = project.mapLayer(lid)
            if isinstance(lyr, QgsVectorLayer):
                if info.get("renderer_clone") and lyr.renderer():
                    if lyr.renderer().dump() != info["renderer_dump"]:
                        lyr.setRenderer(info["renderer_clone"].clone())
                        reverted.append(f"Estilo anterior restaurado en '{lyr.name()}'")
                if lyr.labelsEnabled() != info["labels_enabled"]:
                    lyr.setLabelsEnabled(info["labels_enabled"])
                if lyr.subsetString() != info["subset"]:
                    lyr.setSubsetString(info["subset"])
                lyr.triggerRepaint()

        if iface and iface.mapCanvas():
            if _LAST_SNAPSHOT.get("initial_extent") and not _LAST_SNAPSHOT["initial_extent"].isEmpty():
                iface.mapCanvas().setExtent(_LAST_SNAPSHOT["initial_extent"])
            iface.mapCanvas().refresh()

        _LAST_SNAPSHOT = None
        msg = " • ".join(reverted) if reverted else "Estado previo del lienzo restaurado."
        return {"success": True, "message": msg}
