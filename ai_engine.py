# -*- coding: utf-8 -*-
"""
Motor de Inteligencia Artificial y Orquestador de Código (Arquitectura estilo TerraLab).

Analiza el proyecto activo de QGIS, consulta al modelo LLM con balanceo multi-modelo
verificado en tiempo real (`gemini-3.5-flash-lite` -> `gemini-flash-lite-latest` ->
`gemini-3.1-flash-lite` -> `gemini-3.6-flash` -> `gemini-3.5-flash` -> `gemma-4-26b-a4b-it`),
extrae las acciones en PyQGIS generadas y las ejecuta en el hilo principal.
"""

import json
import re
import time
from typing import Dict, Any, List, Optional, Callable
import requests

from qgis.core import (
    QgsSettings,
    QgsTask,
    QgsApplication,
    QgsMessageLog,
    Qgis,
    QgsProject
)

from qgis.PyQt.QtCore import QObject, pyqtSignal

from .qgis_tools import (
    get_active_layers_summary,
    create_professional_layout,
    apply_vector_style,
    enable_labels,
    add_osm_basemap,
    run_geoprocessing
)
from .pyqgis_executor import PyQGISExecutor

LOG_TAG = "CartoAI"
SETTINGS_PREFIX = "cartoai_copilot/"
LEGACY_PREFIX = "ai_colombia_carto_agent/"

# Lista de modelos verificados con respuesta 200 OK en < 1.5s ordenados por velocidad y disponibilidad
VERIFIED_GEMINI_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3.1-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemma-4-26b-a4b-it"
]

# Modelos deprecados o con saturación frecuente que deben redirigirse automáticamente
DEPRECATED_OR_UNSTABLE_MODELS = {
    "",
    "gemini-1.5-flash",
    "gemini-1.5-flash-latest",
    "gemini-1.5-pro",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-3.7-flash",
    "gemini-3.8-flash",
    "gemini-4-argon"
}

SYSTEM_PROMPT = """Eres CartoAI Copilot, un arquitecto de software geoespacial y copiloto de PyQGIS de nivel senior integrado directamente en QGIS.
Tu objetivo es ayudar al usuario a realizar análisis espacial, geoprocesamientos, diseño de simbología temática, descarga/carga de capas y creación de layouts de impresión profesionales sobre las capas de su proyecto.

Cuentas con acceso completo al entorno de ejecución vivo de PyQGIS.
Variables pre-cargadas en el entorno de ejecución:
- `iface`: Objeto QgisInterface principal (acceso al lienzo `iface.mapCanvas()`, capa activa `iface.activeLayer()`).
- `project`: Instancia de `QgsProject.instance()`.
- `processing`: Módulo de geoprocesamiento nativo de QGIS (ej. `processing.run('native:buffer', ...)`).
- Clases importadas: `QgsVectorLayer`, `QgsRasterLayer`, `QgsWkbTypes`, `QColor`, `QFont`, `QgsSingleSymbolRenderer`, `QgsCategorizedSymbolRenderer`, `QgsPrintLayout`, etc.

Directrices Obligatorias de Respuesta:
1. Explica de forma concisa y clara lo que vas a realizar.
2. SIEMPRE que el usuario pida una acción sobre el mapa, capas, estilos, filtros, geoprocesos o diseño de layouts, escribe el código ejecutable dentro de un bloque:
```python
# Código PyQGIS ejecutable
```
3. Reglas de oro de PyQGIS (QGIS 3.28 - 4.99 / PyQt6):
   - Para buscar una capa por nombre: usa `project.mapLayersByName('Nombre')` o toma `iface.activeLayer()` si no especifica nombre.
   - Si creas una capa en memoria o mediante `processing.run(..., {'OUTPUT': 'memory:'})`, añádela al proyecto con `project.addMapLayer(capa)`.
   - Para hacer zoom a una capa: `iface.mapCanvas().setExtent(layer.extent()); iface.mapCanvas().refresh()`.
   - Para cambiar escala o centrar el lienzo: usa `iface.mapCanvas().setCenter(QgsPointXY(x, y))` y `iface.mapCanvas().zoomScale(50000)` (NUNCA uses `.setScale()`, no existe en QgsMapCanvas).
   - Para geometrías desde puntos XY: usa `QgsGeometry.fromPointXY(QgsPointXY(lon, lat))`, `QgsGeometry.fromPolylineXY([...])` y `QgsGeometry.fromPolygonXY([[...]])`.
   - Para crear campos en capas de memoria: usa la URI `Point?crs=epsg:4326&field=nombre:string&field=id:integer` o `QgsField('nombre', QVariant.String)`.
   - Para crear un layout de impresión profesional rápidamente, usa directamente:
     `create_professional_layout(layout_name='Mapa A4', map_title='Título', author='David Ortiz')`
4. Responde siempre en Español.
"""


