# -*- coding: utf-8 -*-
"""
Motor de Inteligencia Artificial para CartoAI Copilot: Map & GIS Architect.

Gestiona la conexión con modelos LLM (Google Gemini y OpenAI), orquesta
el Function Calling de herramientas cartográficas (simbología, geoprocesamiento
y diseño de composiciones de impresión) y ejecuta las tareas en segundo plano
mediante QgsTask sin congelar la interfaz de QGIS.
Compatible con QGIS 3 y QGIS 4.
"""

import json
from typing import Dict, Any, List, Optional, Callable
import requests

from qgis.core import (
    QgsSettings,
    QgsTask,
    QgsApplication,
    QgsMessageLog,
    Qgis
)

try:
    from qgis.PyQt.QtCore import QObject, pyqtSignal
except ImportError:
    from PyQt5.QtCore import QObject, pyqtSignal

from .qgis_tools import (
    get_active_layers_summary,
    apply_vector_style,
    apply_categorized_style,
    enable_labels,
    run_geoprocessing,
    create_professional_layout,
    zoom_to_layer,
    apply_filter
)

LOG_TAG = "CartoAICopilot"
SETTINGS_PREFIX = "cartoai_copilot/"

# Esquema de herramientas de Cartografía y Geoprocesamiento expuesto al LLM
CARTOGRAPHY_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "inspect_active_layers",
            "description": "Inspecciona todas las capas cargadas actualmente en el proyecto QGIS (geometría, CRS, conteo de entidades, campos y valores de muestra).",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_professional_layout",
            "description": "Diseña una composición cartográfica de impresión lista para exportar (QgsPrintLayout) con mapa centrado, título, subtítulo, leyenda, escala gráfica y norte.",
            "parameters": {
                "type": "object",
                "properties": {
                    "layout_name": {
                        "type": "string",
                        "description": "Nombre de la composición (ej. 'Mapa_Final_2026')."
                    },
                    "title": {
                        "type": "string",
                        "description": "Título principal del mapa (ej. 'Mapa de Cobertura y Uso del Suelo')."
                    },
                    "subtitle": {
                        "type": "string",
                        "description": "Subtítulo descriptivo o zona de estudio.",
                        "default": "Generado por CartoAI Copilot"
                    },
                    "author": {
                        "type": "string",
                        "description": "Nombre del autor o entidad cartográfica.",
                        "default": "David Ortiz (Geografía)"
                    },
                    "orientation": {
                        "type": "string",
                        "description": "Orientación de la página: 'landscape' (horizontal) o 'portrait' (vertical).",
                        "default": "landscape"
                    },
                    "include_legend": {
                        "type": "boolean",
                        "description": "Si se debe incluir leyenda dinámica.",
                        "default": True
                    },
                    "include_scalebar": {
                        "type": "boolean",
                        "description": "Si se debe incluir barra de escala gráfica.",
                        "default": True
                    },
                    "include_north": {
                        "type": "boolean",
                        "description": "Si se debe incluir flecha de orientación al norte.",
                        "default": True
                    }
                },
                "required": ["layout_name", "title"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "apply_vector_style",
            "description": "Aplica una simbología de color único armonizada y adaptativa a una capa vectorial (puntos, líneas o polígonos).",
            "parameters": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Nombre de la capa en el proyecto."
                    },
                    "color": {
                        "type": "string",
                        "description": "Color principal en formato Hex (#RRGGBB, ej. '#2A9D8F', '#E76F51', '#457B9D')."
                    },
                    "outline_color": {
                        "type": "string",
                        "description": "Color del contorno (#RRGGBB).",
                        "default": "#1D3557"
                    },
                    "size_or_width": {
                        "type": "number",
                        "description": "Tamaño del marcador en mm (puntos) o grosor de línea/borde.",
                        "default": 2.0
                    },
                    "opacity": {
                        "type": "number",
                        "description": "Opacidad de 0.0 a 1.0.",
                        "default": 1.0
                    }
                },
                "required": ["layer_name", "color"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "apply_categorized_style",
            "description": "Aplica una clasificación cualitativa/categorizada con colores diferenciados según un campo de atributos.",
            "parameters": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Nombre de la capa objetivo."
                    },
                    "field_name": {
                        "type": "string",
                        "description": "Nombre del campo por el cual clasificar (ej. 'TIPO', 'CATEGORIA', 'DEPTO')."
                    },
                    "color_ramp_name": {
                        "type": "string",
                        "description": "Nombre de la rampa de color de QGIS: 'Spectral', 'Viridis', 'Plasma', 'Set1', 'Accent', 'Turbo'.",
                        "default": "Spectral"
                    }
                },
                "required": ["layer_name", "field_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "enable_labels",
            "description": "Activa el etiquetado de texto en una capa con halo protector (buffer) para máxima legibilidad cartográfica.",
            "parameters": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Nombre de la capa a etiquetar."
                    },
                    "field_name": {
                        "type": "string",
                        "description": "Nombre del campo cuyos valores se mostrarán como texto."
                    },
                    "font_size": {
                        "type": "integer",
                        "description": "Tamaño de fuente en puntos.",
                        "default": 9
                    },
                    "font_color": {
                        "type": "string",
                        "description": "Color del texto (#RRGGBB).",
                        "default": "#1E293B"
                    },
                    "halo_color": {
                        "type": "string",
                        "description": "Color del halo de protección alrededor de las letras.",
                        "default": "#FFFFFF"
                    }
                },
                "required": ["layer_name", "field_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_geoprocessing",
            "description": "Ejecuta un geoproceso nativo de QGIS (Processing: buffers, clips, centroides, disolver) y añade el resultado al proyecto.",
            "parameters": {
                "type": "object",
                "properties": {
                    "algorithm_id": {
                        "type": "string",
                        "description": "ID del algoritmo de QGIS: 'native:buffer', 'native:clip', 'native:centroids', 'native:dissolve', 'native:convexhull'."
                    },
                    "parameters": {
                        "type": "object",
                        "description": "Diccionario con los parámetros del algoritmo (ej. {'INPUT': 'vias', 'DISTANCE': 100} para buffer)."
                    },
                    "output_layer_name": {
                        "type": "string",
                        "description": "Nombre para la nueva capa generada (ej. 'Buffer_Rios_100m')."
                    }
                },
                "required": ["algorithm_id", "parameters"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "zoom_to_layer",
            "description": "Encuadra y centra el mapa de QGIS sobre la extensión espacial de la capa indicada.",
            "parameters": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Nombre de la capa hacia la cual hacer zoom."
                    }
                },
                "required": ["layer_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "apply_filter",
            "description": "Aplica una consulta de filtro SQL (setSubsetString) sobre los atributos de una capa para mostrar solo registros específicos.",
            "parameters": {
                "type": "object",
                "properties": {
                    "layer_name": {
                        "type": "string",
                        "description": "Nombre de la capa."
                    },
                    "sql_expression": {
                        "type": "string",
                        "description": "Expresión SQL de QGIS o 'CLEAR' para remover el filtro."
                    }
                },
                "required": ["layer_name", "sql_expression"]
            }
        }
    }
]

