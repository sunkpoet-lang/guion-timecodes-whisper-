# -*- coding: utf-8 -*-
"""
Catálogo de modelos de Whisper (versiones de faster-whisper / CTranslate2
publicadas en Hugging Face por sus autores), descarga con progreso, borrado,
y recomendación según el hardware del equipo.

Dónde busca modelos ya instalados, en este orden:
  1. CARPETA_MODELOS            (descargados desde la app)
  2. CARPETA_MODELOS_INCLUIDOS  (el "base" que viene con el instalador)
  3. La caché de Hugging Face   (modelos que faster-whisper ya había bajado
                                 antes, por ejemplo con la versión anterior
                                 de esta herramienta: no se vuelven a descargar)
"""

import os
import shutil
import threading
import urllib.error
import urllib.request

import cuda_runtime
from rutas import CARPETA_MODELOS, CARPETA_MODELOS_INCLUIDOS

# Archivos que necesita faster-whisper (igual que faster_whisper.utils.download_model)
ARCHIVOS_MODELO = ["config.json", "preprocessor_config.json", "model.bin", "tokenizer.json",
                   "vocabulary.txt", "vocabulary.json"]

# precision/velocidad: escala 1-5 para las barras de la interfaz.
# vram_gb: VRAM mínima cómoda en GPU (float16). ram_gb: RAM que ocupa en CPU (int8).
# costo_gpu / costo_cpu: minutos aproximados para 22 min de audio en una GPU de gama
# media (RTX 3060) y en una CPU de 8 núcleos. Solo sirven para comparar entre modelos.
CATALOGO = [
    {"id": "tiny", "nombre": "Tiny", "repo": "Systran/faster-whisper-tiny", "tamano_mb": 75,
     "precision": 1, "velocidad": 5, "vram_gb": 1, "ram_gb": 1, "costo_gpu": 0.4, "costo_cpu": 0.6,
     "traduce": True, "solo_ingles": False,
     "nota": "Solo para pruebas rápidas. Comete muchos errores."},
    {"id": "base", "nombre": "Base", "repo": "Systran/faster-whisper-base", "tamano_mb": 141,
     "precision": 2, "velocidad": 5, "vram_gb": 1, "ram_gb": 1, "costo_gpu": 0.5, "costo_cpu": 1.2,
     "traduce": True, "solo_ingles": False,
     "nota": "Viene incluido. Sirve en cualquier equipo, pero es poco preciso."},
    {"id": "small", "nombre": "Small", "repo": "Systran/faster-whisper-small", "tamano_mb": 464,
     "precision": 3, "velocidad": 4, "vram_gb": 2, "ram_gb": 2, "costo_gpu": 0.8, "costo_cpu": 3,
     "traduce": True, "solo_ingles": False,
     "nota": "Buen equilibrio para equipos sin GPU."},
    {"id": "medium", "nombre": "Medium", "repo": "Systran/faster-whisper-medium", "tamano_mb": 1460,
     "precision": 4, "velocidad": 3, "vram_gb": 4, "ram_gb": 3, "costo_gpu": 1.8, "costo_cpu": 7,
     "traduce": True, "solo_ingles": False,
     "nota": "Preciso. En casi todo conviene más Large v3 Turbo."},
    {"id": "large-v3-turbo", "nombre": "Large v3 Turbo", "repo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
     "tamano_mb": 1547, "precision": 4.5, "velocidad": 4, "vram_gb": 4, "ram_gb": 3, "costo_gpu": 1.0,
     "costo_cpu": 7, "traduce": False, "solo_ingles": False,
     "nota": "Casi tan preciso como Large v3 y varias veces más rápido. No sirve para \"Traducir a inglés\"."},
    {"id": "large-v3", "nombre": "Large v3", "repo": "Systran/faster-whisper-large-v3", "tamano_mb": 2948,
     "precision": 5, "velocidad": 2, "vram_gb": 6, "ram_gb": 5, "costo_gpu": 3.0, "costo_cpu": 14,
     "traduce": True, "solo_ingles": False,
     "nota": "El más preciso. Ideal con GPU; en CPU es muy lento."},
    {"id": "distil-large-v3.5", "nombre": "Distil Large v3.5", "repo": "distil-whisper/distil-large-v3.5-ct2",
     "tamano_mb": 1446, "precision": 4, "velocidad": 4, "vram_gb": 4, "ram_gb": 3, "costo_gpu": 0.9,
     "costo_cpu": 6, "traduce": False, "solo_ingles": True,
     "nota": "Solo para audio en INGLÉS. Rápido y preciso en ese caso."},
]
POR_ID = {m["id"]: m for m in CATALOGO}