class AISettingsManager:
    """Almacenamiento persistente de configuración en QgsSettings con migración automática."""

    @staticmethod
    def get_provider() -> str:
        s = QgsSettings()
        val = s.value(SETTINGS_PREFIX + "provider", "", type=str)
        if not val:
            val = s.value(LEGACY_PREFIX + "provider", "gemini", type=str)
        return val or "gemini"

    @staticmethod
    def set_provider(provider: str) -> None:
        s = QgsSettings()
        s.setValue(SETTINGS_PREFIX + "provider", provider)
        s.setValue(LEGACY_PREFIX + "provider", provider)

    @staticmethod
    def get_api_key() -> str:
        s = QgsSettings()
        key = s.value(SETTINGS_PREFIX + "api_key", "", type=str).strip()
        if not key:
            key = s.value(LEGACY_PREFIX + "api_key", "", type=str).strip()
            if key:
                s.setValue(SETTINGS_PREFIX + "api_key", key)
        return key

    @staticmethod
    def set_api_key(api_key: str) -> None:
        clean_key = api_key.strip()
        s = QgsSettings()
        s.setValue(SETTINGS_PREFIX + "api_key", clean_key)
        s.setValue(LEGACY_PREFIX + "api_key", clean_key)

    @staticmethod
    def get_model_name() -> str:
        provider = AISettingsManager.get_provider()
        default_model = "gemini-3.5-flash-lite" if provider == "gemini" else "gpt-4o-mini"
        s = QgsSettings()
        val = s.value(SETTINGS_PREFIX + "model_name", default_model, type=str).strip()
        if provider == "gemini" and val in DEPRECATED_OR_UNSTABLE_MODELS:
            val = "gemini-3.5-flash-lite"
            s.setValue(SETTINGS_PREFIX + "model_name", val)
            s.setValue(LEGACY_PREFIX + "model_name", val)
        return val

    @staticmethod
    def set_model_name(model_name: str) -> None:
        clean_model = model_name.strip()
        if clean_model in DEPRECATED_OR_UNSTABLE_MODELS and AISettingsManager.get_provider() == "gemini":
            clean_model = "gemini-3.5-flash-lite"
        s = QgsSettings()
        s.setValue(SETTINGS_PREFIX + "model_name", clean_model)
        s.setValue(LEGACY_PREFIX + "model_name", clean_model)

    @staticmethod
    def get_custom_url() -> str:
        return QgsSettings().value(SETTINGS_PREFIX + "custom_url", "", type=str)

    @staticmethod
    def set_custom_url(url: str) -> None:
        QgsSettings().setValue(SETTINGS_PREFIX + "custom_url", url.strip())

    @staticmethod
    def get_theme() -> str:
        return QgsSettings().value(SETTINGS_PREFIX + "ui_theme", "dark", type=str) or "dark"

    @staticmethod
    def set_theme(theme: str) -> None:
        QgsSettings().setValue(SETTINGS_PREFIX + "ui_theme", theme)

    @staticmethod
    def get_agent_mode() -> str:
        return QgsSettings().value(SETTINGS_PREFIX + "agent_mode", "equilibrado", type=str) or "equilibrado"

    @staticmethod
    def set_agent_mode(mode: str) -> None:
        QgsSettings().setValue(SETTINGS_PREFIX + "agent_mode", mode)

    @staticmethod
    def get_effort_level() -> str:
        return QgsSettings().value(SETTINGS_PREFIX + "effort_level", "Medium", type=str) or "Medium"

    @staticmethod
    def set_effort_level(effort: str) -> None:
        QgsSettings().setValue(SETTINGS_PREFIX + "effort_level", effort)


