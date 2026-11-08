# -*- coding: utf-8 -*-
"""
Interfaz gráfica fluida e interactiva de CartoAI Copilot (Inspirada en TerraLab Dark/Light UI).

Características principales:
- Modo Oscuro (#111317) y Modo Claro (#F4F6F9) con conmutación en vivo en 1 clic (🌙 / ☀️).
- Avatar con personalidad de Arquitecto Geógrafo ("CartoAI • de David Ortiz").
- Tarjetas de resultado "✓ Listo" con viñetas de cambios reales y botón "↩ Deshacer los cambios".
- Enlaces interactivos dentro del chat (`action://...`) que ejecutan herramientas al instante.
- Compositor inferior unificado con botón circular `+` (menú de herramientas SIG),
  selector de personalidad (`🛡️ Equilibrado ▾`), selector de esfuerzo (`Esfuerzo ▾`) y botón circular verde `↑`.
- Compatible con QGIS 3 (PyQt5) y QGIS 4 (PyQt6).
"""

import os
import re
import html
from typing import Dict, Any, List, Optional

from qgis.PyQt.QtCore import Qt, pyqtSignal, QSize, QUrl
from qgis.PyQt.QtGui import QIcon, QFont, QColor, QDesktopServices, QCursor
from qgis.PyQt.QtWidgets import (
    QDockWidget,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QTextBrowser,
    QPlainTextEdit,
    QPushButton,
    QToolButton,
    QProgressBar,
    QLabel,
    QDialog,
    QComboBox,
    QLineEdit,
    QFormLayout,
    QDialogButtonBox,
    QMessageBox,
    QScrollArea,
    QFrame,
    QMenu
)

from qgis.core import (
    QgsApplication,
    QgsMessageLog,
    Qgis,
    QgsProject,
    QgsMapLayer,
    QgsVectorLayer,
    QgsRasterLayer,
    QgsWkbTypes
)
from qgis.utils import iface

from .ai_engine import (
    AISettingsManager,
    CartoAgentWorkerTask
)
from .pyqgis_executor import PyQGISExecutor

LOG_TAG = "CartoAI"

THEMES: Dict[str, Dict[str, str]] = {
    "dark": {
        "bg_main": "#111317",
        "bg_card": "#1A1D24",
        "bg_card_inner": "#22262F",
        "bg_composer": "#181B22",
        "bg_pill": "#232730",
        "bg_pill_hover": "#2E333E",
        "border": "#2B303B",
        "border_Focus": "#43A047",
        "text_primary": "#F3F4F6",
        "text_secondary": "#9CA3AF",
        "text_muted": "#6B7280",
        "brand_green": "#43A047",
        "brand_green_hover": "#2E7D32",
        "accent_lime": "#8BAC27",
        "user_bubble": "#253042",
        "user_border": "#374761",
        "code_bg": "#0D0F12",
        "code_fg": "#E5E7EB",
        "err_bg": "#2C1618",
        "err_border": "#EF4444",
        "err_fg": "#FCA5A5",
    },
    "light": {
        "bg_main": "#F4F6F9",
        "bg_card": "#FFFFFF",
        "bg_card_inner": "#F8FAFC",
        "bg_composer": "#FFFFFF",
        "bg_pill": "#F1F5F9",
        "bg_pill_hover": "#E2E8F0",
        "border": "#CBD5E1",
        "border_Focus": "#2E7D32",
        "text_primary": "#0F172A",
        "text_secondary": "#475569",
        "text_muted": "#64748B",
        "brand_green": "#43A047",
        "brand_green_hover": "#2E7D32",
        "accent_lime": "#4D7C0F",
        "user_bubble": "#E0F2FE",
        "user_border": "#BAE6FD",
        "code_bg": "#1E293B",
        "code_fg": "#F8FAFC",
        "err_bg": "#FEF2F2",
        "err_border": "#EF4444",
        "err_fg": "#991B1B",
    }
}


def _get_echo_mode(is_password: bool):
    return QLineEdit.EchoMode.Password if is_password else QLineEdit.EchoMode.Normal


def _get_button_flags():
    return QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel


def _get_scrollbar_always_off():
    return Qt.ScrollBarPolicy.ScrollBarAlwaysOff


def _exec_menu(menu: QMenu, pos):
    return menu.exec(pos)


