# -*- mode: python ; coding: utf-8 -*-
"""
Receta de PyInstaller para el ejecutable.

    pyinstaller empaquetado/guion_timecodes.spec --noconfirm

Genera dist/GuionTimecodes/ (Windows y Linux) o dist/GuionTimecodes.app (Mac).
Antes hay que descargar el modelo que va incluido:
    python empaquetado/descargar_modelo.py base modelos_incluidos/base

Las librerías de NVIDIA (cuBLAS/cuDNN, ~1.8 GB) NO van aquí: la app las
descarga solo si el equipo tiene una GPU NVIDIA (ver cuda_runtime.py).
"""

import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs, collect_submodules

RAIZ = os.path.abspath(os.path.join(SPECPATH, ".."))
ES_MAC = sys.platform == "darwin"
ES_WINDOWS = sys.platform == "win32"

datas = [
    (os.path.join(RAIZ, "web"), "web"),
    (os.path.join(RAIZ, "modelos_incluidos"), "modelos_incluidos"),
]
datas += collect_data_files("faster_whisper")  # modelo de detección de voz (silero VAD)
datas += collect_data_files("docx")            # plantilla por defecto de python-docx

binaries = collect_dynamic_libs("ctranslate2")
hiddenimports = collect_submodules("uvicorn") + ["multipart", "python_multipart"]

for paquete in ("webview", "av", "onnxruntime", "tokenizers"):
    d, b, h = collect_all(paquete)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    [os.path.join(RAIZ, "app.py")],
    pathex=[RAIZ],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["gradio", "torch", "tensorflow", "matplotlib", "tkinter", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

icono = os.path.join(SPECPATH, "icono.ico" if ES_WINDOWS else "icono.png")

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GuionTimecodes",
    console=False,          # sin ventana negra de consola
    icon=icono,
    upx=False,
)

coleccion = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="GuionTimecodes")

if ES_MAC:
    app = BUNDLE(
        coleccion,
        name="GuionTimecodes.app",
        icon=icono,
        bundle_identifier="com.sunkpoet.guiontimecodes",
        info_plist={"CFBundleDisplayName": "Guion con Time Codes", "NSHighResolutionCapable": True},
    )