SYSTEM_PROMPT = """Eres 'CartoAI Copilot', un asistente de inteligencia artificial senior, arquitecto geoespacial y maestro cartógrafo integrado en QGIS.
Tu misión es interpretar la información geográfica del proyecto activo (a nivel mundial), ejecutar geoprocesamientos espaciales avanzados y construir mapas y composiciones de impresión de estándar profesional.

Tus Capacidades Centrales:
1. ANÁLISIS DE DATOS: Inspeccionas capas cargadas ('inspect_active_layers') para entender geometrías, sistemas de coordenadas (CRS), atributos y valores.
2. DISEÑO CARTOGRÁFICO Y SIMBOLOGÍA:
   - Aplicas estilos con paletas cromáticas armónicas y profesionales ('apply_vector_style').
   - Clasificas temáticamente capas cualitativas o cuantitativas con rampas armónicas ('apply_categorized_style').
   - Activas etiquetas tipográficas con halo blanco para garantizar legibilidad contra el fondo ('enable_labels').
3. COMPOSICIÓN DE IMPRESIÓN (LAYOUTS):
   - Cuando el usuario te pida crear o diseñar un mapa/layout, utiliza 'create_professional_layout' para generar la composición completa en formato A4 con mapa centrado, título, subtítulo, autor, leyenda dinámica, barra de escala gráfica y flecha de norte.
4. GEOPROCESAMIENTO AVANZADO:
   - Ejecutas herramientas espaciales con 'run_geoprocessing' (ej. buffers de proximidad con 'native:buffer', cortes espaciales con 'native:clip', centroides con 'native:centroids', disolver límites con 'native:dissolve').
5. NAVEGACIÓN Y FILTROS:
   - Ajustas el zoom del lienzo con 'zoom_to_layer' y aplicas consultas SQL con 'apply_filter'.

Estilo de Comunicación:
- Responde siempre de forma clara, técnica y concisa en Español.
- Utiliza formato Markdown con viñetas para explicar las acciones realizadas y destacar los nombres de capas y herramientas.
"""


