# -*- coding: utf-8 -*-
"""
Clase principal y ciclo de vida de CartoAI Copilot: Map & GIS Architect.

Controla la integración con la interfaz de QGIS, el menú de complementos,
la barra de herramientas y la gestión del panel acoplable QDockWidget.
"""

import os

from qgis.PyQt.QtCore import Qt, QCoreApplication
from qgis.PyQt.QtGui import QIcon

try:
    from qgis.PyQt.QtGui import QAction
except ImportError:
    from qgis.PyQt.QtWidgets import QAction

from qgis.core import QgsApplication
from qgis.gui import QgisInterface

from .agent_dockwidget import CartoAgentDockWidget


class ColombiaCartoAgentPlugin:
    """Clase principal del plugin CartoAI Copilot."""

    def __init__(self, iface: QgisInterface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)

        self.action = None
        self.dockwidget: CartoAgentDockWidget = None
        self.menu_name = "&CartoAI Copilot"

    def tr(self, message: str) -> str:
        return QCoreApplication.translate("CartoAICopilotPlugin", message)

    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, "icon.svg")
        if not os.path.exists(icon_path):
            icon = QIcon(QgsApplication.iconPath("mIconModel.svg"))
        else:
            icon = QIcon(icon_path)

        self.action = QAction(icon, self.tr("CartoAI Copilot: Map & GIS Architect"), self.iface.mainWindow())
        self.action.setObjectName("actionCartoAICopilot")
        self.action.setToolTip(self.tr("Abrir panel de CartoAI Copilot para diseño cartográfico y geoprocesamiento"))
        self.action.triggered.connect(self.toggle_dockwidget)

        self.iface.addPluginToMenu(self.menu_name, self.action)
        self.iface.addToolBarIcon(self.action)

        self.dockwidget = CartoAgentDockWidget(self.iface.mainWindow())
        self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dockwidget)
        self.dockwidget.hide()

        self.dockwidget.visibilityChanged.connect(self._on_dock_visibility_changed)

    def _on_dock_visibility_changed(self, visible: bool):
        if self.action:
            self.action.setChecked(visible)

    def toggle_dockwidget(self):
        if not self.dockwidget:
            return

        if self.dockwidget.isVisible():
            self.dockwidget.hide()
        else:
            self.dockwidget.show()
            self.dockwidget.raise_()

    def unload(self):
        if self.action:
            self.iface.removePluginMenu(self.menu_name, self.action)
            self.iface.removeToolBarIcon(self.action)
            del self.action
            self.action = None

        if self.dockwidget:
            self.iface.removeDockWidget(self.dockwidget)
            self.dockwidget.deleteLater()
            self.dockwidget = None