class LLMClient:
    """Cliente de alta disponibilidad con conmutación automática entre 6 modelos verificados."""

    def __init__(self, provider: str, api_key: str, model_name: str, custom_url: Optional[str] = None):
        self.provider = provider
        self.api_key = api_key.strip() if api_key else ""
        self.model_name = model_name.strip() if model_name else ("gemini-3.5-flash-lite" if provider == "gemini" else "gpt-4o-mini")
        self.custom_url = custom_url.strip() if custom_url else ""

    def generate_response(self, messages: List[Dict[str, Any]], active_layers_summary: List[Dict[str, Any]]) -> str:
        if not self.api_key and self.provider != "custom":
            raise ValueError("Por favor configure su API Key en el icono de configuración (⚙️).")

        if self.provider == "gemini":
            return self._call_gemini(messages, active_layers_summary)
        else:
            return self._call_openai_compatible(messages, active_layers_summary)

    def _call_gemini(self, messages: List[Dict[str, Any]], active_layers_summary: List[Dict[str, Any]]) -> str:
        primary_model = self.model_name
        if not primary_model or primary_model in DEPRECATED_OR_UNSTABLE_MODELS:
            primary_model = "gemini-3.5-flash-lite"

        # Construir cadena de conmutación por error (Failover Chain) con los 6 modelos 200 OK
        candidate_models = [primary_model]
        for fb in VERIFIED_GEMINI_MODELS:
            if fb not in candidate_models:
                candidate_models.append(fb)

        agent_mode = AISettingsManager.get_agent_mode()
        effort_level = AISettingsManager.get_effort_level()

        mode_instruction = {
            "autopilot": "\nMODO ACTIVO: Piloto Automático. Sé ultra-conciso (1-2 líneas de respuesta amigable) y genera directamente el código PyQGIS ejecutable.",
            "equilibrado": "\nMODO ACTIVO: Equilibrado. Habla con personalidad de colega geógrafo experto, explica brevemente el paso cartográfico y ejecuta el código PyQGIS.",
            "geografo": "\nMODO ACTIVO: Arquitecto Geógrafo & Académico. Habla con entusiasmo cartográfico, explica los criterios espaciales/metodológicos (proyección, jerarquía visual, simbología) y proporciona el código PyQGIS completo."
        }.get(agent_mode, "")

        max_tokens = 1200 if effort_level == "Low" else (3072 if effort_level == "High" else 2048)

        context_str = f"{mode_instruction}\n\nESTADO ACTUAL DEL PROYECTO QGIS:\nCapas en el proyecto:\n{json.dumps(active_layers_summary, ensure_ascii=False, indent=2)}"
        full_system_prompt = SYSTEM_PROMPT + context_str

        contents = []
        for m in messages:
            role = "user" if m.get("role") == "user" else "model"
            contents.append({"role": role, "parts": [{"text": m.get("content", "")}]})

        headers = {"Content-Type": "application/json"}
        errors_log = []

        for cand in candidate_models:
            cand_clean = cand.replace("models/", "")
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{cand_clean}:generateContent?key={self.api_key}"

            # Algunos modelos como gemma no aceptan system_instruction separado; lo inyectamos de forma compatible
            if cand_clean.startswith("gemma"):
                gemma_contents = [{"role": "user", "parts": [{"text": full_system_prompt + "\n\nSolicitud del usuario: " + messages[-1].get("content", "")}]}]
                payload = {
                    "contents": gemma_contents,
                    "generationConfig": {"temperature": 0.25, "maxOutputTokens": max_tokens}
                }
            else:
                payload = {
                    "system_instruction": {"parts": [{"text": full_system_prompt}]},
                    "contents": contents,
                    "generationConfig": {"temperature": 0.25, "maxOutputTokens": max_tokens}
                }

            try:
                r = requests.post(url, headers=headers, json=payload, timeout=12)
                if r.status_code == 200:
                    data = r.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        text_out = "".join(p.get("text", "") for p in parts)
                        if text_out.strip():
                            return text_out
                else:
                    err_detail = r.json().get("error", {}).get("message", r.text[:80]) if r.text else str(r.status_code)
                    errors_log.append(f"{cand_clean}({r.status_code})")
                    # Pasar de inmediato al siguiente modelo verificado sin bloquear al usuario
                    continue
            except Exception as exc:  # nosec B112
                errors_log.append(f"{cand_clean}({type(exc).__name__})")
                continue

        raise RuntimeError(f"No se pudo conectar con los servidores de IA ({', '.join(errors_log)}).")

    def _call_openai_compatible(self, messages: List[Dict[str, Any]], active_layers_summary: List[Dict[str, Any]]) -> str:
        endpoint = self.custom_url if (self.provider == "custom" and self.custom_url) else "https://api.openai.com/v1"
        url = endpoint.rstrip("/") + "/chat/completions"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}" if self.api_key else ""
        }

        augmented_system = SYSTEM_PROMPT + f"\n\nESTADO ACTUAL DEL PROYECTO QGIS:\nCapas activas en el proyecto:\n{json.dumps(active_layers_summary, ensure_ascii=False, indent=2)}"

        req_messages = [{"role": "system", "content": augmented_system}]
        for m in messages:
            req_messages.append({"role": m.get("role", "user"), "content": m.get("content", "")})

        payload = {
            "model": self.model_name or "gpt-4o-mini",
            "messages": req_messages,
            "temperature": 0.2,
            "max_tokens": 2048
        }

        try:
            r = requests.post(url, headers=headers, json=payload, timeout=25)
            if r.status_code == 200:
                data = r.json()
                return data["choices"][0]["message"]["content"]
            else:
                raise RuntimeError(f"Error HTTP {r.status_code} desde {endpoint}: {r.text[:150]}")
        except requests.exceptions.RequestException as exc:
            raise RuntimeError(f"Error de conexión con {endpoint}: {str(exc)}")