class SettingsDialog(QDialog):
    """Diálogo modal de configuración con soporte multi-proveedor."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Ajustes de IA - CartoAI Copilot")
        self.resize(480, 280)
        self._setup_ui()
        self._load_values()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.combo_provider = QComboBox()
        self.combo_provider.addItems([
            "Google Gemini (6 Modelos Activos en Cadena)",
            "OpenAI (GPT-4o / GPT-4o-mini)",
            "Endpoint Personalizado (DeepSeek / Groq / Ollama)"
        ])
        self.combo_provider.currentIndexChanged.connect(self._on_provider_changed)
        form.addRow("Proveedor de IA:", self.combo_provider)

        self.edit_model = QLineEdit()
        form.addRow("Modelo Principal:", self.edit_model)

        self.edit_api_key = QLineEdit()
        self.edit_api_key.setEchoMode(_get_echo_mode(True))
        self.edit_api_key.setPlaceholderText("Pega aquí tu API Key...")

        h_box_key = QHBoxLayout()
        h_box_key.addWidget(self.edit_api_key)
        self.btn_show_key = QPushButton("👁️")
        self.btn_show_key.setFixedWidth(36)
        self.btn_show_key.setCheckable(True)
        self.btn_show_key.toggled.connect(self._toggle_key_visibility)
        h_box_key.addWidget(self.btn_show_key)
        form.addRow("API Key:", h_box_key)

        self.edit_url = QLineEdit()
        self.edit_url.setPlaceholderText("Ej. https://api.deepseek.com/v1 o http://localhost:11434/v1")
        form.addRow("URL Base (Opcional):", self.edit_url)

        layout.addLayout(form)

        info = QLabel(
            "<small><i>• Conmutación automática activa: <b>gemini-3.5-flash-lite</b> (0.6s) ➔ "
            "<b>gemini-flash-lite-latest</b> ➔ <b>gemini-3.6-flash</b>.</i></small>"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.button_box = QDialogButtonBox(_get_button_flags())
        self.button_box.accepted.connect(self._save_values)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def _toggle_key_visibility(self, checked: bool):
        self.edit_api_key.setEchoMode(_get_echo_mode(not checked))

    def _on_provider_changed(self):
        idx = self.combo_provider.currentIndex()
        if idx == 0:
            self.edit_model.setText("gemini-3.5-flash-lite")
            self.edit_url.setEnabled(False)
        elif idx == 1:
            self.edit_model.setText("gpt-4o-mini")
            self.edit_url.setEnabled(False)
        else:
            self.edit_model.setText("deepseek-chat")
            self.edit_url.setEnabled(True)

    def _load_values(self):
        provider = AISettingsManager.get_provider()
        if provider == "gemini":
            self.combo_provider.setCurrentIndex(0)
        elif provider == "openai":
            self.combo_provider.setCurrentIndex(1)
        else:
            self.combo_provider.setCurrentIndex(2)

        self.edit_model.setText(AISettingsManager.get_model_name())
        self.edit_api_key.setText(AISettingsManager.get_api_key())
        self.edit_url.setText(AISettingsManager.get_custom_url())

    def _save_values(self):
        idx = self.combo_provider.currentIndex()
        provider = "gemini" if idx == 0 else "openai" if idx == 1 else "custom"
        AISettingsManager.set_provider(provider)
        AISettingsManager.set_model_name(self.edit_model.text())
        AISettingsManager.set_api_key(self.edit_api_key.text())
        AISettingsManager.set_custom_url(self.edit_url.text())
        self.accept()


class ChatInputField(QPlainTextEdit):
    """Campo de texto fluido con envío con Enter y salto con Shift+Enter."""

    returnPressed = pyqtSignal()

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if int(event.modifiers()) & int(Qt.KeyboardModifier.ShiftModifier):
                super().keyPressEvent(event)
            else:
                self.returnPressed.emit()
        else:
            super().keyPressEvent(event)


class CartoAgentDockWidget(QDockWidget):
    """Panel interactivo con estética TerraLab Dark/Light, personalidad y herramientas fluidas."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__("CartoAI Copilot", parent)
        self.setObjectName("CartoAICopilotDockWidget")
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)

        self.chat_history: List[Dict[str, str]] = []
        self._rendered_blocks: List[str] = []
        self._active_task: Optional[CartoAgentWorkerTask] = None
        self.current_theme: str = AISettingsManager.get_theme()
        self.tools_drawer_open: bool = True

        self._setup_ui()
        self._apply_theme()
        self._connect_layer_watcher()
        self._update_active_layer_card()
        self._render_welcome_state()

    def _t(self) -> Dict[str, str]:
        return THEMES.get(self.current_theme, THEMES["dark"])

    def _setup_ui(self):
        self.main_container = QWidget()
        layout = QVBoxLayout(self.main_container)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(8)

        # =====================================================================
        # 1. CABECERA SUPERIOR (Avatar + Identidad + Pill Central + Iconos)
        # =====================================================================
        top_bar = QHBoxLayout()
        top_bar.setSpacing(6)

        # Mascota / Avatar circular verde lima
        self.avatar_label = QLabel("◕‿◕")
        self.avatar_label.setFixedSize(28, 28)
        self.avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top_bar.addWidget(self.avatar_label)

        # Título en dos líneas: CartoAI / de David Ortiz
        self.brand_label = QLabel()
        top_bar.addWidget(self.brand_label)

        # Pastilla interactiva central
        self.btn_studio_pill = QPushButton("✨ Estudio SIG Activo")
        self.btn_studio_pill.setToolTip("Mostrar / Ocultar Cajón de Herramientas Interactivas")
        self.btn_studio_pill.clicked.connect(self._toggle_tools_drawer)
        top_bar.addWidget(self.btn_studio_pill)

        top_bar.addStretch()

        # Botón Modo Oscuro / Claro
        self.btn_theme = QPushButton("☀️" if self.current_theme == "dark" else "🌙")
        self.btn_theme.setToolTip("Cambiar entre Modo Oscuro y Modo Claro")
        self.btn_theme.setFixedSize(28, 28)
        self.btn_theme.clicked.connect(self._toggle_theme)
        top_bar.addWidget(self.btn_theme)

        # Botón Deshacer rápido en barra
        self.btn_undo_top = QPushButton("↩")
        self.btn_undo_top.setToolTip("Deshacer el último cambio en el proyecto")
        self.btn_undo_top.setFixedSize(28, 28)
        self.btn_undo_top.clicked.connect(self._handle_undo)
        top_bar.addWidget(self.btn_undo_top)

        # Botón Nueva conversación
        self.btn_clear = QPushButton("📝")
        self.btn_clear.setToolTip("Nueva conversación")
        self.btn_clear.setFixedSize(28, 28)
        self.btn_clear.clicked.connect(self._clear_chat)
        top_bar.addWidget(self.btn_clear)

        # Botón Ajustes
        self.btn_settings = QPushButton("⚙️")
        self.btn_settings.setToolTip("Configurar Proveedor y API Key")
        self.btn_settings.setFixedSize(28, 28)
        self.btn_settings.clicked.connect(self._open_settings)
        top_bar.addWidget(self.btn_settings)

        layout.addLayout(top_bar)

        # =====================================================================
        # 2. PASTILLA DE CAPA ACTIVA EN VIVO (LayerWatch)
        # =====================================================================
        self.layer_watch_card = QLabel()
        self.layer_watch_card.setWordWrap(True)
        layout.addWidget(self.layer_watch_card)

        # =====================================================================
        # 3. CAJÓN DE HERRAMIENTAS INTERACTIVAS FLUIDAS (2 Filas de Botones)
        # =====================================================================
        self.tools_frame = QFrame()
        tools_grid = QGridLayout(self.tools_frame)
        tools_grid.setContentsMargins(6, 6, 6, 6)
        tools_grid.setSpacing(5)

        self.tool_buttons: List[QPushButton] = []
        tool_defs = [
            ("🗺️ Layout A4", "action://layout_a4", "Crear composición de impresión A4 profesional con leyenda, norte y escala"),
            ("🎨 Auto-Estilo", "action://auto_style", "Aplicar simbología moderna y armonizada a la capa activa"),
            ("🌈 Categorizar", "action://categorize", "Clasificar por colores según atributos de la capa activa"),
            ("🏷️ Etiquetar", "action://labels", "Activar etiquetas con halo de lectura sobre la capa activa"),
            ("⭕ Buffer 100m", "action://buffer_100", "Generar área de influencia de 100 metros sobre la capa activa"),
            ("🌍 Mapa Base ▾", "menu://basemaps", "Cargar mapa base mundial (OSM, Satélite, Dark, Positron, Topo)"),
            ("🔍 Zoom Capa", "action://zoom_active", "Centrar el lienzo en la extensión de la capa activa"),
            ("📊 Diagnóstico", "action://analyze", "Inspeccionar estructura, CRS y resumen estadístico de la capa"),
        ]

        for idx, (label, action_uri, tip) in enumerate(tool_defs):
            btn = QPushButton(label)
            btn.setToolTip(tip)
            if action_uri == "menu://basemaps":
                btn.clicked.connect(self._show_basemap_menu)
            else:
                btn.clicked.connect(lambda _, uri=action_uri: self._execute_interactive_uri(uri))
            self.tool_buttons.append(btn)
            tools_grid.addWidget(btn, idx // 4, idx % 4)

        layout.addWidget(self.tools_frame)

        # =====================================================================
        # 4. LIENZO DE CONVERSACIÓN E HISTORIAL DE TARJETAS INTERACTIVAS
        # =====================================================================
        self.chat_browser = QTextBrowser()
        self.chat_browser.setOpenLinks(False)
        self.chat_browser.anchorClicked.connect(self._on_chat_anchor_clicked)
        layout.addWidget(self.chat_browser, stretch=1)

        # =====================================================================
        # 5. BARRA DE PROGRESO ANIMADA
        # =====================================================================
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(3)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # =====================================================================
        # 6. COMPOSITOR INFERIOR ESTILO TERRALAB (Caja Única con Barra de Controles)
        # =====================================================================
        self.composer_frame = QFrame()
        composer_layout = QVBoxLayout(self.composer_frame)
        composer_layout.setContentsMargins(10, 8, 10, 8)
        composer_layout.setSpacing(6)

        self.input_edit = ChatInputField()
        self.input_edit.setPlaceholderText("Dale una tarea al agente de IA en QGIS...")
        self.input_edit.setFixedHeight(44)
        self.input_edit.returnPressed.connect(self._handle_send_message)
        composer_layout.addWidget(self.input_edit)

        # Fila inferior dentro del compositor: [+] [🛡️ Equilibrado ▾] ... [Esfuerzo ▾] [↑]
        bottom_controls = QHBoxLayout()
        bottom_controls.setContentsMargins(0, 0, 0, 0)
        bottom_controls.setSpacing(8)

        # Botón circular [+] de herramientas y adjuntos
        self.btn_plus = QPushButton("＋")
        self.btn_plus.setFixedSize(28, 28)
        self.btn_plus.setToolTip("Menú rápido de acciones cartográficas y mapas base")
        self.btn_plus.clicked.connect(self._show_plus_menu)
        bottom_controls.addWidget(self.btn_plus)

        # Selector de Personalidad / Modo
        self.btn_mode = QPushButton()
        self.btn_mode.setToolTip("Cambiar personalidad y modo de ejecución del bot")
        self.btn_mode.clicked.connect(self._show_mode_menu)
        bottom_controls.addWidget(self.btn_mode)
        self._update_mode_button_label()

        bottom_controls.addStretch()

        # Selector de Esfuerzo (Low / Medium / High)
        self.btn_effort = QPushButton()
        self.btn_effort.setToolTip("Ajustar nivel de profundidad analítica del agente")
        self.btn_effort.clicked.connect(self._show_effort_menu)
        bottom_controls.addWidget(self.btn_effort)
        self._update_effort_button_label()

        # Botón circular verde [↑]
        self.btn_send = QPushButton("↑")
        self.btn_send.setFixedSize(32, 32)
        self.btn_send.setToolTip("Enviar tarea (Enter)")
        self.btn_send.clicked.connect(self._handle_send_message)
        bottom_controls.addWidget(self.btn_send)

        composer_layout.addLayout(bottom_controls)
        layout.addWidget(self.composer_frame)

        self.setWidget(self.main_container)

    # =========================================================================
    # MOTOR DE TEMAS (MODO OSCURO / MODO CLARO)
    # =========================================================================
    def _toggle_theme(self):
        self.current_theme = "light" if self.current_theme == "dark" else "dark"
        AISettingsManager.set_theme(self.current_theme)
        self.btn_theme.setText("☀️" if self.current_theme == "dark" else "🌙")
        self._apply_theme()
        self._update_active_layer_card()
        self._refresh_chat_html()

    def _apply_theme(self):
        t = self._t()

        self.main_container.setStyleSheet(f"""
            QWidget {{
                background-color: {t['bg_main']};
                color: {t['text_primary']};
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            }}
        """)

        self.avatar_label.setStyleSheet(f"""
            QLabel {{
                background-color: {t['accent_lime']};
                color: #111317;
                font-weight: bold;
                font-size: 11px;
                border-radius: 14px;
            }}
        """)

        self.brand_label.setText(
            f"<div style='line-height:1.1;'>"
            f"<b style='color:{t['text_primary']}; font-size:13px;'>CartoAI</b><br>"
            f"<span style='color:{t['text_secondary']}; font-size:10px;'>de David Ortiz</span>"
            f"</div>"
        )

        self.btn_studio_pill.setStyleSheet(f"""
            QPushButton {{
                background-color: {t['bg_card']};
                color: {t['text_primary']};
                border: 1px solid {t['border']};
                border-radius: 13px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: {t['bg_pill_hover']};
                border-color: {t['brand_green']};
            }}
        """)

        ghost_btn_qss = f"""
            QPushButton {{
                background-color: transparent;
                color: {t['text_secondary']};
                border: none;
                border-radius: 6px;
                font-size: 14px;
            }}
            QPushButton:hover {{
                background-color: {t['bg_pill_hover']};
                color: {t['text_primary']};
            }}
        """
        for b in (self.btn_theme, self.btn_undo_top, self.btn_clear, self.btn_settings):
            b.setStyleSheet(ghost_btn_qss)

        self.layer_watch_card.setStyleSheet(f"""
            QLabel {{
                background-color: {t['bg_card']};
                border: 1px solid {t['border']};
                border-radius: 10px;
                padding: 6px 10px;
                font-size: 11px;
                color: {t['text_secondary']};
            }}
        """)

        self.tools_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {t['bg_card']};
                border: 1px solid {t['border']};
                border-radius: 12px;
            }}
        """)

        tool_btn_qss = f"""
            QPushButton {{
                background-color: {t['bg_pill']};
                color: {t['text_primary']};
                border: 1px solid {t['border']};
                border-radius: 8px;
                padding: 5px 6px;
                font-size: 11px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: {t['bg_pill_hover']};
                border-color: {t['brand_green']};
            }}
            QPushButton:pressed {{
                background-color: {t['brand_green']};
                color: white;
            }}
        """
        for tb in self.tool_buttons:
            tb.setStyleSheet(tool_btn_qss)

        self.chat_browser.setStyleSheet(f"""
            QTextBrowser {{
                background-color: {t['bg_main']};
                border: none;
                padding: 2px;
                font-size: 12px;
                color: {t['text_primary']};
            }}
        """)

        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: transparent;
                border: none;
            }}
            QProgressBar::chunk {{
                background-color: {t['brand_green']};
            }}
        """)

        self.composer_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {t['bg_composer']};
                border: 1px solid {t['border']};
                border-radius: 14px;
            }}
        """)

        self.input_edit.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: transparent;
                border: none;
                font-size: 12px;
                color: {t['text_primary']};
            }}
        """)

        self.btn_plus.setStyleSheet(f"""
            QPushButton {{
                background-color: {t['bg_pill']};
                color: {t['text_secondary']};
                border: 1px solid {t['border']};
                border-radius: 14px;
                font-size: 15px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {t['bg_pill_hover']};
                color: {t['text_primary']};
            }}
        """)

        sub_chip_qss = f"""
            QPushButton {{
                background-color: transparent;
                color: {t['text_secondary']};
                border: none;
                border-radius: 8px;
                padding: 4px 8px;
                font-size: 11px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: {t['bg_pill_hover']};
                color: {t['text_primary']};
            }}
        """
        self.btn_mode.setStyleSheet(sub_chip_qss)
        self.btn_effort.setStyleSheet(sub_chip_qss)

        self.btn_send.setStyleSheet(f"""
            QPushButton {{
                background-color: {t['brand_green']};
                color: white;
                border: none;
                border-radius: 16px;
                font-size: 15px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {t['brand_green_hover']};
            }}
            QPushButton:disabled {{
                background-color: {t['bg_pill']};
                color: {t['text_muted']};
            }}
        """)

    # =========================================================================
    # MENÚS INTERACTIVOS DE LA BARRA INFERIOR Y HERRAMIENTAS
    # =========================================================================
    def _toggle_tools_drawer(self):
        self.tools_drawer_open = not self.tools_drawer_open
        self.tools_frame.setVisible(self.tools_drawer_open)

    def _update_mode_button_label(self):
        mode = AISettingsManager.get_agent_mode()
        labels = {
            "equilibrado": "🛡️ Equilibrado ▾",
            "autopilot": "⚡ Piloto Automático ▾",
            "geografo": "🧭 Arquitecto Geógrafo ▾"
        }
        self.btn_mode.setText(labels.get(mode, "🛡️ Equilibrado ▾"))

    def _update_effort_button_label(self):
        effort = AISettingsManager.get_effort_level()
        self.btn_effort.setText(f"Esfuerzo {effort} ▾")

    def _show_mode_menu(self):
        menu = QMenu(self)
        modes = [
            ("🛡️ Equilibrado (Colega Geógrafo)", "equilibrado"),
            ("⚡ Piloto Automático (Ejecución Directa)", "autopilot"),
            ("🧭 Arquitecto Geógrafo & Académico", "geografo"),
        ]
        for label, val in modes:
            act = menu.addAction(label)
            act.triggered.connect(lambda _, v=val: self._set_agent_mode(v))
        _exec_menu(menu, QCursor.pos())

    def _set_agent_mode(self, mode: str):
        AISettingsManager.set_agent_mode(mode)
        self._update_mode_button_label()

    def _show_effort_menu(self):
        menu = QMenu(self)
        for level, desc in [
            ("Low", "Low • Respuesta instantánea (0.6s)"),
            ("Medium", "Medium • Balance óptimo"),
            ("High", "High • Análisis espacial profundo"),
        ]:
            act = menu.addAction(desc)
            act.triggered.connect(lambda _, lv=level: self._set_effort_level(lv))
        _exec_menu(menu, QCursor.pos())

    def _set_effort_level(self, level: str):
        AISettingsManager.set_effort_level(level)
        self._update_effort_button_label()

    def _show_basemap_menu(self):
        menu = QMenu(self)
        basemaps = [
            ("🌍 OpenStreetMap Standard", "action://basemap_osm"),
            ("🛰️ Esri World Imagery (Satélite)", "action://basemap_satellite"),
            ("🌑 CartoDB Dark Matter (Oscuro)", "action://basemap_dark"),
            ("⚪ CartoDB Positron (Minimalista Claro)", "action://basemap_positron"),
            ("⛰️ OpenTopoMap (Relieve y Topografía)", "action://basemap_topo"),
        ]
        for label, uri in basemaps:
            act = menu.addAction(label)
            act.triggered.connect(lambda _, u=uri: self._execute_interactive_uri(u))
        _exec_menu(menu, QCursor.pos())

    def _show_plus_menu(self):
        menu = QMenu(self)

        sub_base = menu.addMenu("🌍 Cargar Mapa Base Mundial")
        for label, uri in [
            ("OpenStreetMap Standard", "action://basemap_osm"),
            ("Satélite Esri World Imagery", "action://basemap_satellite"),
            ("CartoDB Dark Matter (Oscuro)", "action://basemap_dark"),
            ("CartoDB Positron (Claro)", "action://basemap_positron"),
            ("OpenTopoMap (Topográfico)", "action://basemap_topo"),
        ]:
            a = sub_base.addAction(label)
            a.triggered.connect(lambda _, u=uri: self._execute_interactive_uri(u))

        sub_layout = menu.addMenu("🗺️ Diseñar Composición de Impresión")
        for label, uri in [
            ("Diseño A4 Horizontal Profesional", "action://layout_a4"),
            ("Diseño A4 Vertical (Portrait)", "action://layout_portrait"),
            ("Diseño A3 Gran Formato", "action://layout_a3"),
        ]:
            a = sub_layout.addAction(label)
            a.triggered.connect(lambda _, u=uri: self._execute_interactive_uri(u))

        sub_style = menu.addMenu("🎨 Simbología y Etiquetado")
        for label, uri in [
            ("Auto-Estilo Azul Cartográfico", "action://auto_style"),
            ("Estilo Verde Ambiental / Forestal", "action://style_green"),
            ("Estilo Rojo Alerta / Infraestructura", "action://style_red"),
            ("Categorizar por Atributo Único", "action://categorize"),
            ("Activar Etiquetas con Halo", "action://labels"),
        ]:
            a = sub_style.addAction(label)
            a.triggered.connect(lambda _, u=uri: self._execute_interactive_uri(u))

        sub_geo = menu.addMenu("⭕ Geoprocesamiento Rápido")
        for label, uri in [
            ("Buffer de 100m", "action://buffer_100"),
            ("Buffer de 500m", "action://buffer_500"),
            ("Calcular Centroides", "action://centroids"),
            ("Disolver Geometrías", "action://dissolve"),
        ]:
            a = sub_geo.addAction(label)
            a.triggered.connect(lambda _, u=uri: self._execute_interactive_uri(u))

        menu.addSeparator()
        act_undo = menu.addAction("↩ Deshacer el último cambio")
        act_undo.triggered.connect(self._handle_undo)

        _exec_menu(menu, QCursor.pos())

    # =========================================================================
    # OBSERVADOR DE CAPA ACTIVA (LayerWatch)
    # =========================================================================
    def _connect_layer_watcher(self):
        if iface:
            try:
                iface.currentLayerChanged.connect(self._update_active_layer_card)
            except Exception:  # nosec B110
                pass
        QgsProject.instance().layersAdded.connect(self._update_active_layer_card)
        QgsProject.instance().layersRemoved.connect(self._update_active_layer_card)

    def _update_active_layer_card(self, *args):
        t = self._t()
        layer = iface.activeLayer() if iface else None
        if layer and layer.isValid():
            name = html.escape(layer.name())
            if isinstance(layer, QgsVectorLayer):
                geom_type = QgsWkbTypes.displayString(layer.wkbType())
                count = layer.featureCount()
                crs_auth = layer.crs().authid() if layer.crs().isValid() else "Sin CRS"
                icon = "📐" if "Polygon" in geom_type else "〰️" if "Line" in geom_type else "📍"
                txt = (
                    f"{icon} <b style='color:{t['text_primary']};'>{name}</b> "
                    f"<span style='color:{t['text_secondary']};'>• {geom_type} • {count:,} ent. • {crs_auth}</span>"
                )
            elif isinstance(layer, QgsRasterLayer):
                crs_auth = layer.crs().authid() if layer.crs().isValid() else "Sin CRS"
                txt = f"🖼️ <b style='color:{t['text_primary']};'>{name}</b> <span style='color:{t['text_secondary']};'>• Ráster • {crs_auth}</span>"
            else:
                txt = f"📄 <b style='color:{t['text_primary']};'>{name}</b>"
        else:
            total_layers = len(QgsProject.instance().mapLayers())
            txt = f"🧭 <b style='color:{t['text_primary']};'>Proyecto activo:</b> <span style='color:{t['text_secondary']};'>{total_layers} capas cargadas</span>"

        self.layer_watch_card.setText(txt)

    # =========================================================================
    # RENDERIZADO DE TARJETAS Y PERSONALIDAD ESTILO TERRALAB
    # =========================================================================
    def _render_welcome_state(self):
        self._rendered_blocks.clear()
        self._refresh_chat_html()

    def _build_welcome_card_html(self) -> str:
        t = self._t()
        return f"""
        <div style="background-color: {t['bg_card']}; border: 1px solid {t['border']}; border-radius: 12px; padding: 14px; margin: 4px 0 10px 0;">
            <div style="font-size: 13px; font-weight: bold; color: {t['text_primary']}; margin-bottom: 4px;">
                👋 ¡Hola! Soy CartoAI, tu Arquitecto SIG
            </div>
            <div style="font-size: 11px; color: {t['text_secondary']}; margin-bottom: 10px; line-height: 1.4;">
                Diseñado por <b>David Ortiz</b> (Geografía). Ejecuto análisis espacial, aplico simbología temática y construyo diseños de impresión profesionales directamente en tu proyecto.
            </div>

            <div style="background-color: {t['brand_green']}; color: white; text-align: center; padding: 8px; border-radius: 8px; font-weight: bold; font-size: 12px; margin-bottom: 10px;">
                <a href="action://layout_a4" style="color: white; text-decoration: none;">✨ Crear Composición Cartográfica A4 en 1 Clic</a>
            </div>

            <div style="font-size: 11px; color: {t['text_primary']}; font-weight: bold; margin-bottom: 6px;">
                Capacidades interactivas incluidas:
            </div>
            <div style="font-size: 11px; color: {t['text_secondary']}; line-height: 1.7;">
                <span style="color: {t['brand_green']}; font-weight: bold;">✓</span> Diseño automático de mapas A4/A3 con leyenda, escala y norte<br>
                <span style="color: {t['brand_green']}; font-weight: bold;">✓</span> Mapas base mundiales (<a href="action://basemap_satellite" style="color:{t['accent_lime']}; text-decoration:none;">Satélite</a>, <a href="action://basemap_dark" style="color:{t['accent_lime']}; text-decoration:none;">Dark</a>, <a href="action://basemap_osm" style="color:{t['accent_lime']}; text-decoration:none;">OSM</a>, <a href="action://basemap_topo" style="color:{t['accent_lime']}; text-decoration:none;">Topo</a>)<br>
                <span style="color: {t['brand_green']}; font-weight: bold;">✓</span> Piloto automático PyQGIS con botón de <b>Deshacer en 1 clic</b><br>
                <span style="color: {t['brand_green']}; font-weight: bold;">✓</span> Conmutación inteligente entre 6 motores de IA sin caídas
            </div>
        </div>
        """

    def _refresh_chat_html(self):
        welcome = self._build_welcome_card_html()
        full_html = welcome + "\n".join(self._rendered_blocks)
        self.chat_browser.setHtml(full_html)
        scrollbar = self.chat_browser.verticalScrollBar()
        if scrollbar:
            scrollbar.setValue(scrollbar.maximum())

    def _append_user_message(self, text: str):
        t = self._t()
        block = f"""
        <div style="margin: 10px 0 6px 0; text-align: right;">
            <div style="display: inline-block; background-color: {t['user_bubble']}; color: {t['text_primary']}; border: 1px solid {t['user_border']}; padding: 8px 12px; border-radius: 14px 14px 3px 14px; max-width: 88%; font-size: 12px; text-align: left;">
                {html.escape(text)}
            </div>
        </div>
        """
        self._rendered_blocks.append(block)
        self._refresh_chat_html()

    def _append_assistant_card(self, text: str, execution_results: List[Dict[str, Any]]):
        t = self._t()
        clean_text = re_sub_code(text)
        formatted_text = html.escape(clean_text).replace("\n", "<br>")

        status_cards_html = ""
        if execution_results:
            for item in execution_results:
                report = item.get("report", {})
                code = item.get("code", "")
                success = report.get("success", False)
                stdout = report.get("stdout", "")
                error = report.get("error", "")
                bullets = report.get("summary_bullets", [])

                if success:
                    bullets_html = "".join([
                        f"<div style='color:{t['text_secondary']}; font-size:11px; margin-top:3px;'>• {html.escape(b)}</div>"
                        for b in bullets
                    ])
                    stdout_html = (
                        f"<div style='margin-top:6px; padding:5px 8px; background:{t['bg_card_inner']}; border-radius:6px; font-family:Consolas, monospace; font-size:10px; color:{t['text_secondary']};'>{html.escape(stdout)}</div>"
                        if stdout else ""
                    )
                    code_escaped = html.escape(code.strip())

                    # Tarjeta idéntica a la captura de TerraLab: barra superior "↩ Deshacer los cambios  👍 👎" + caja "✓ Listo"
                    status_cards_html += f"""
                    <div style="margin: 8px 0 4px 0; text-align: right; font-size: 11px;">
                        <a href="action://undo" style="color: {t['text_secondary']}; text-decoration: none; font-weight: 500;">↩ Deshacer los cambios</a>
                        &nbsp;&nbsp;&nbsp;
                        <a href="action://rate_up" style="color: {t['text_secondary']}; text-decoration: none;">👍</a>
                        &nbsp;
                        <a href="action://rate_down" style="color: {t['text_secondary']}; text-decoration: none;">👎</a>
                    </div>
                    <div style="background-color: {t['bg_card']}; border: 1px solid {t['border']}; border-radius: 12px; padding: 10px 12px; margin-bottom: 6px;">
                        <div style="font-weight: bold; font-size: 12px; color: {t['text_primary']}; margin-bottom: 4px;">
                            <span style="color: {t['brand_green']};">✓</span> Listo
                        </div>
                        {bullets_html}
                        {stdout_html}
                        <div style="margin-top: 6px;">
                            <details>
                                <summary style="cursor: pointer; color: {t['text_muted']}; font-size: 10px;">
                                    Ver script PyQGIS ejecutado
                                </summary>
                                <pre style="margin-top: 5px; background: {t['code_bg']}; color: {t['code_fg']}; padding: 8px; border-radius: 6px; font-family: Consolas, monospace; font-size: 10px; white-space: pre-wrap;">{code_escaped}</pre>
                            </details>
                        </div>
                    </div>
                    """
                else:
                    status_cards_html += f"""
                    <div style="background-color: {t['err_bg']}; border: 1px solid {t['err_border']}; border-radius: 10px; padding: 10px; margin: 6px 0; color: {t['err_fg']}; font-size: 11px;">
                        <b>✗ Detalle de ejecución:</b><br>
                        <span style="font-family: Consolas, monospace; font-size: 10px;">{html.escape(error)}</span>
                    </div>
                    """

        # Botones interactivos de sugerencia de siguiente paso
        followup_bar = f"""
        <div style="margin-top: 6px; font-size: 10px;">
            <a href="action://layout_a4" style="background:{t['bg_pill']}; color:{t['text_primary']}; border:1px solid {t['border']}; border-radius:10px; padding:3px 8px; text-decoration:none; margin-right:4px;">🗺️ Abrir Layout A4</a>
            <a href="action://auto_style" style="background:{t['bg_pill']}; color:{t['text_primary']}; border:1px solid {t['border']}; border-radius:10px; padding:3px 8px; text-decoration:none; margin-right:4px;">🎨 Estilizar</a>
            <a href="action://labels" style="background:{t['bg_pill']}; color:{t['text_primary']}; border:1px solid {t['border']}; border-radius:10px; padding:3px 8px; text-decoration:none; margin-right:4px;">🏷️ Etiquetar</a>
            <a href="action://zoom_active" style="background:{t['bg_pill']}; color:{t['text_primary']}; border:1px solid {t['border']}; border-radius:10px; padding:3px 8px; text-decoration:none;">🔍 Zoom</a>
        </div>
        """

        explanation_div = (
            f"<div style='color:{t['text_primary']}; font-size:12px; line-height:1.5; margin-bottom:6px;'>{formatted_text}</div>"
            if formatted_text else ""
        )

        block = f"""
        <div style="margin: 8px 0 12px 0;">
            {explanation_div}
            {status_cards_html}
            {followup_bar}
        </div>
        """
        self._rendered_blocks.append(block)
        self._refresh_chat_html()

    # =========================================================================
    # EJECUCIÓN DIRECTA DE ACCIONES INTERACTIVAS EN 1 CLIC
    # =========================================================================
    def _on_chat_anchor_clicked(self, url: QUrl):
        uri = url.toString()
        if uri.startswith("action://"):
            self._execute_interactive_uri(uri)
        elif uri.startswith("http://") or uri.startswith("https://"):
            QDesktopServices.openUrl(url)

    def _execute_interactive_uri(self, uri: str):
        action = uri.replace("action://", "").strip()

        if action == "undo":
            self._handle_undo()
            return
        if action in ("rate_up", "rate_down"):
            msg = "¡Gracias por tu valoración positiva! Seguimos mejorando la cartografía." if action == "rate_up" else "Gracias por tu retroalimentación. Puedes pulsar '↩ Deshacer los cambios' si deseas revertir."
            self._append_system_note(msg)
            return

        # Mapa de scripts directos para ejecución instantánea (< 50 ms) sin esperar a la nube
        instant_scripts = {
            "layout_a4": (
                "Diseñar composición cartográfica A4 horizontal",
                "He preparado tu diseño de impresión A4 horizontal con mapa centrado, título, leyenda, barra de escala y flecha de norte.",
                "create_professional_layout(layout_name='Mapa Oficial CartoAI', map_title='MAPA TEMÁTICO OFICIAL', orientation='landscape', page_format='A4')"
            ),
            "layout_portrait": (
                "Diseñar composición cartográfica A4 vertical",
                "He generado un diseño de impresión A4 vertical listo para publicación.",
                "create_professional_layout(layout_name='Mapa Vertical A4', map_title='MAPA TEMÁTICO VERTICAL', orientation='portrait', page_format='A4')"
            ),
            "layout_a3": (
                "Diseñar póster cartográfico A3",
                "He construido una plancha cartográfica en gran formato A3 horizontal.",
                "create_professional_layout(layout_name='Plancha Cartografica A3', map_title='MAPA GENERAL ESCALA A3', orientation='landscape', page_format='A3')"
            ),
            "auto_style": (
                "Aplicar Auto-Estilo Cartográfico",
                "He aplicado una simbología azul zafiro de alto contraste sobre la capa activa.",
                "apply_vector_style(color='#2563EB', outline_color='#1E3A8A', opacity=0.85)"
            ),
            "style_green": (
                "Aplicar Estilo Ambiental / Forestal",
                "He estilizado la capa activa con paleta verde esmeralda ambiental.",
                "apply_vector_style(color='#10B981', outline_color='#065F46', opacity=0.85)"
            ),
            "style_red": (
                "Aplicar Estilo Infraestructura / Alerta",
                "He aplicado simbología carmesí de resalte sobre la capa activa.",
                "apply_vector_style(color='#EF4444', outline_color='#991B1B', opacity=0.85)"
            ),
            "categorize": (
                "Clasificar capa por categorías",
                "He generado una clasificación temática por colores sobre los atributos de tu capa activa.",
                "apply_categorized_style(color_ramp_name='Spectral')"
            ),
            "labels": (
                "Activar etiquetado con halo",
                "He activado las etiquetas tipográficas con halo blanco de protección visual.",
                "enable_labels(font_size=9, halo_color='#FFFFFF', halo_size=1.2)"
            ),
            "zoom_active": (
                "Hacer zoom a la capa activa",
                "He encuadrado el lienzo en la extensión total de tu capa activa.",
                "zoom_to_layer()"
            ),
            "basemap_osm": (
                "Cargar OpenStreetMap Standard",
                "He añadido la capa base mundial de OpenStreetMap.",
                "add_osm_basemap(basemap_type='osm')"
            ),
            "basemap_satellite": (
                "Cargar Satélite Esri World Imagery",
                "He cargado el mosaico satelital de alta resolución Esri World Imagery.",
                "add_osm_basemap(basemap_type='satellite')"
            ),
            "basemap_dark": (
                "Cargar CartoDB Dark Matter",
                "He añadido el mapa base oscuro CartoDB Dark Matter para resaltar tus capas.",
                "add_osm_basemap(basemap_type='dark')"
            ),
            "basemap_positron": (
                "Cargar CartoDB Positron",
                "He añadido el mapa base minimalista CartoDB Positron.",
                "add_osm_basemap(basemap_type='positron')"
            ),
            "basemap_topo": (
                "Cargar OpenTopoMap Relieve",
                "He añadido el mapa topográfico con curvas de nivel OpenTopoMap.",
                "add_osm_basemap(basemap_type='topo')"
            ),
            "buffer_100": (
                "Crear Buffer de 100m",
                "He calculado un área de influencia (Buffer de 100m) sobre la capa activa.",
                """layer = iface.activeLayer() or list(project.mapLayers().values())[0]
res = processing.run('native:buffer', {'INPUT': layer, 'DISTANCE': 100, 'SEGMENTS': 12, 'OUTPUT': 'memory:'})
out = res['OUTPUT']
out.setName(f'Buffer 100m - {layer.name()}')
project.addMapLayer(out)
apply_vector_style(out, color='#F59E0B', outline_color='#B45309', opacity=0.65)"""
            ),
            "buffer_500": (
                "Crear Buffer de 500m",
                "He calculado un área de influencia de 500m con simbología translúcida.",
                """layer = iface.activeLayer() or list(project.mapLayers().values())[0]
res = processing.run('native:buffer', {'INPUT': layer, 'DISTANCE': 500, 'SEGMENTS': 12, 'OUTPUT': 'memory:'})
out = res['OUTPUT']
out.setName(f'Buffer 500m - {layer.name()}')
project.addMapLayer(out)
apply_vector_style(out, color='#8B5CF6', outline_color='#5B21B6', opacity=0.65)"""
            ),
            "centroids": (
                "Calcular Centroides",
                "He generado la capa puntual de centroides geométricos.",
                """layer = iface.activeLayer() or list(project.mapLayers().values())[0]
res = processing.run('native:centroids', {'INPUT': layer, 'ALL_PARTS': False, 'OUTPUT': 'memory:'})
out = res['OUTPUT']
out.setName(f'Centroides - {layer.name()}')
project.addMapLayer(out)
apply_vector_style(out, color='#EC4899', outline_color='#831843', size_or_width=3.5)"""
            ),
            "dissolve": (
                "Disolver geometrías",
                "He unificado las geometrías de la capa activa mediante Dissolve.",
                """layer = iface.activeLayer() or list(project.mapLayers().values())[0]
res = processing.run('native:dissolve', {'INPUT': layer, 'OUTPUT': 'memory:'})
out = res['OUTPUT']
out.setName(f'Disuelto - {layer.name()}')
project.addMapLayer(out)"""
            ),
            "analyze": (
                "Diagnosticar capa activa",
                "Aquí tienes el diagnóstico técnico de tu capa activa:",
                """layer = iface.activeLayer() or (list(project.mapLayers().values())[0] if project.mapLayers() else None)
if layer and hasattr(layer, 'fields'):
    fields = [f"{f.name()} ({f.typeName()})" for f in layer.fields()]
    ext = layer.extent()
    print(f"Capa: {layer.name()} | Entidades: {layer.featureCount():,} | CRS: {layer.crs().authid()}")
    print(f"BBox: [{ext.xMinimum():.3f}, {ext.yMinimum():.3f}, {ext.xMaximum():.3f}, {ext.yMaximum():.3f}]")
    print(f"Atributos ({len(fields)}): " + ", ".join(fields[:12]))
elif layer:
    print(f"Capa Ráster: {layer.name()} | CRS: {layer.crs().authid()}")
else:
    print("No hay capas cargadas en el proyecto.")"""
            ),
        }

        if action in instant_scripts:
            user_title, explanation, code = instant_scripts[action]
            self._append_user_message(user_title)
            report = PyQGISExecutor.execute(code)
            self._append_assistant_card(explanation, [{"code": code, "report": report}])
            self._update_active_layer_card()

    def _handle_undo(self):
        res = PyQGISExecutor.undo_last_action()
        self._append_system_note(f"↩ {res.get('message', 'Acción revertida.')}")
        self._update_active_layer_card()

    def _append_system_note(self, note: str):
        t = self._t()
        block = f"""
        <div style="background-color: {t['bg_card']}; border-left: 3px solid {t['accent_lime']}; border-radius: 6px; padding: 6px 10px; margin: 6px 0; font-size: 11px; color: {t['text_secondary']};">
            {html.escape(note)}
        </div>
        """
        self._rendered_blocks.append(block)
        self._refresh_chat_html()

    # =========================================================================
    # FLUJO DE CONVERSACIÓN CON EL AGENTE LLM
    # =========================================================================
    def _open_settings(self):
        dlg = SettingsDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._update_active_layer_card()

    def _clear_chat(self):
        self.chat_history.clear()
        self._render_welcome_state()

    def _set_ui_busy(self, busy: bool):
        self.progress_bar.setVisible(busy)
        self.btn_send.setEnabled(not busy)
        self.input_edit.setEnabled(not busy)

    def _handle_send_message(self):
        text = self.input_edit.toPlainText().strip()
        if not text:
            return

        self._append_user_message(text)
        self.input_edit.clear()
        self._set_ui_busy(True)

        self._active_task = CartoAgentWorkerTask(
            description=f"CartoAI: {text[:25]}...",
            user_message=text,
            history=list(self.chat_history),
            on_success_callback=self._on_task_success,
            on_error_callback=self._on_task_error
        )
        QgsApplication.taskManager().addTask(self._active_task)

    def _on_task_success(self, result: Dict[str, Any]):
        self._set_ui_busy(False)
        llm_text = result.get("llm_text", "")
        execution_results = result.get("execution_results", [])

        self._append_assistant_card(llm_text, execution_results)
        self._update_active_layer_card()

        user_content = self._active_task.user_message if self._active_task else ""
        self.chat_history.append({"role": "user", "content": user_content})
        self.chat_history.append({"role": "assistant", "content": llm_text})
        self._active_task = None

    def _on_task_error(self, error_message: str):
        self._set_ui_busy(False)
        t = self._t()
        err_html = f"""
        <div style="margin: 8px 0; background: {t['err_bg']}; border: 1px solid {t['err_border']}; padding: 10px; border-radius: 10px; color: {t['err_fg']}; font-size: 11px;">
            <b>Aviso del sistema:</b> {html.escape(error_message)}
        </div>
        """
        self._rendered_blocks.append(err_html)
        self._refresh_chat_html()
        self._active_task = None


def re_sub_code(text: str) -> str:
    """Elimina los bloques ```python ... ``` del texto explicativo."""
    return re.sub(r"```(?:python|py)?\s*.*?\s*```", "", text, flags=re.DOTALL).strip()
