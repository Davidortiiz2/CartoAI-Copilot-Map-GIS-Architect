# CartoAI Copilot: Map & GIS Architect (QGIS 3 & QGIS 4)

Copiloto inteligente de Inteligencia Artificial integrado en QGIS para **análisis geoespacial avanzado, ejecución de geoprocesamientos y generación automatizada de composiciones cartográficas profesionales (Layouts)** a nivel mundial.

Desarrollado y mantenido por **David Ortiz** (*Estudiante de Geografía*).

---

## 🚀 Capacidades Principales

1. **Interpretación y Análisis Geoespacial Global:**
   - Inspecciona y comprende en tiempo real las capas cargadas en tu proyecto (Shapefiles, GeoPackages, GeoJSON, PostGIS, Ráster).
   - Analiza tipos de geometría, sistemas de referencia de coordenadas (CRS), esquemas de campos y valores de muestra.

2. **Diseño Cartográfico y Simbología Temática:**
   - **Auto-Estilo Armonizado:** Paletas de colores cromáticamente balanceadas y adaptativas según la geometría.
   - **Clasificación Categorizada:** Genera mapas temáticos cualitativos con rampas cromáticas como *Spectral, Viridis, Plasma o Set1*.
   - **Etiquetado Cartográfico Inteligente:** Activa etiquetas con halo protector (buffer blanco) para asegurar lectura clara sobre cualquier fondo.

3. **Generador Automático de Composiciones de Impresión (Layouts):**
   - Diseña mapas listos para PDF/impresión en formato A4 (horizontal o vertical).
   - Incluye automáticamente:
     - Mapa principal centrado a la extensión relevante.
     - Título principal y subtítulo descriptivo.
     - Leyenda dinámica.
     - Barra de escala gráfica con subdivisiones métricas/kilométricas.
     - Flecha de orientación al norte.
     - Cajetín de metadatos (Autor: `David Ortiz`, CRS y fecha de generación).

4. **Geoprocesamiento Espacial Nativo:**
   - Ejecución autónoma de herramientas de análisis mediante la API de Processing:
     - Áreas de influencia (*Buffers* con distancias configurables).
     - Cortes y recortes espaciales (*Clips*).
     - Cálculo de centroides geométricos (*Centroids*).
     - Disolución de límites y fronteras (*Dissolve*).

5. **Panel Interactivo con Atajos Rápidos:**
   - Chips interactivos de 1 clic:
     - 🗺️ *Crear Layout*
     - 🎨 *Auto-Estilo*
     - ⭕ *Buffer 100m*
     - 🏷️ *Etiquetar*
     - 📊 *Analizar*
   - Chat conversacional con soporte de Google Gemini (`gemini-3.5-flash-lite`, respuesta en ~2s) y OpenAI (`gpt-4o-mini`).

---

## 🛠️ Instalación y Activación

El plugin ya se encuentra sincronizado en tu perfil de QGIS:
`%APPDATA%\QGIS\QGIS4\profiles\default\python\plugins\ai_colombia_carto_agent`

1. Abre QGIS.
2. Ve al menú: **Complementos ➔ Administrar e instalar complementos...**
3. En la pestaña **Instalados**, activa la casilla:
   ☑️ **CartoAI Copilot: Map & GIS Architect**
4. Pulsa el ícono en la barra de herramientas para desplegar el panel.

---

## 💡 Ejemplos de Peticiones

* *"Diseña una composición cartográfica horizontal en A4 para imprimir con título 'Mapa de Uso del Suelo', leyenda y escala gráfica."*
* *"Aplica una simbología categorizada con colores Spectral a la capa de municipios según el campo 'tipo'."*
* *"Crea un área de influencia (buffer) de 500 metros alrededor de la capa de vías."*
* *"Activa etiquetas en la capa de ciudades usando el campo 'nombre' con halo blanco."*
* *"¿Qué capas tengo abiertas en el proyecto y qué campos contienen?"*

---

## 📄 Licencia y Créditos
* **Autor:** David Ortiz (Estudiante de Geografía)
* **Repositorio oficial:** [https://github.com/Davidortiiz2/CartoAI-Copilot-Map-GIS-Architect](https://github.com/Davidortiiz2/CartoAI-Copilot-Map-GIS-Architect)
* **Seguimiento de problemas (Issues):** [https://github.com/Davidortiiz2/CartoAI-Copilot-Map-GIS-Architect/issues](https://github.com/Davidortiiz2/CartoAI-Copilot-Map-GIS-Architect/issues)
* **Licencia:** GNU General Public License v2.0+ (GPL-2.0+)