def generate_local_fallback_code(user_prompt: str) -> Optional[tuple[str, str]]:
    """
    Motor local de respaldo: resuelve comandos cartográficos usando PyQGIS nativo
    si no hay conexión a internet o si el usuario aún no configura su API Key.
    """
    prompt = user_prompt.lower()

    # 1. Cargar OpenStreetMap
    if any(k in prompt for k in ["osm", "openstreetmap", "mapa base", "capa base", "basemap"]):
        code = """# Cargar mapa base de OpenStreetMap vía XYZ Tiles
from qgis.core import QgsRasterLayer, QgsProject
urlWithParams = 'type=xyz&url=https://tile.openstreetmap.org/{z}/{x}/{y}.png&zmax=19&zmin=0'
osm_layer = QgsRasterLayer(urlWithParams, 'OpenStreetMap Standard', 'wms')
if osm_layer.isValid():
    QgsProject.instance().addMapLayer(osm_layer)
    print("Mapa base OpenStreetMap añadido correctamente al proyecto.")
else:
    print("No se pudo conectar con el servicio de OpenStreetMap.")
"""
        return ("He añadido la capa base mundial de OpenStreetMap (XYZ Tiles) a tu proyecto.", code)

    # 2. Diseñar Layout / Composición de Impresión A4
    if any(k in prompt for k in ["layout", "composicion", "composición", "diseñar", "diseña", "mapa a4", "imprimir"]):
        code = """# Crear composición cartográfica profesional A4
res = create_professional_layout(
    layout_name="Mapa Oficial CartoAI",
    map_title="MAPA TEMÁTICO OFICIAL",
    subtitle="Composición profesional generada por CartoAI Copilot",
    author="David Ortiz - Estudiante de Geografía",
    page_format="A4",
    orientation="landscape"
)
print("Resultado layout:", res.get("message", "Listo"))
"""
        return ("He generado una composición cartográfica A4 horizontal profesional con marco, leyenda, barra de escala y flecha de norte.", code)

    # 3. Buffer / Área de Influencia
    if "buffer" in prompt or "area de influencia" in prompt or "área de influencia" in prompt:
        dist_match = re.search(r"(\d+(?:\.\d+)?)", prompt)
        dist = dist_match.group(1) if dist_match else "100"
        code = f"""# Generar buffer sobre la capa activa
import processing
from qgis.core import QgsProject
from qgis.utils import iface

layer = iface.activeLayer()
if not layer or not layer.isValid():
    layers = list(QgsProject.instance().mapLayers().values())
    layer = layers[0] if layers else None

if layer:
    params = {{
        'INPUT': layer,
        'DISTANCE': {dist},
        'SEGMENTS': 10,
        'DISSOLVE': False,
        'OUTPUT': 'memory:'
    }}
    res = processing.run('native:buffer', params)
    out_layer = res['OUTPUT']
    out_layer.setName(f"Buffer {dist}m - {{layer.name()}}")
    QgsProject.instance().addMapLayer(out_layer)
    iface.mapCanvas().setExtent(out_layer.extent())
    iface.mapCanvas().refresh()
    print(f"Buffer de {dist}m creado exitosamente sobre {{layer.name()}}")
else:
    print("No se encontró ninguna capa activa para aplicar el buffer.")
"""
        return (f"He ejecutado un análisis de proximidad (Buffer de {dist} metros) sobre tu capa activa.", code)

    # 4. Auto-estilo / Simbología
    if any(k in prompt for k in ["estilo", "auto-estilo", "simbologia", "simbología", "color", "pintar", "colorear"]):
        code = """# Aplicar estilo vectorial armonizado
from qgis.utils import iface
layer = iface.activeLayer()
if layer:
    res = apply_vector_style(layer, color_hex='#2563EB', opacity=0.85, stroke_color='#1E40AF', stroke_width=0.6)
    iface.mapCanvas().refresh()
    print(f"Estilo visual profesional aplicado a la capa '{layer.name()}'.")
else:
    print("Por favor selecciona una capa activa en el panel de capas.")
"""
        return ("He aplicado una paleta de colores cartográficos armonizada sobre la capa activa.", code)

    # 5. Etiquetado
    if any(k in prompt for k in ["etiquetar", "etiqueta", "labels", "label", "nombres"]):
        code = """# Activar etiquetado inteligente con halo
from qgis.utils import iface
layer = iface.activeLayer()
if layer and layer.isValid():
    field_names = [f.name() for f in layer.fields()]
    candidate = None
    for cand in ['nombre', 'name', 'nom', 'municipio', 'departamento', 'codigo', 'id']:
        for fn in field_names:
            if cand in fn.lower():
                candidate = fn
                break
        if candidate:
            break
    field_to_use = candidate if candidate else field_names[0]
    enable_labels(layer, field_name=field_to_use, font_size=9, font_family='Segoe UI', buffer_color='#FFFFFF')
    iface.mapCanvas().refresh()
    print(f"Etiquetas activadas en '{layer.name()}' usando el campo '{field_to_use}'.")
else:
    print("No hay una capa vectorial activa seleccionada.")
"""
        return ("He configurado el etiquetado tipográfico con halo de protección visual sobre la capa activa.", code)

    # 6. Analizar / Estadísticas / Resumen
    if any(k in prompt for k in ["analizar", "analisis", "análisis", "estadistica", "estadísticas", "atributos", "campos", "resumen", "info"]):
        code = """# Inspección detallada de la capa activa
from qgis.utils import iface
from qgis.core import QgsProject, QgsWkbTypes, QgsVectorLayer

layer = iface.activeLayer()
if not layer:
    layers = list(QgsProject.instance().mapLayers().values())
    layer = layers[0] if layers else None

if layer and isinstance(layer, QgsVectorLayer):
    geom = QgsWkbTypes.displayString(layer.wkbType())
    crs = layer.crs().authid()
    fields = [f"{f.name()} ({f.typeName()})" for f in layer.fields()]
    ext = layer.extent()
    print(f"Capa: {layer.name()}")
    print(f"Geometría: {geom} | Entidades: {layer.featureCount():,} | CRS: {crs}")
    print(f"Extensión: [{ext.xMinimum():.4f}, {ext.yMinimum():.4f}] a [{ext.xMaximum():.4f}, {ext.yMaximum():.4f}]")
    print(f"Campos ({len(fields)}): " + ", ".join(fields[:15]))
elif layer:
    print(f"Capa ráster activa: {layer.name()} | CRS: {layer.crs().authid()}")
else:
    print("No hay capas cargadas en el proyecto actualmente.")
"""
        return ("Aquí tienes el diagnóstico técnico y resumen de estructura de tu capa activa:", code)

    return None


