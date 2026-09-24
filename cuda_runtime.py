# -*- coding: utf-8 -*-
"""
Librerías de NVIDIA (cuBLAS y cuDNN) que faster-whisper necesita para usar
la GPU.

El driver de la tarjeta NO las trae. Si faltan, faster-whisper carga el modelo
"en GPU" pero falla al empezar a transcribir (cublas64_12.dll not found) y
alinear_timecodes.py cae a CPU sin que se note. Este módulo:

  - detecta si ya están disponibles (instaladas en el sistema o por esta app),
  - las descarga de PyPI (los paquetes oficiales nvidia-cublas-cu12 y
    nvidia-cudnn-cu12, los mismos que instala pip) y extrae solo las
    librerías a CARPETA_CUDA, sin necesitar pip ni Python,
  - entrega las rutas para agregarlas al PATH (Windows) o LD_LIBRARY_PATH
    (Linux) del proceso que transcribe.

En Mac no aplica: no hay GPUs NVIDIA y faster-whisper usa solo CPU.
"""

import ctypes
import json
import os
import platform
import shutil
import sys
import urllib.request
import zipfile

from rutas import CARPETA_CUDA

PAQUETES = ["nvidia-cublas-cu12", "nvidia-cudnn-cu12"]

SISTEMA = platform.system()

if SISTEMA == "Windows":
    LIBRERIAS_CLAVE = ["cublas64_12.dll", "cublasLt64_12.dll", "cudnn_ops64_9.dll", "cudnn_cnn64_9.dll"]
    EXTENSION = ".dll"
else:
    LIBRERIAS_CLAVE = ["libcublas.so.12", "libcublasLt.so.12", "libcudnn_ops.so.9", "libcudnn_cnn.so.9"]
    EXTENSION = ".so"

ARCHIVO_INFO = os.path.join(CARPETA_CUDA, "instalado.json")


def aplica():
    """Solo tiene sentido en Windows y Linux de 64 bits (donde hay GPUs NVIDIA con CUDA)."""
    return SISTEMA in ("Windows", "Linux") and platform.machine().lower() in ("amd64", "x86_64")


def _cargable(nombre, carpeta=None):
    ruta = os.path.join(carpeta, nombre) if carpeta else nombre
    try:
        if SISTEMA == "Windows":
            ctypes.WinDLL(ruta)
        else:
            ctypes.CDLL(ruta)
        return True
    except OSError:
        return False


def instalado_por_la_app():
    return os.path.exists(ARCHIVO_INFO) and all(
        os.path.exists(os.path.join(CARPETA_CUDA, n)) for n in LIBRERIAS_CLAVE
    )


def disponible_en_sistema():
    """True si las librerías ya se pueden cargar sin ayuda (CUDA Toolkit instalado, pip, etc.)."""
    return all(_cargable(n) for n in LIBRERIAS_CLAVE)


def estado():
    if not aplica():
        return {"aplica": False, "listo": False, "origen": None, "tamano_mb": 0}
    if instalado_por_la_app():
        with open(ARCHIVO_INFO, encoding="utf-8") as f:
            info = json.load(f)
        return {"aplica": True, "listo": True, "origen": "app", "tamano_mb": info.get("tamano_mb", 0)}
    if disponible_en_sistema():
        return {"aplica": True, "listo": True, "origen": "sistema", "tamano_mb": 0}
    return {"aplica": True, "listo": False, "origen": None, "tamano_mb": 0}


def carpetas_librerias():
    """Carpetas a agregar al PATH / LD_LIBRARY_PATH del proceso de Whisper."""
    return [CARPETA_CUDA] if instalado_por_la_app() else []


def entorno_con_cuda(env):
    """Devuelve una copia de env con las librerías de la app al frente del buscador de librerías."""
    env = dict(env)
    carpetas = carpetas_librerias()
    if not carpetas:
        return env
    variable = "PATH" if SISTEMA == "Windows" else "LD_LIBRARY_PATH"
    previas = env.get(variable, "")
    env[variable] = os.pathsep.join(carpetas + ([previas] if previas else []))
    return env


