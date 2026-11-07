# -*- coding: utf-8 -*-
"""
Interfaz gráfica interactiva para CartoAI Copilot: Map & GIS Architect.

Incluye chat inteligente con renderizado HTML, barra de atajos rápidos interactivos
(Crear Layout, Auto-Estilo, Geoprocesos, Análisis), indicador de progreso
y diálogo de configuración de modelos LLM.
Compatible con QGIS 3 (PyQt5) y QGIS 4 (PyQt6).
"""

import os
from typing import Dict, Any, List, Optional

try:
    from qgis.PyQt.QtCore import Qt, pyqtSignal, QSize
    from qgis.PyQt.QtGui import QIcon, QFont, QKeySequence
    from qgis.PyQt.QtWidgets import (
        QDockWidget,
        QWidget,
        QVBoxLayout,
        QHBoxLayout,
        QTextBrowser,
        QPlainTextEdit,
        QPushButton,
        QProgressBar,
        QLabel,
        QDialog,
        QComboBox,
        QLineEdit,
        QFormLayout,
        QDialogButtonBox,
        QMessageBox,
        QScrollArea
    )
except ImportError:
    from PyQt5.QtCore import Qt, pyqtSignal, QSize
    from PyQt5.QtGui import QIcon, QFont, QKeySequence
    from PyQt5.QtWidgets import (
        QDockWidget,
        QWidget,
        QVBoxLayout,
        QHBoxLayout,
        QTextBrowser,
        QPlainTextEdit,
        QPushButton,
        QProgressBar,
        QLabel,
        QDialog,
        QComboBox,
        QLineEdit,
        QFormLayout,
        QDialogButtonBox,
        QMessageBox,
        QScrollArea
    )

from qgis.core import (
    QgsApplication,
    QgsMessageLog,
    Qgis
)

from .ai_engine import (
    AISettingsManager,
    CartoAgentWorkerTask
)
from .qgis_tools import (
    apply_vector_style,
    apply_categorized_style,
    enable_labels,
    run_geoprocessing,
    create_professional_layout,
    zoom_to_layer,
    apply_filter
)

LOG_TAG = "CartoAICopilot"


def _get_echo_mode(is_password: bool):
    if hasattr(QLineEdit, "EchoMode"):
        return QLineEdit.EchoMode.Password if is_password else QLineEdit.EchoMode.Normal
    return QLineEdit.Password if is_password else QLineEdit.Normal


def _get_button_flags():
    if hasattr(QDialogButtonBox, "StandardButton"):
        return QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
    return QDialogButtonBox.Save | QDialogButtonBox.Cancel


def _get_scrollbar_always_off():
    if hasattr(Qt, "ScrollBarPolicy"):
        return Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    return getattr(Qt, "ScrollBarAlwaysOff", None)