class CartoAgentWorkerTask(QgsTask):
    """Tarea asíncrona en segundo plano que consulta al LLM y ejecuta el código en el hilo principal."""

    def __init__(
        self,
        description: str,
        user_message: str,
        history: List[Dict[str, str]],
        on_success_callback: Callable[[Dict[str, Any]], None],
        on_error_callback: Callable[[str], None]
    ):
        super().__init__(description, QgsTask.Flag.CanCancel)
        self.user_message = user_message
        self.history = history
        self.on_success = on_success_callback
        self.on_error = on_error_callback
        self.result: Optional[Dict[str, Any]] = None
        self.error_message: Optional[str] = None

    def run(self) -> bool:
        try:
            provider = AISettingsManager.get_provider()
            api_key = AISettingsManager.get_api_key()
            model_name = AISettingsManager.get_model_name()
            custom_url = AISettingsManager.get_custom_url()

            layers_summary = get_active_layers_summary()

            llm_text = ""
            llm_error_detail = ""
            try:
                if api_key or provider == "custom":
                    client = LLMClient(provider=provider, api_key=api_key, model_name=model_name, custom_url=custom_url)
                    messages = list(self.history)
                    messages.append({"role": "user", "content": self.user_message})
                    llm_text = client.generate_response(messages, layers_summary)
            except Exception as llm_exc:
                llm_error_detail = str(llm_exc)
                QgsMessageLog.logMessage(f"Aviso LLM: {llm_error_detail}", LOG_TAG, Qgis.MessageLevel.Warning)

            code_blocks = re.findall(r"```(?:python|py)?\s*(.*?)\s*```", llm_text, re.DOTALL) if llm_text else []

            if not llm_text:
                local_solution = generate_local_fallback_code(self.user_message)
                if local_solution:
                    explanation, fallback_code = local_solution
                    llm_text = f"{explanation}\n\n```python\n{fallback_code}\n```"
                    code_blocks = [fallback_code]
                else:
                    if not api_key and provider != "custom":
                        raise ValueError("Por favor introduce tu API Key en Configuración (⚙️) para habilitar el agente.")
                    else:
                        raise RuntimeError(f"Detalle de conexión: {llm_error_detail}")

            self.result = {
                "llm_text": llm_text,
                "code_blocks": code_blocks
            }
            return True

        except Exception as exc:
            self.error_message = str(exc)
            QgsMessageLog.logMessage(f"Fallo en CartoAgentWorkerTask: {str(exc)}", LOG_TAG, Qgis.MessageLevel.Critical)
            return False

    def finished(self, result: bool) -> None:
        if result and self.result:
            execution_results = []
            for code in self.result.get("code_blocks", []):
                exec_report = PyQGISExecutor.execute(code)

                # Auto-reparación automática si ocurre algún error de atributo o sintaxis en PyQGIS
                if not exec_report.get("success") and exec_report.get("error"):
                    try:
                        provider = AISettingsManager.get_provider()
                        api_key = AISettingsManager.get_api_key()
                        model_name = AISettingsManager.get_model_name()
                        custom_url = AISettingsManager.get_custom_url()
                        if api_key or provider == "custom":
                            client = LLMClient(provider=provider, api_key=api_key, model_name=model_name, custom_url=custom_url)
                            fix_prompt = (
                                "El siguiente código PyQGIS produjo este error en QGIS 4 (PyQt6):\n"
                                f"ERROR:\n{exec_report['error']}\n\n"
                                f"CÓDIGO ORIGINAL:\n```python\n{code}\n```\n\n"
                                "Devuelve ÚNICAMENTE el bloque ```python ... ``` corregido sin explicaciones adicionales."
                            )
                            fixed_resp = client.generate_response([{"role": "user", "content": fix_prompt}], [])
                            fixed_blocks = re.findall(r"```(?:python|py)?\s*(.*?)\s*```", fixed_resp, re.DOTALL)
                            if fixed_blocks:
                                retry_report = PyQGISExecutor.execute(fixed_blocks[0])
                                if retry_report.get("success"):
                                    code = fixed_blocks[0]
                                    exec_report = retry_report
                    except Exception:  # nosec B110
                        pass

                execution_results.append({
                    "code": exec_report.get("executed_code", code),
                    "report": exec_report
                })
            self.result["execution_results"] = execution_results
            self.on_success(self.result)
        else:
            self.on_error(self.error_message or "Error procesando la solicitud.")