# ------------------------------------------------------------------
# Modelos instalados
# ------------------------------------------------------------------

def _es_modelo_valido(carpeta):
    return os.path.isfile(os.path.join(carpeta, "model.bin")) and os.path.isfile(os.path.join(carpeta, "config.json"))


def _en_cache_hf(repo):
    try:
        from huggingface_hub import snapshot_download
        ruta = snapshot_download(repo, local_files_only=True, allow_patterns=ARCHIVOS_MODELO)
        return ruta if _es_modelo_valido(ruta) else None
    except Exception:
        return None


def ubicar(id_modelo):
    """Devuelve (ruta, origen) del modelo instalado, o (None, None)."""
    m = POR_ID[id_modelo]
    propia = os.path.join(CARPETA_MODELOS, id_modelo)
    if _es_modelo_valido(propia):
        return propia, "app"
    incluida = os.path.join(CARPETA_MODELOS_INCLUIDOS, id_modelo)
    if _es_modelo_valido(incluida):
        return incluida, "incluido"
    cache = _en_cache_hf(m["repo"])
    if cache:
        return cache, "cache_hf"
    return None, None


def borrar(id_modelo):
    ruta, origen = ubicar(id_modelo)
    if origen == "incluido":
        raise RuntimeError("El modelo incluido con la app no se puede borrar.")
    if origen == "app":
        shutil.rmtree(ruta, ignore_errors=True)
    elif origen == "cache_hf":
        # .../hub/models--Org--Nombre/snapshots/<hash>  ->  .../hub/models--Org--Nombre
        shutil.rmtree(os.path.dirname(os.path.dirname(ruta)), ignore_errors=True)


# ------------------------------------------------------------------
# Descargas (una a la vez por modelo, en segundo plano, cancelables)
# ------------------------------------------------------------------

DESCARGAS = {}  # id_modelo -> {"hechos", "total", "error", "cancelar"}
_candado = threading.Lock()