class SettingsDialog(QDialog):
    """Diálogo modal para configurar API Key y modelo."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Configuración - CartoAI Copilot")
        self.resize(440, 220)
        self._setup_ui()
        self._load_values()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.combo_provider = QComboBox()
        self.combo_provider.addItems(["Google Gemini", "OpenAI"])
        self.combo_provider.currentIndexChanged.connect(self._on_provider_changed)
        form.addRow("Proveedor de IA:", self.combo_provider)

        self.edit_model = QLineEdit()
        form.addRow("Modelo LLM:", self.edit_model)

        self.edit_api_key = QLineEdit()
        self.edit_api_key.setEchoMode(_get_echo_mode(True))
        self.edit_api_key.setPlaceholderText("Introduce tu API Key...")

        h_box_key = QHBoxLayout()
        h_box_key.addWidget(self.edit_api_key)
        self.btn_show_key = QPushButton("👁")
        self.btn_show_key.setFixedWidth(35)
        self.btn_show_key.setCheckable(True)
        self.btn_show_key.toggled.connect(self._toggle_key_visibility)
        h_box_key.addWidget(self.btn_show_key)
        form.addRow("API Key:", h_box_key)

        layout.addLayout(form)

        info_label = QLabel(
            "<small><i>Recomendado para Gemini: <b>gemini-3.5-flash-lite</b> (alta velocidad y sin saturación).</i></small>"
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        self.button_box = QDialogButtonBox(_get_button_flags())
        self.button_box.accepted.connect(self._save_values)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def _toggle_key_visibility(self, checked: bool):
        self.edit_api_key.setEchoMode(_get_echo_mode(not checked))

    def _on_provider_changed(self):
        is_gemini = (self.combo_provider.currentText() == "Google Gemini")
        current_text = self.edit_model.text().strip()
        if is_gemini and (not current_text or "gpt" in current_text or "1.5" in current_text):
            self.edit_model.setText("gemini-3.5-flash-lite")
        elif not is_gemini and (not current_text or "gemini" in current_text):
            self.edit_model.setText("gpt-4o-mini")

    def _load_values(self):
        provider = AISettingsManager.get_provider()
        idx = 0 if provider == "gemini" else 1
        self.combo_provider.setCurrentIndex(idx)
        self.edit_model.setText(AISettingsManager.get_model_name())
        self.edit_api_key.setText(AISettingsManager.get_api_key())

    def _save_values(self):
        provider = "gemini" if self.combo_provider.currentIndex() == 0 else "openai"
        AISettingsManager.set_provider(provider)
        AISettingsManager.set_model_name(self.edit_model.text())
        AISettingsManager.set_api_key(self.edit_api_key.text())
        self.accept()


class ChatInputField(QPlainTextEdit):
    """Campo de texto con soporte para enviar con Enter y salto con Shift+Enter."""

    returnPressed = pyqtSignal()

    def keyPressEvent(self, event):
        key = event.key()
        key_return = getattr(Qt.Key, "Key_Return", None) or getattr(Qt, "Key_Return")
        key_enter = getattr(Qt.Key, "Key_Enter", None) or getattr(Qt, "Key_Enter")
        shift_mod = getattr(Qt.KeyboardModifier, "ShiftModifier", None) or getattr(Qt, "ShiftModifier")

        if key in (key_return, key_enter):
            if int(event.modifiers()) & int(shift_mod):
                super().keyPressEvent(event)
            else:
                self.returnPressed.emit()
        else:
            super().keyPressEvent(event)


class CartoAgentDockWidget(QDockWidget):
    """Panel lateral interactivo de CartoAI Copilot."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__("CartoAI Copilot: Map & GIS Architect", parent)
        self.setObjectName("CartoAICopilotDockWidget")

        left_area = getattr(Qt.DockWidgetArea, "LeftDockWidgetArea", None) or getattr(Qt, "LeftDockWidgetArea")
        right_area = getattr(Qt.DockWidgetArea, "RightDockWidgetArea", None) or getattr(Qt, "RightDockWidgetArea")
        self.setAllowedAreas(left_area | right_area)

        self.chat_history: List[Dict[str, str]] = []
        self._active_task: Optional[CartoAgentWorkerTask] = None

        self._setup_ui()
        self._show_welcome_message()

    def _setup_ui(self):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # 1. Barra superior
        top_bar = QHBoxLayout()
        header_title = QLabel("<b style='color:#0284C7; font-size:13px;'>🌐 CartoAI Copilot</b> <span style='color: #64748B; font-size:11px;'>• Map Architect</span>")
        top_bar.addWidget(header_title)
        top_bar.addStretch()

        self.btn_clear = QPushButton("🗑️")
        self.btn_clear.setToolTip("Limpiar historial de chat")
        self.btn_clear.setFixedSize(28, 28)
        self.btn_clear.clicked.connect(self._clear_chat)
        top_bar.addWidget(self.btn_clear)

        self.btn_settings = QPushButton("⚙️")
        self.btn_settings.setToolTip("Configurar API Key")
        self.btn_settings.setFixedSize(28, 28)
        self.btn_settings.clicked.connect(self._open_settings)
        top_bar.addWidget(self.btn_settings)

        layout.addLayout(top_bar)

        # 2. Visor de Mensajes
        self.chat_browser = QTextBrowser()
        self.chat_browser.setOpenExternalLinks(True)
        self.chat_browser.setStyleSheet("""
            QTextBrowser {
                background-color: #F8FAFC;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 8px;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                font-size: 12px;
            }
        """)
        layout.addWidget(self.chat_browser, stretch=1)

        # 3. Botonera de Atajos Rápidos Interactivos
        actions_scroll = QScrollArea()
        actions_scroll.setFixedHeight(38)
        actions_scroll.setWidgetResizable(True)
        scroll_off = _get_scrollbar_always_off()
        if scroll_off is not None:
            actions_scroll.setHorizontalScrollBarPolicy(scroll_off)
            actions_scroll.setVerticalScrollBarPolicy(scroll_off)
        actions_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        quick_widget = QWidget()
        quick_layout = QHBoxLayout(quick_widget)
        quick_layout.setContentsMargins(0, 2, 0, 2)
        quick_layout.setSpacing(5)

        shortcuts = [
            ("🗺️ Crear Layout", "Crea una composición cartográfica profesional A4 horizontal para imprimir con título, leyenda, escala y norte"),
            ("🎨 Auto-Estilo", "Aplica una simbología armonizada y profesional a las capas del proyecto"),
            ("⭕ Buffer 100m", "Crea un área de influencia (buffer) de 100 metros a la capa activa"),
            ("🏷️ Etiquetar", "Etiqueta los polígonos o puntos con un halo blanco protector"),
            ("📊 Analizar", "¿Qué capas tengo en el proyecto y qué estadísticas y campos tienen?")
        ]

        for label, prompt_text in shortcuts:
            btn = QPushButton(label)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #F1F5F9;
                    border: 1px solid #CBD5E1;
                    border-radius: 12px;
                    padding: 3px 9px;
                    font-size: 11px;
                    color: #334155;
                }
                QPushButton:hover {
                    background-color: #E2E8F0;
                    color: #0284C7;
                    border-color: #0284C7;
                }
            """)
            btn.clicked.connect(lambda checked, p=prompt_text: self._send_quick_prompt(p))
            quick_layout.addWidget(btn)

        quick_layout.addStretch()
        actions_scroll.setWidget(quick_widget)
        layout.addWidget(actions_scroll)

        # 4. Barra de Progreso
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFixedHeight(5)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar { border: none; background-color: #E2E8F0; border-radius: 2px; }
            QProgressBar::chunk { background-color: #0284C7; border-radius: 2px; }
        """)
        layout.addWidget(self.progress_bar)

        # 5. Entrada de texto
        self.input_edit = ChatInputField()
        self.input_edit.setFixedHeight(60)
        self.input_edit.setPlaceholderText("Pídeme un mapa, geoproceso o estilo... [Enter para enviar]")
        self.input_edit.returnPressed.connect(self._handle_send_message)
        layout.addWidget(self.input_edit)

        # 6. Barra inferior
        btn_layout = QHBoxLayout()
        self.status_label = QLabel("Listo")
        self.status_label.setStyleSheet("color: #64748B; font-size: 11px;")
        btn_layout.addWidget(self.status_label)
        btn_layout.addStretch()

        self.btn_send = QPushButton(" Enviar")
        self.btn_send.setIcon(QIcon(QgsApplication.iconPath("mActionArrowRight.svg")))
        self.btn_send.setStyleSheet("""
            QPushButton {
                background-color: #0284C7;
                color: white;
                font-weight: bold;
                padding: 6px 14px;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #0369A1; }
            QPushButton:disabled { background-color: #94A3B8; }
        """)
        self.btn_send.clicked.connect(self._handle_send_message)
        btn_layout.addWidget(self.btn_send)

        layout.addLayout(btn_layout)
        self.setWidget(container)

    def _show_welcome_message(self):
        welcome_html = """
        <div style="background-color: #EFF6FF; border-left: 4px solid #0284C7; padding: 10px; border-radius: 4px; margin-bottom: 8px;">
            <b style="color: #0284C7; font-size: 13px;">🌐 ¡Bienvenido a CartoAI Copilot!</b><br>
            <p style="color: #1E293B; margin-top: 4px; margin-bottom: 6px;">
            Tu asistente de IA para <b>diseño cartográfico, geoprocesamiento y creación de mapas</b> a nivel mundial.
            </p>
            <span style="color: #475569; font-size: 11px;">
            <b>Ejemplos de lo que puedes pedirme:</b><br>
            • <i>"Diseña una composición de impresión en A4 con título 'Mapa de Cobertura', leyenda y norte"</i><br>
            • <i>"Haz un buffer de 200 metros sobre la capa de ríos"</i><br>
            • <i>"Aplica una simbología categorizada con colores Spectral a la capa de municipios"</i><br>
            • <i>"Activa etiquetas con halo blanco en la capa de ciudades"</i><br>
            • <i>"Filtra la capa para mostrar solo registros con población mayor a 50000"</i>
            </span>
        </div>
        """
        self.chat_browser.setHtml(welcome_html)

    def _send_quick_prompt(self, prompt: str):
        self.input_edit.setPlainText(prompt)
        self._handle_send_message()

    def _open_settings(self):
        dlg = SettingsDialog(self)
        if hasattr(dlg, "exec"):
            dlg.exec()
        else:
            dlg.exec_()

    def _clear_chat(self):
        self.chat_history.clear()
        self.chat_browser.clear()
        self._show_welcome_message()

    def _append_chat_message(self, role: str, content: str):
        if role == "user":
            bubble_html = f"""
            <div style="margin: 8px 0; text-align: right;">
                <div style="display: inline-block; background-color: #0284C7; color: #FFFFFF; padding: 7px 11px; border-radius: 12px 12px 2px 12px; max-width: 85%; text-align: left;">
                    <b>Tú:</b><br>{content}
                </div>
            </div>
            """
        else:
            formatted = content.replace("\n", "<br>")
            bubble_html = f"""
            <div style="margin: 8px 0; text-align: left;">
                <div style="display: inline-block; background-color: #FFFFFF; color: #1E293B; border: 1px solid #E2E8F0; padding: 8px 12px; border-radius: 12px 12px 12px 2px; max-width: 90%;">
                    <b style="color: #0284C7;">CartoAI:</b><br>{formatted}
                </div>
            </div>
            """
        self.chat_browser.append(bubble_html)
        self.chat_browser.verticalScrollBar().setValue(self.chat_browser.verticalScrollBar().maximum())

    def _append_action_badge(self, action_text: str, success: bool = True):
        color = "#10B981" if success else "#EF4444"
        icon = "✓" if success else "✗"
        badge_html = f"""
        <div style="margin: 3px 0 3px 12px;">
            <span style="background-color: {color}; color: white; padding: 2px 8px; border-radius: 4px; font-size: 11px;">
                {icon} {action_text}
            </span>
        </div>
        """
        self.chat_browser.append(badge_html)
        self.chat_browser.verticalScrollBar().setValue(self.chat_browser.verticalScrollBar().maximum())

    def _set_ui_busy(self, busy: bool):
        self.progress_bar.setVisible(busy)
        self.btn_send.setEnabled(not busy)
        self.input_edit.setEnabled(not busy)
        self.status_label.setText("CartoAI procesando..." if busy else "Listo")

    def _handle_send_message(self):
        text = self.input_edit.toPlainText().strip()
        if not text:
            return

        api_key = AISettingsManager.get_api_key()
        if not api_key:
            QMessageBox.warning(
                self,
                "API Key requerida",
                "Por favor configure su API Key en el icono de engranaje (⚙️) antes de continuar."
            )
            self._open_settings()
            return

        self._append_chat_message("user", text)
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
        llm_text = result.get("llm_content", "")
        reports = result.get("reports", [])

        # Ejecutar las acciones de geoprocesamiento / diseño en el hilo principal
        for report in reports:
            if "qgis_action" in report:
                act_info = report["qgis_action"]
                action = act_info["action"]
                args = act_info["args"]

                res = {"success": False, "message": "Acción no reconocida"}

                if action == "apply_vector_style":
                    res = apply_vector_style(**args)
                elif action == "apply_categorized_style":
                    res = apply_categorized_style(**args)
                elif action == "enable_labels":
                    res = enable_labels(**args)
                elif action == "run_geoprocessing":
                    res = run_geoprocessing(**args)
                elif action == "create_professional_layout":
                    res = create_professional_layout(**args)
                elif action == "zoom_to_layer":
                    res = zoom_to_layer(**args)
                elif action == "apply_filter":
                    res = apply_filter(**args)

                msg = res.get("message") or res.get("error") or "Completado"
                self._append_action_badge(msg, res.get("success", False))

        final_msg = llm_text or "Operación cartográfica completada con éxito."
        self._append_chat_message("assistant", final_msg)

        self.chat_history.append({"role": "user", "content": self._active_task.user_message if self._active_task else ""})
        self.chat_history.append({"role": "assistant", "content": final_msg})
        self._active_task = None

    def _on_task_error(self, error_message: str):
        self._set_ui_busy(False)
        self._append_action_badge(f"Error: {error_message}", False)
        self._append_chat_message("assistant", f"No se pudo completar la operación: <i>{error_message}</i>")
        self._active_task = None