def _wheel_para_esta_plataforma(paquete):
    with urllib.request.urlopen(f"https://pypi.org/pypi/{paquete}/json", timeout=30) as r:
        datos = json.load(r)
    version = datos["info"]["version"]
    for archivo in datos["urls"]:
        nombre = archivo["filename"]
        if not nombre.endswith(".whl"):
            continue
        if SISTEMA == "Windows" and nombre.endswith("win_amd64.whl"):
            return version, archivo
        if SISTEMA == "Linux" and "manylinux" in nombre and nombre.endswith("x86_64.whl"):
            return version, archivo
    raise RuntimeError(f"No hay una versión de {paquete} para este sistema.")


def instalar(progreso=None, cancelado=lambda: False):
    """
    Descarga los paquetes de NVIDIA y extrae sus librerías a CARPETA_CUDA.
    progreso(etapa: str, hechos: int, total: int) se llama durante la descarga.
    """
    if not aplica():
        raise RuntimeError("La aceleración por GPU con CUDA solo está disponible en Windows y Linux.")

    progreso = progreso or (lambda *a: None)
    progreso("Consultando versiones…", 0, 0)
    wheels = [(p,) + _wheel_para_esta_plataforma(p) for p in PAQUETES]
    total = sum(w[2]["size"] for w in wheels)
    hechos = 0

    temporal = os.path.join(CARPETA_CUDA, "_descarga")
    os.makedirs(temporal, exist_ok=True)
    versiones = {}

    try:
        for paquete, version, archivo in wheels:
            destino = os.path.join(temporal, archivo["filename"])
            etapa = f"Descargando {paquete} {version}"
            with urllib.request.urlopen(archivo["url"], timeout=60) as r, open(destino, "wb") as f:
                while True:
                    if cancelado():
                        raise RuntimeError("Descarga cancelada.")
                    bloque = r.read(1024 * 1024)
                    if not bloque:
                        break
                    f.write(bloque)
                    hechos += len(bloque)
                    progreso(etapa, hechos, total)

            progreso(f"Extrayendo {paquete}…", hechos, total)
            with zipfile.ZipFile(destino) as z:
                for miembro in z.namelist():
                    base = os.path.basename(miembro)
                    # Solo las librerías (nvidia/<x>/bin/*.dll en Windows, nvidia/<x>/lib/*.so* en Linux)
                    if not base or not (base.endswith(".dll") or ".so" in base):
                        continue
                    with z.open(miembro) as origen, open(os.path.join(CARPETA_CUDA, base), "wb") as salida:
                        shutil.copyfileobj(origen, salida)
            os.remove(destino)
            versiones[paquete] = version
    finally:
        shutil.rmtree(temporal, ignore_errors=True)

    tamano = sum(
        os.path.getsize(os.path.join(CARPETA_CUDA, n)) for n in os.listdir(CARPETA_CUDA)
        if os.path.isfile(os.path.join(CARPETA_CUDA, n))
    )
    with open(ARCHIVO_INFO, "w", encoding="utf-8") as f:
        json.dump({"versiones": versiones, "tamano_mb": round(tamano / 1024 ** 2)}, f)
    progreso("Listo", total, total)


def desinstalar():
    for nombre in os.listdir(CARPETA_CUDA):
        ruta = os.path.join(CARPETA_CUDA, nombre)
        if os.path.isdir(ruta):
            shutil.rmtree(ruta, ignore_errors=True)
        else:
            try:
                os.remove(ruta)
            except OSError:
                pass  # en Windows una DLL cargada no se puede borrar hasta cerrar la app


if __name__ == "__main__":
    # Prueba manual: python cuda_runtime.py [instalar]
    if len(sys.argv) > 1 and sys.argv[1] == "instalar":
        instalar(lambda e, h, t: print(f"\r{e}: {h / 1024**2:.0f}/{t / 1024**2:.0f} MB", end="", flush=True))
        print()
    print(estado())
