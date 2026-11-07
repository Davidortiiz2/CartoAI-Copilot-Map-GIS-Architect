"""
Script auxiliar para compilar archivos de recursos Qt (.qrc) a código Python (.py).

En QGIS 3 moderno, es preferible cargar los íconos directamente desde archivos SVG
con QIcon(path), pero este script permite generar 'resources.py' si se desea usar
el sistema tradicional de recursos embebidos de Qt.
"""

import subprocess
import sys
import os

def compile_qrc():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    qrc_path = os.path.join(current_dir, "resources.qrc")
    py_path = os.path.join(current_dir, "resources.py")

    cmd_options = [
        ["pyrcc5", "-o", py_path, qrc_path],
        ["python", "-m", "PyQt5.pyrcc_main", "-o", py_path, qrc_path],
        ["pyqt5-tools", "pyrcc5", "-o", py_path, qrc_path]
    ]

    success = False
    for cmd in cmd_options:
        try:
            print(f"Intentando compilar con: {' '.join(cmd)}")
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            print(f"Éxito: Archivo {py_path} generado correctamente.")
            success = True
            break
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue

    if not success:
        print("Aviso: No se encontró un compilador pyrcc5 en el entorno.")
        print("El plugin utilizará la carga directa de SVG mediante QIcon(), por lo que resources.py no es estrictamente obligatorio.")

if __name__ == "__main__":
    compile_qrc()

