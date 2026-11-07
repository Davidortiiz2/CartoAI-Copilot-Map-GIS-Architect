# -*- coding: utf-8 -*-
"""
Punto de entrada oficial para el plugin 'Colombia Open Data & Carto Agent' en QGIS 3.

QGIS busca la función classFactory() al cargar el plugin desde el directorio de complementos.
"""

def classFactory(iface):
    """
    Función de fábrica requerida por la API de plugins de QGIS.

    Args:
        iface (QgisInterface): Puntero a la interfaz principal de QGIS.

    Returns:
        ColombiaCartoAgentPlugin: Instancia de la clase principal del plugin.
    """
    from .main_plugin import ColombiaCartoAgentPlugin
    return ColombiaCartoAgentPlugin(iface)

