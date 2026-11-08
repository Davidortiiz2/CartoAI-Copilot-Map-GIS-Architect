# CartoAI Copilot: Map & GIS Architect (QGIS 3 & QGIS 4)

Copiloto inteligente de Inteligencia Artificial integrado en QGIS para **análisis geoespacial avanzado, ejecución de geoprocesamientos y generación automatizada de composiciones cartográficas profesionales (Layouts)** a nivel mundial, con arquitectura inspirada en TerraLab.

Desarrollado y mantenido por **David Ortiz** (*Estudiante de Geografía*).

---

## 🚀 Capacidades Principales

1. **Arquitectura Reactiva y Ejecutor PyQGIS en Tiempo Real:**
   - Detección en vivo de la capa activa (`LayerWatch`) mostrando geometría, número de entidades y CRS.
   - Generación y ejecución de scripts PyQGIS en el hilo principal con captura de salidas estándar (`stdout`) y errores.
   - Detección automática y zoom a capas recién creadas.

2. **Diseño Cartográfico y Simbología Temática:**
   - **Auto-Estilo Armonizado:** Paletas de colores cromáticamente balanceadas y adaptativas según la geometría.
   - **Clasificación Categorizada:** Genera mapas temáticos cualitativos con rampas cromáticas como *Spectral, Viridis, Plasma o Set1*.
   - **Etiquetado Cartográfico Inteligente:** Activa etiquetas con halo protector (buffer blanco) para lectura clara sobre cualquier fondo.

3. **Generador Automático de Composiciones de Impresión (Layouts):**
   - Diseña mapas listos para PDF/impresión en formato A4 (horizontal o vertical).
   - Incluye automáticamente:
     - Mapa principal centrado a la extensión relevante.
     - Título principal y subtítulo descriptivo.
     - Leyenda dinámica.
     - Barra de escala gráfica con subdivisiones métricas/kilométricas.
     - Flecha de orientación al norte.
     - Cajetín de metadatos (Autor: `David Ortiz`, CRS y fecha).

4. **Geoprocesamiento Espacial Nativo:**
   - Ejecución autónoma de herramientas de análisis mediante la API de Processing:
     - Áreas de influencia (*Buffers* con distancias configurables).
     - Cortes y recortes espaciales (*Clips*).
     - Cálculo de centroides geométricos (*Centroids*).
     - Disolución de límites y fronteras (*Dissolve*).

5. **Panel Interactivo con Atajos Rápidos (Chips estilo TerraLab):**
   - 🗺️ *Layout A4*
   - 🎨 *Auto-Estilo*
   - ⭕ *Buffer 100m*
   - 🏷️ *Etiquetar*
   - 🌍 *Cargar OSM*
   - 📊 *Analizar Capa*
   - Asistente multimodal con soporte para Google Gemini (`gemini-2.0-flash`), OpenAI (`gpt-4o-mini`) y endpoints locales/personalizados (DeepSeek, Groq, Ollama).
   - Motor local de respaldo: si la nube está ocupada (503/429) o no hay conexión, resuelve comandos cartográficos comunes instantáneamente.

---

## 🛠️ Instalación y Uso en QGIS

1. Abre QGIS (3.28 a 4.99).
2. Ve al menú **Complementos** > **Administrar e instalar complementos...**
3. En la pestaña *Instalados*, activa la casilla **CartoAI Copilot: Map & GIS Architect**.
4. Haz clic en el icono del mapa con destello en la barra de herramientas o accede desde el menú **CartoAI Copilot**.
5. Opcional: Haz clic en el icono de engranaje (⚙️) para ingresar tu clave gratuita de Google Gemini (o OpenAI / DeepSeek).