class AISettingsManager:
    """Gestiona la persistencia de credenciales y modelos en QgsSettings."""

    @staticmethod
    def get_provider() -> str:
        settings = QgsSettings()
        return settings.value(SETTINGS_PREFIX + "provider", "gemini", type=str)

    @staticmethod
    def set_provider(provider: str) -> None:
        settings = QgsSettings()
        settings.setValue(SETTINGS_PREFIX + "provider", provider)

    @staticmethod
    def get_api_key() -> str:
        settings = QgsSettings()
        return settings.value(SETTINGS_PREFIX + "api_key", "", type=str)

    @staticmethod
    def set_api_key(api_key: str) -> None:
        settings = QgsSettings()
        settings.setValue(SETTINGS_PREFIX + "api_key", api_key.strip())

    @staticmethod
    def get_model_name() -> str:
        settings = QgsSettings()
        provider = AISettingsManager.get_provider()
        default_model = "gemini-3.5-flash-lite" if provider == "gemini" else "gpt-4o-mini"
        val = settings.value(SETTINGS_PREFIX + "model_name", default_model, type=str)
        if provider == "gemini" and val in ("gemini-1.5-flash", "gemini-2.0-flash", "gemini-3.5-flash", ""):
            val = "gemini-3.5-flash-lite"
            settings.setValue(SETTINGS_PREFIX + "model_name", val)
        return val

    @staticmethod
    def set_model_name(model_name: str) -> None:
        settings = QgsSettings()
        settings.setValue(SETTINGS_PREFIX + "model_name", model_name.strip())


