# -*- coding: utf-8 -*-
"""
Catálogo de modelos de traducción (LLMs en formato GGUF para llama.cpp),
descarga con progreso y recomendación según la memoria del equipo.

Todos son Apache 2.0 (se pueden usar en trabajo comercial) y se descargan de
Hugging Face sin necesidad de cuenta. Viven en CARPETA_DATOS/modelos_traduccion.
"""

import os
import threading
import urllib.request

import motor_llm
from rutas import CARPETA_DATOS

CARPETA = os.path.join(CARPETA_DATOS, "modelos_traduccion")
os.makedirs(CARPETA, exist_ok=True)

# tamano_mb: el archivo. activos_gb: lo que se lee por cada palabra generada (en los
# modelos "A4B" solo se activa una parte), de eso depende la velocidad.
# calidad: 1-5 para las barras de la interfaz.
CATALOGO = [
    {"id": "qwen3.5-2b", "nombre": "Qwen 3.5 2B", "repo": "unsloth/Qwen3.5-2B-GGUF",
     "archivo": "Qwen3.5-2B-Q4_K_M.gguf", "tamano_mb": 1222, "activos_gb": 1.2, "calidad": 1.5,
     "nota": "Muy liviano. Para equipos sin GPU o con poca RAM; revisa bien el resultado."},
    {"id": "qwen3.5-4b", "nombre": "Qwen 3.5 4B", "repo": "unsloth/Qwen3.5-4B-GGUF",
     "archivo": "Qwen3.5-4B-Q4_K_M.gguf", "tamano_mb": 2614, "activos_gb": 2.6, "calidad": 2.5,
     "nota": "Buen equilibrio en equipos modestos."},
    {"id": "gemma-4-e4b", "nombre": "Gemma 4 E4B", "repo": "google/gemma-4-E4B-it-qat-q4_0-gguf",
     "archivo": "gemma-4-E4B_q4_0-it.gguf", "tamano_mb": 4916, "activos_gb": 2.5, "calidad": 3,
     "nota": "De Google. Rápido para su calidad; bueno con el español."},
    {"id": "qwen3.5-9b", "nombre": "Qwen 3.5 9B", "repo": "unsloth/Qwen3.5-9B-GGUF",
     "archivo": "Qwen3.5-9B-Q4_K_M.gguf", "tamano_mb": 5417, "activos_gb": 5.4, "calidad": 3.5,
     "nota": "Sigue muy bien las reglas de estilo y el glosario."},
    {"id": "gemma-4-12b", "nombre": "Gemma 4 12B", "repo": "google/gemma-4-12B-it-qat-q4_0-gguf",
     "archivo": "gemma-4-12b-it-qat-q4_0.gguf", "tamano_mb": 6653, "activos_gb": 6.7, "calidad": 4,
     "nota": "Traducción natural y matizada. Ideal con una GPU de 10-12 GB."},
    {"id": "gemma-4-26b-a4b", "nombre": "Gemma 4 26B A4B", "repo": "google/gemma-4-26B-A4B-it-qat-q4_0-gguf",
     "archivo": "gemma-4-26B_q4_0-it.gguf", "tamano_mb": 13770, "activos_gb": 2.5, "calidad": 5,
     "nota": "El mejor. Solo activa 4B por palabra: rápido en GPU de 16 GB o más, "
             "y usable en CPU con 32 GB de RAM."},
]
POR_ID = {m["id"]: m for m in CATALOGO}

# Salida aproximada de un episodio de 22 min (~450 líneas), en tokens
TOKENS_EPISODIO = 11000


def ruta(id_modelo):
    return os.path.join(CARPETA, POR_ID[id_modelo]["archivo"])


def instalado(id_modelo):
    return os.path.isfile(ruta(id_modelo))


def borrar(id_modelo):
    motor_llm.SERVIDOR.detener()
    try:
        os.remove(ruta(id_modelo))
    except FileNotFoundError:
        pass


# ------------------------------------------------------------------
# Descargas
# ------------------------------------------------------------------

DESCARGAS = {}
_candado = threading.Lock()


