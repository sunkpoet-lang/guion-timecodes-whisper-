# -*- coding: utf-8 -*-
"""
Carpetas que usa la app, iguales si se corre desde el código fuente o desde
el ejecutable instalado.

- CARPETA_APP: donde están los archivos del programa (en el .exe instalado es
  de solo lectura, por ejemplo dentro de "Archivos de programa").
- CARPETA_DATOS: carpeta del usuario donde sí se puede escribir: modelos
  descargados, librerías de GPU, salidas y configuración.
"""

import os
import platform
import sys

NOMBRE_APP = "GuionTimecodes"

EMPAQUETADO = getattr(sys, "frozen", False)

if EMPAQUETADO:
    # PyInstaller descomprime/ubica los archivos de datos en sys._MEIPASS
    CARPETA_APP = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
else:
    CARPETA_APP = os.path.dirname(os.path.abspath(__file__))


def _carpeta_datos():
    sistema = platform.system()
    if sistema == "Windows":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
        return os.path.join(base, NOMBRE_APP)
    if sistema == "Darwin":
        return os.path.expanduser(f"~/Library/Application Support/{NOMBRE_APP}")
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "guion-timecodes")


CARPETA_DATOS = _carpeta_datos()
CARPETA_MODELOS = os.path.join(CARPETA_DATOS, "modelos")
CARPETA_CUDA = os.path.join(CARPETA_DATOS, "cuda")
CARPETA_SALIDAS = os.path.join(CARPETA_DATOS, "salidas")
CARPETA_SUBIDAS = os.path.join(CARPETA_DATOS, "subidas")

# Modelos que vienen dentro del instalador (el "base"), de solo lectura
CARPETA_MODELOS_INCLUIDOS = os.path.join(CARPETA_APP, "modelos_incluidos")

CARPETA_WEB = os.path.join(CARPETA_APP, "web")

for _c in (CARPETA_MODELOS, CARPETA_CUDA, CARPETA_SALIDAS, CARPETA_SUBIDAS):
    os.makedirs(_c, exist_ok=True)