def _archivos_remotos(repo):
    """Lista [(nombre, tamaño)] de los archivos del modelo en Hugging Face."""
    try:
        from huggingface_hub import HfApi
        info = HfApi().model_info(repo, files_metadata=True)
        return [(s.rfilename, s.size or 0) for s in info.siblings if s.rfilename in ARCHIVOS_MODELO]
    except Exception:
        return [(n, 0) for n in ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")]


def _descargar(id_modelo):
    m = POR_ID[id_modelo]
    estado = DESCARGAS[id_modelo]
    destino = os.path.join(CARPETA_MODELOS, id_modelo)
    temporal = destino + ".descargando"
    shutil.rmtree(temporal, ignore_errors=True)
    os.makedirs(temporal)

    try:
        archivos = _archivos_remotos(m["repo"])
        estado["total"] = sum(t for _, t in archivos) or m["tamano_mb"] * 1024 ** 2
        for nombre, _ in archivos:
            url = f"https://huggingface.co/{m['repo']}/resolve/main/{nombre}"
            try:
                respuesta = urllib.request.urlopen(url, timeout=60)
            except urllib.error.HTTPError as e:
                if e.code == 404:  # vocabulary.txt/.json: cada repo trae solo uno
                    continue
                raise
            with respuesta, open(os.path.join(temporal, nombre), "wb") as f:
                while True:
                    if estado["cancelar"]:
                        raise InterruptedError
                    bloque = respuesta.read(1024 * 1024)
                    if not bloque:
                        break
                    f.write(bloque)
                    estado["hechos"] += len(bloque)

        if not _es_modelo_valido(temporal):
            raise RuntimeError("La descarga quedó incompleta.")
        shutil.rmtree(destino, ignore_errors=True)
        os.replace(temporal, destino)
        with _candado:
            DESCARGAS.pop(id_modelo, None)
    except InterruptedError:
        shutil.rmtree(temporal, ignore_errors=True)
        with _candado:
            DESCARGAS.pop(id_modelo, None)
    except Exception as e:
        shutil.rmtree(temporal, ignore_errors=True)
        estado["error"] = f"No se pudo descargar: {e}"


def iniciar_descarga(id_modelo):
    with _candado:
        actual = DESCARGAS.get(id_modelo)
        if actual and not actual["error"]:
            return
        DESCARGAS[id_modelo] = {"hechos": 0, "total": POR_ID[id_modelo]["tamano_mb"] * 1024 ** 2,
                                "error": None, "cancelar": False}
    threading.Thread(target=_descargar, args=(id_modelo,), daemon=True).start()


def cancelar_descarga(id_modelo):
    estado = DESCARGAS.get(id_modelo)
    if estado:
        estado["cancelar"] = True
        if estado["error"]:
            DESCARGAS.pop(id_modelo, None)


# ------------------------------------------------------------------
# Recomendación según hardware
# ------------------------------------------------------------------

def configuracion_gpu(hw):
    """(puede_usar_cuda, compute_type) según la GPU NVIDIA detectada."""
    gpu = hw.get("gpu")
    if not gpu:
        return False, None
    cc = gpu.get("compute_cap")
    if cc is None or cc >= 7.0:
        return True, "float16"
    if cc >= 6.1:
        return True, "int8"      # Pascal (GTX 10xx): float16 es lento, int8 sí rinde
    if cc >= 3.5:
        return True, "float32"
    return False, None


def _capacidad_cpu(hw):
    """Núcleos 'equivalentes' respecto a la CPU de referencia de 8 núcleos."""
    nucleos = min(hw.get("cpu_nucleos") or 4, 16)
    factor = 1.0 if hw.get("apple_silicon") else 0.5  # los lógicos x86 incluyen hyperthreading
    return max(nucleos * factor / 8, 0.3)


def evaluar(hw, dispositivo):
    """
    Para cada modelo del catálogo: si cabe en memoria, minutos estimados por
    episodio de 22 min y un veredicto ("ok", "lento", "no_cabe").
    dispositivo: "cuda" o "cpu".
    """
    resultado = {}
    for m in CATALOGO:
        if dispositivo == "cuda":
            vram = hw["gpu"]["vram_gb"]
            cabe = vram >= m["vram_gb"]
            minutos = m["costo_gpu"] * (1.6 if configuracion_gpu(hw)[1] != "float16" else 1)
        else:
            ram = hw.get("ram_gb") or 8
            cabe = ram >= m["ram_gb"] * 2  # deja memoria para el resto del sistema
            minutos = m["costo_cpu"] / _capacidad_cpu(hw)
        if not cabe:
            veredicto = "no_cabe"
        elif minutos > 10:
            veredicto = "lento"
        else:
            veredicto = "ok"
        resultado[m["id"]] = {"minutos": round(minutos, 1), "veredicto": veredicto}
    return resultado


def recomendar(evaluacion, idioma_ingles=False):
    """El modelo más preciso que cabe y no es lento (el más rápido si empatan)."""
    candidatos = [m for m in CATALOGO
                  if evaluacion[m["id"]]["veredicto"] == "ok" and (idioma_ingles or not m["solo_ingles"])]
    if not candidatos:
        return "base"
    candidatos.sort(key=lambda m: (m["precision"], -evaluacion[m["id"]]["minutos"]), reverse=True)
    return candidatos[0]["id"]


def resumen(hw):
    """Todo lo que la interfaz necesita para la pestaña Modelos y el selector de modelo."""
    cuda_estado = cuda_runtime.estado()
    gpu_compatible, compute_type = configuracion_gpu(hw)
    gpu_lista = gpu_compatible and cuda_estado["listo"]
    dispositivo = "cuda" if gpu_lista else "cpu"

    evaluacion = evaluar(hw, dispositivo)
    recomendado = recomendar(evaluacion)

    # Si hay GPU NVIDIA pero faltan librerías: qué se ganaría al activarla
    recomendado_con_gpu = None
    if gpu_compatible and not cuda_estado["listo"]:
        recomendado_con_gpu = recomendar(evaluar(hw, "cuda"))

    modelos = []
    for m in CATALOGO:
        ruta, origen = ubicar(m["id"])
        descarga = DESCARGAS.get(m["id"])
        modelos.append({
            **{k: v for k, v in m.items() if k != "repo"},
            "url": f"https://huggingface.co/{m['repo']}",
            "instalado": ruta is not None,
            "origen": origen,
            "descarga": None if not descarga else {
                "hechos": descarga["hechos"], "total": descarga["total"], "error": descarga["error"],
            },
            **evaluacion[m["id"]],
        })

    return {
        "hardware": hw,
        "cuda": cuda_estado,
        "gpu_compatible": gpu_compatible,
        "dispositivo": dispositivo,
        "compute_type": compute_type if gpu_lista else "int8",
        "recomendado": recomendado,
        "recomendado_con_gpu": recomendado_con_gpu,
        "modelos": modelos,
    }