class LLMClient:
    """Cliente HTTP optimizado con fallback automático entre modelos para cero latencia."""

    def __init__(self, provider: str, api_key: str, model_name: str):
        self.provider = provider.lower()
        self.api_key = api_key.strip()
        self.model_name = model_name.strip()

    def generate_response(self, messages: List[Dict[str, Any]], active_layers_summary: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not self.api_key:
            raise ValueError("Por favor configure su API Key en el icono de engranaje (⚙️).")

        if self.provider == "gemini":
            return self._call_gemini(messages, active_layers_summary)
        else:
            return self._call_openai(messages, active_layers_summary)

    def _call_openai(self, messages: List[Dict[str, Any]], active_layers_summary: List[Dict[str, Any]]) -> Dict[str, Any]:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        augmented_system = SYSTEM_PROMPT + f"\n\nESTADO ACTUAL DEL PROYECTO QGIS:\nCapas cargadas: {json.dumps(active_layers_summary, ensure_ascii=False)}"

        payload_messages = [{"role": "system", "content": augmented_system}]
        for m in messages:
            payload_messages.append({"role": m["role"], "content": m["content"]})

        payload = {
            "model": self.model_name or "gpt-4o-mini",
            "messages": payload_messages,
            "tools": CARTOGRAPHY_TOOLS_SCHEMA,
            "tool_choice": "auto",
            "temperature": 0.2
        }

        response = requests.post(url, headers=headers, json=payload, timeout=25)
        response.raise_for_status()
        data = response.json()

        choice = data["choices"][0]
        message = choice["message"]
        tool_calls = message.get("tool_calls", [])

        parsed = []
        for tc in tool_calls:
            parsed.append({
                "id": tc.get("id"),
                "name": tc["function"]["name"],
                "arguments": json.loads(tc["function"].get("arguments", "{}"))
            })

        return {"content": message.get("content") or "", "tool_calls": parsed}

    def _call_gemini(self, messages: List[Dict[str, Any]], active_layers_summary: List[Dict[str, Any]]) -> Dict[str, Any]:
        preferred_model = self.model_name or "gemini-3.5-flash-lite"
        if preferred_model in ("gemini-1.5-flash", "gemini-2.0-flash", "gemini-3.5-flash", ""):
            preferred_model = "gemini-3.5-flash-lite"

        candidate_models = [preferred_model]
        for fb in ["gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-3.5-flash"]:
            if fb not in candidate_models:
                candidate_models.append(fb)

        gemini_tools = [
            {
                "name": t["function"]["name"],
                "description": t["function"]["description"],
                "parameters": t["function"]["parameters"]
            }
            for t in CARTOGRAPHY_TOOLS_SCHEMA
        ]

        augmented_system = SYSTEM_PROMPT + f"\n\nESTADO ACTUAL DEL PROYECTO QGIS:\nCapas cargadas: {json.dumps(active_layers_summary, ensure_ascii=False)}"

        contents = []
        for m in messages:
            role = "user" if m["role"] == "user" else "model"
            contents.append({"role": role, "parts": [{"text": m["content"]}]})

        payload = {
            "system_instruction": {"parts": [{"text": augmented_system}]},
            "contents": contents,
            "tools": [{"function_declarations": gemini_tools}],
            "generationConfig": {"temperature": 0.2}
        }

        headers = {"Content-Type": "application/json"}
        last_err = None

        for cand in candidate_models:
            clean_m = cand if cand.startswith("models/") else f"models/{cand}"
            url = f"https://generativelanguage.googleapis.com/v1beta/{clean_m}:generateContent?key={self.api_key}"

            try:
                r = requests.post(url, headers=headers, json=payload, timeout=15)
                if r.status_code == 200:
                    data = r.json()
                    candidates = data.get("candidates", [])
                    if not candidates:
                        return {"content": "No se recibió respuesta del modelo.", "tool_calls": []}

                    content_obj = candidates[0].get("content", {})
                    parts = content_obj.get("parts", [])

                    text_content = ""
                    tool_calls = []

                    for p in parts:
                        if "text" in p:
                            text_content += p["text"]
                        if "functionCall" in p:
                            fc = p["functionCall"]
                            tool_calls.append({
                                "id": fc.get("name"),
                                "name": fc.get("name"),
                                "arguments": fc.get("args", {})
                            })

                    return {"content": text_content, "tool_calls": tool_calls}

                elif r.status_code in (503, 429, 500, 404):
                    last_err = f"{r.status_code}: {r.text[:150]}"
                    continue
                else:
                    r.raise_for_status()

            except requests.exceptions.RequestException as exc:
                last_err = str(exc)
                continue

        raise ValueError(f"Servicio temporalmente no disponible: {last_err}")


class CartoAgentWorkerTask(QgsTask):
    """Tarea asíncrona en segundo plano para procesar razonamiento cartográfico y geoprocesos."""

    def __init__(
        self,
        description: str,
        user_message: str,
        history: List[Dict[str, str]],
        on_success_callback: Callable[[Dict[str, Any]], None],
        on_error_callback: Callable[[str], None]
    ):
        super().__init__(description, QgsTask.CanCancel)
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

            if not api_key:
                raise ValueError("Por favor configure la API Key en el icono de engranaje (⚙️).")

            client = LLMClient(provider=provider, api_key=api_key, model_name=model_name)
            layers_summary = get_active_layers_summary()

            messages = list(self.history)
            messages.append({"role": "user", "content": self.user_message})

            llm_result = client.generate_response(messages, layers_summary)
            tool_calls = llm_result.get("tool_calls", [])

            execution_reports = []
            for call in tool_calls:
                fn_name = call.get("name")
                args = call.get("arguments", {})

                report_item = {"name": fn_name, "args": args}

                if fn_name == "inspect_active_layers":
                    report_item["result"] = layers_summary
                else:
                    # Las acciones cartográficas de PyQGIS se ejecutan en el hilo principal de la UI
                    report_item["qgis_action"] = {"action": fn_name, "args": args}

                execution_reports.append(report_item)

            self.result = {
                "llm_content": llm_result.get("content", ""),
                "tool_calls": tool_calls,
                "reports": execution_reports
            }
            return True

        except Exception as exc:
            self.error_message = str(exc)
            QgsMessageLog.logMessage(f"Fallo en CartoAgentWorkerTask: {str(exc)}", LOG_TAG, Qgis.Critical)
            return False

    def finished(self, result: bool) -> None:
        if result and self.result:
            self.on_success(self.result)
        else:
            self.on_error(self.error_message or "Error procesando la solicitud.")