def _descargar(id_modelo):
    m = POR_ID[id_modelo]
    estado = DESCARGAS[id_modelo]
    destino = ruta(id_modelo)
    temporal = destino + ".descargando"
    try:
        url = f"https://huggingface.co/{m['repo']}/resolve/main/{m['archivo']}"
        with urllib.request.urlopen(url, timeout=60) as r, open(temporal, "wb") as f:
            estado["total"] = int(r.headers.get("Content-Length") or estado["total"])
            while True:
                if estado["cancelar"]:
                    raise InterruptedError
                bloque = r.read(4 * 1024 * 1024)
                if not bloque:
                    break
                f.write(bloque)
                estado["hechos"] += len(bloque)
        if estado["total"] and os.path.getsize(temporal) < estado["total"]:
            raise RuntimeError("La descarga quedó incompleta.")
        os.replace(temporal, destino)
        with _candado:
            DESCARGAS.pop(id_modelo, None)
    except InterruptedError:
        _borrar_temporal(temporal)
        with _candado:
            DESCARGAS.pop(id_modelo, None)
    except Exception as e:
        _borrar_temporal(temporal)
        estado["error"] = f"No se pudo descargar: {e}"


def _borrar_temporal(temporal):
    try:
        os.remove(temporal)
    except OSError:
        pass


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
# Recomendación
# ------------------------------------------------------------------

def _gpu(hw):
    """La GPU que usará llama.cpp: la que reporta el motor, o si aún no está instalado, la de hardware.py."""
    lista = motor_llm.dispositivos() if motor_llm.instalado() else []
    if lista:
        mejor = max(lista, key=lambda d: d["memoria_mb"])
        return {"nombre": mejor["nombre"], "vram_gb": round(mejor["memoria_mb"] / 1024, 1)}
    if hw.get("apple_silicon"):
        # En Mac la memoria es compartida: Metal puede usar cerca del 70 % de la RAM
        return {"nombre": "GPU de Apple (Metal)", "vram_gb": round((hw.get("ram_gb") or 8) * 0.7, 1)}
    if hw.get("gpu"):
        return {"nombre": hw["gpu"]["nombre"], "vram_gb": hw["gpu"]["vram_gb"]}
    return None


def evaluar(hw):
    """Por modelo: si va en GPU o CPU, si cabe, y minutos estimados por episodio."""
    gpu = _gpu(hw)
    ram = hw.get("ram_gb") or 8
    resultado = {}
    for m in CATALOGO:
        necesita_gb = m["tamano_mb"] / 1024 + 1.5  # modelo + contexto
        if gpu and gpu["vram_gb"] >= necesita_gb:
            dispositivo = "gpu"
            ancho_banda = 100 if hw.get("apple_silicon") else 180  # GB/s efectivos, aproximados
        else:
            dispositivo = "cpu"
            ancho_banda = 60 if hw.get("apple_silicon") else 20
        tokens_por_segundo = ancho_banda / m["activos_gb"]
        minutos = TOKENS_EPISODIO / tokens_por_segundo / 60 * 1.3  # + procesar el texto de entrada
        if dispositivo == "cpu" and ram < necesita_gb + 4:
            veredicto = "no_cabe"
        elif minutos > 45:
            veredicto = "lento"
        else:
            veredicto = "ok"
        resultado[m["id"]] = {"dispositivo": dispositivo, "minutos": round(minutos, 1), "veredicto": veredicto}
    return resultado


def recomendar(evaluacion):
    """El de mejor calidad que cabe; si alguno cabe entero en la GPU, se elige entre esos."""
    candidatos = [m for m in CATALOGO if evaluacion[m["id"]]["veredicto"] == "ok"]
    en_gpu = [m for m in candidatos if evaluacion[m["id"]]["dispositivo"] == "gpu"]
    candidatos = en_gpu or candidatos
    if not candidatos:
        return "qwen3.5-2b"
    return max(candidatos, key=lambda m: (m["calidad"], -evaluacion[m["id"]]["minutos"]))["id"]


def resumen(hw):
    evaluacion = evaluar(hw)
    modelos = []
    for m in CATALOGO:
        descarga = DESCARGAS.get(m["id"])
        modelos.append({
            **{k: v for k, v in m.items() if k not in ("repo", "archivo")},
            "url": f"https://huggingface.co/{m['repo']}",
            "instalado": instalado(m["id"]),
            "descarga": None if not descarga else {
                "hechos": descarga["hechos"], "total": descarga["total"], "error": descarga["error"]},
            **evaluacion[m["id"]],
        })
    return {
        "motor": {"instalado": motor_llm.instalado(), "version": motor_llm.VERSION_LLAMA,
                  "gpu": _gpu(hw) if motor_llm.instalado() else None},
        "recomendado": recomendar(evaluacion),
        "modelos": modelos,
    }
