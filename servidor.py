# -*- coding: utf-8 -*-
"""
Servidor local (FastAPI) que atiende a la interfaz de web/.

Solo escucha en 127.0.0.1 y cada petición a /api necesita el token aleatorio
con el que se abrió la ventana, para que ninguna página web externa pueda
usarlo aunque sepa el puerto.

------------------------------------------------------------------
CÓMO FUNCIONA LA TRANSCRIPCIÓN (igual que en la versión con Gradio):

No se llama a Whisper dentro de este proceso: se corre alinear_timecodes.py
como un proceso aparte. Si ese proceso se cierra de golpe (el problema conocido
de ciertos drivers de GPU al terminar de transcribir), la app sigue viva, detecta
que no se generó el archivo pero sí el respaldo de Whisper, y vuelve a llamar
al script con --continuar_desde para terminar sin transcribir de nuevo.
------------------------------------------------------------------
"""

import json
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import uuid

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import cuda_runtime
import hardware
import modelos
from convertir_libreto import detectar_y_parsear, generar_docx_3_columnas
from rutas import CARPETA_APP, CARPETA_SALIDAS, CARPETA_SUBIDAS, CARPETA_WEB, EMPAQUETADO
from version import REPO_GITHUB, VERSION

TOKEN = secrets.token_urlsafe(24)
SISTEMA = platform.system()
_SIN_VENTANA = {"creationflags": 0x08000000} if SISTEMA == "Windows" else {}

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/web", StaticFiles(directory=CARPETA_WEB), name="web")


def verificar_token(request: Request):
    if request.headers.get("X-Token") != TOKEN and request.query_params.get("t") != TOKEN:
        raise HTTPException(403, "Token inválido")


api = Depends(verificar_token)


@app.get("/", response_class=HTMLResponse)
def inicio():
    with open(os.path.join(CARPETA_WEB, "index.html"), encoding="utf-8") as f:
        return f.read()


# ------------------------------------------------------------------
# Hardware (se detecta una vez, en segundo plano, al arrancar)
# ------------------------------------------------------------------

HW = {"datos": None}


def _detectar_hardware():
    HW["datos"] = hardware.detectar()


threading.Thread(target=_detectar_hardware, daemon=True).start()


def _hw():
    for _ in range(100):
        if HW["datos"]:
            return HW["datos"]
        time.sleep(0.1)
    raise HTTPException(503, "Detectando hardware…")


@app.get("/api/estado", dependencies=[api])
def estado():
    return {"version": VERSION, "sistema": SISTEMA, "escritorio": ESCRITORIO["activo"],
            "ocupado": _trabajo_activo() is not None, **modelos.resumen(_hw()), "cuda_instalacion": CUDA_JOB}


# ------------------------------------------------------------------
# Modelos y GPU
# ------------------------------------------------------------------

def _validar_modelo(id_modelo):
    if id_modelo not in modelos.POR_ID:
        raise HTTPException(404, "Modelo desconocido")


@app.post("/api/modelos/{id_modelo}/descargar", dependencies=[api])
def descargar_modelo(id_modelo: str):
    _validar_modelo(id_modelo)
    modelos.iniciar_descarga(id_modelo)
    return {"ok": True}


@app.post("/api/modelos/{id_modelo}/cancelar", dependencies=[api])
def cancelar_modelo(id_modelo: str):
    _validar_modelo(id_modelo)
    modelos.cancelar_descarga(id_modelo)
    return {"ok": True}


@app.delete("/api/modelos/{id_modelo}", dependencies=[api])
def borrar_modelo(id_modelo: str):
    _validar_modelo(id_modelo)
    try:
        modelos.borrar(id_modelo)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


CUDA_JOB = {"activo": False, "etapa": "", "hechos": 0, "total": 0, "error": None, "cancelar": False}


def _instalar_cuda():
    def progreso(etapa, hechos, total):
        CUDA_JOB.update(etapa=etapa, hechos=hechos, total=total)
    try:
        cuda_runtime.instalar(progreso, cancelado=lambda: CUDA_JOB["cancelar"])
    except Exception as e:
        CUDA_JOB["error"] = str(e)
    finally:
        CUDA_JOB["activo"] = False


@app.post("/api/cuda/instalar", dependencies=[api])
def instalar_cuda():
    if not CUDA_JOB["activo"]:
        CUDA_JOB.update(activo=True, etapa="Preparando…", hechos=0, total=0, error=None, cancelar=False)
        threading.Thread(target=_instalar_cuda, daemon=True).start()
    return {"ok": True}


@app.post("/api/cuda/cancelar", dependencies=[api])
def cancelar_cuda():
    CUDA_JOB["cancelar"] = True
    return {"ok": True}


@app.delete("/api/cuda", dependencies=[api])
def borrar_cuda():
    cuda_runtime.desinstalar()
    return {"ok": True}


# ------------------------------------------------------------------
# Archivos
# ------------------------------------------------------------------

# Solo se pueden abrir/descargar archivos que generó la app o que eligió el usuario
RUTAS_PERMITIDAS = set()


def _info_archivo(ruta):
    return {"ruta": ruta, "nombre": os.path.basename(ruta), "tamano": os.path.getsize(ruta)}


class Ruta(BaseModel):
    ruta: str
    carpeta: bool = False


@app.post("/api/archivo", dependencies=[api])
def info_archivo(datos: Ruta):
    """Para rutas que vienen del diálogo nativo o de arrastrar y soltar en la ventana de escritorio."""
    if not os.path.isfile(datos.ruta):
        raise HTTPException(404, "No se encontró el archivo.")
    return _info_archivo(datos.ruta)


@app.post("/api/subir", dependencies=[api])
def subir(archivo: UploadFile = File(...)):
    """Solo se usa en modo navegador, donde no se conoce la ruta real del archivo."""
    carpeta = os.path.join(CARPETA_SUBIDAS, uuid.uuid4().hex[:8])
    os.makedirs(carpeta)
    ruta = os.path.join(carpeta, os.path.basename(archivo.filename or "archivo"))
    with open(ruta, "wb") as f:
        shutil.copyfileobj(archivo.file, f, length=4 * 1024 * 1024)
    return _info_archivo(ruta)


@app.post("/api/abrir", dependencies=[api])
def abrir(datos: Ruta):
    ruta = os.path.abspath(datos.ruta)
    if ruta not in RUTAS_PERMITIDAS or not os.path.exists(ruta):
        raise HTTPException(404, "Archivo no disponible.")
    if SISTEMA == "Windows":
        if datos.carpeta:
            subprocess.Popen(["explorer", "/select,", ruta])
        else:
            os.startfile(ruta)
    elif SISTEMA == "Darwin":
        subprocess.Popen(["open", "-R", ruta] if datos.carpeta else ["open", ruta])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(ruta) if datos.carpeta else ruta])
    return {"ok": True}


@app.get("/api/descargar", dependencies=[api])
def descargar(ruta: str):
    ruta = os.path.abspath(ruta)
    if ruta not in RUTAS_PERMITIDAS or not os.path.isfile(ruta):
        raise HTTPException(404, "Archivo no disponible.")
    return FileResponse(ruta, filename=os.path.basename(ruta))


def _nombre_seguro(nombre, extension, por_defecto):
    nombre = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", (nombre or "").strip()) or por_defecto
    if not nombre.lower().endswith(extension):
        nombre = os.path.splitext(nombre)[0] + extension
    return nombre


def _ruta_libre(carpeta, nombre):
    """Si ya existe 'x.docx', devuelve 'x (2).docx', 'x (3).docx'… para no sobrescribir."""
    base, ext = os.path.splitext(nombre)
    ruta, n = os.path.join(carpeta, nombre), 2
    while os.path.exists(ruta):
        ruta = os.path.join(carpeta, f"{base} ({n}){ext}")
        n += 1
    return ruta


def _carpeta_destino(carpeta, respaldo_desde=None):
    """La carpeta elegida; si no hay, la del video; si no se puede escribir ahí, la de salidas de la app."""
    for opcion in (carpeta, os.path.dirname(respaldo_desde) if respaldo_desde else None):
        if opcion and os.path.isdir(opcion) and os.access(opcion, os.W_OK) \
                and not os.path.abspath(opcion).startswith(os.path.abspath(CARPETA_SUBIDAS)):
            return opcion
    return CARPETA_SALIDAS


# ------------------------------------------------------------------
# Trabajos de Whisper
# ------------------------------------------------------------------

TRABAJOS = {}
PATRON_PORCENTAJE = re.compile(r"(Transcribiendo|Emparejando líneas|Repartiendo líneas):\s+(\d+)%")


def _trabajo_activo():
    return next((t for t in TRABAJOS.values() if t["estado"] == "corriendo"), None)


class PedidoTrabajo(BaseModel):
    modo: str                     # "guion" | "asrec" | "subtitulos"
    video: str
    guion: str | None = None
    idioma: str = "en"
    alineacion: str = "proporcional"
    modelo: str
    tarea: str = "transcribir"
    exportar_srt: bool = False
    formato_mmss: bool = False
    nombre_salida: str = ""
    carpeta_salida: str | None = None


def _comando_worker(args):
    if EMPAQUETADO:
        return [sys.executable, "--worker"] + args
    return [sys.executable, "-u", os.path.join(CARPETA_APP, "alinear_timecodes.py")] + args


def _correr(trabajo, args):
    env = cuda_runtime.entorno_con_cuda(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    proceso = subprocess.Popen(
        _comando_worker(args), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        encoding="utf-8", errors="replace", cwd=CARPETA_APP, env=env, **_SIN_VENTANA,
    )
    trabajo["proceso"] = proceso

    # Se lee carácter por carácter: tqdm actualiza su barra con \r en vez de \n
    linea = ""
    while True:
        c = proceso.stdout.read(1)
        if c == "" and proceso.poll() is not None:
            break
        if c in ("\n", "\r"):
            _procesar_linea(trabajo, linea, reemplazar=(c == "\r"))
            linea = ""
        elif c:
            linea += c
    if linea:
        _procesar_linea(trabajo, linea, reemplazar=False)
    proceso.wait()
    return proceso.returncode


def _procesar_linea(trabajo, linea, reemplazar):
    linea = linea.rstrip()
    if not linea:
        return
    log = trabajo["log"]
    # Las actualizaciones de la barra de progreso reemplazan la línea anterior en vez de acumularse
    if log and trabajo.get("_ultima_era_barra"):
        log[-1] = linea
    else:
        log.append(linea)
    trabajo["_ultima_era_barra"] = reemplazar
    del log[:-400]

    m = PATRON_PORCENTAJE.search(linea)
    if m:
        etapa = {"Transcribiendo": "Transcribiendo audio"}.get(m.group(1), "Alineando el guion")
        trabajo["etapa"] = etapa
        trabajo["progreso"] = int(m.group(2)) / 100
    elif linea.startswith("Cargando modelo"):
        trabajo["etapa"] = "Cargando modelo"
    elif linea.startswith("AVISO_CPU"):
        trabajo["aviso_cpu"] = True
        log[-1] = linea.replace("AVISO_CPU: ", "")
    elif linea.startswith("Idioma detectado"):
        trabajo["idioma_detectado"] = linea.split(":", 1)[1].strip()


def _ejecutar(trabajo, pedido: PedidoTrabajo):
    try:
        ruta_modelo, _ = modelos.ubicar(pedido.modelo)
        if not ruta_modelo:
            raise RuntimeError(f"El modelo '{pedido.modelo}' no está instalado.")

        resumen_hw = modelos.resumen(_hw())
        # Carpeta de trabajo propia: el respaldo de Whisper no ensucia la carpeta del usuario
        trabajo_dir = os.path.join(CARPETA_SALIDAS, "trabajos", trabajo["id"])
        os.makedirs(trabajo_dir, exist_ok=True)
        destino = _carpeta_destino(pedido.carpeta_salida, pedido.video)
        base_video = os.path.splitext(os.path.basename(pedido.video))[0]

        con_guion = pedido.modo in ("guion", "asrec")
        if con_guion:
            nombre = _nombre_seguro(pedido.nombre_salida, ".docx", f"{base_video}_TC.docx")
        else:
            nombre = _nombre_seguro(pedido.nombre_salida, ".srt", f"{base_video}.srt")
        salida_tmp = os.path.join(trabajo_dir, nombre)
        respaldo = salida_tmp.rsplit(".", 1)[0] + "_respaldo_whisper.json"

        args = ["--video", pedido.video, "--salida", salida_tmp, "--idioma_audio", pedido.idioma,
                "--modelo", ruta_modelo, "--dispositivo", resumen_hw["dispositivo"],
                "--compute_type", resumen_hw["compute_type"]]
        if con_guion:
            if not pedido.guion:
                raise RuntimeError("Falta el guion en Word.")
            args += ["--guion", pedido.guion,
                     "--modo", "texto" if pedido.modo == "asrec" else pedido.alineacion,
                     "--formato_tc", "mmss" if pedido.formato_mmss else "completo"]
            if pedido.exportar_srt:
                args.append("--exportar_srt")
        else:
            args += ["--tarea", pedido.tarea]

        trabajo["etapa"] = "Iniciando"
        en = f"GPU ({resumen_hw['compute_type']})" if resumen_hw["dispositivo"] == "cuda" else "procesador"
        trabajo["log"].append(f"Modelo: {modelos.POR_ID[pedido.modelo]['nombre']} en {en}")
        _correr(trabajo, args)

        if not os.path.exists(salida_tmp) and os.path.exists(respaldo) and not trabajo["cancelado"]:
            trabajo["etapa"] = "Recuperando desde el respaldo"
            trabajo["log"].append("El proceso se cerró antes de guardar. Completando con el respaldo de Whisper…")
            _correr(trabajo, args + ["--continuar_desde", respaldo])

        if trabajo["cancelado"]:
            trabajo["estado"] = "cancelado"
            return
        if not os.path.exists(salida_tmp):
            # La última línea del script suele explicar el motivo (guion sin formato, error de Python…)
            ultima = trabajo["log"][-1] if len(trabajo["log"]) > 1 else ""
            raise RuntimeError(ultima or "No se pudo generar el archivo. Revisa el registro para más detalles.")

        resultados = []
        for tmp in [salida_tmp] + ([salida_tmp.rsplit(".", 1)[0] + ".srt"] if con_guion else []):
            if os.path.exists(tmp):
                final = _ruta_libre(destino, os.path.basename(tmp))
                shutil.move(tmp, final)
                RUTAS_PERMITIDAS.add(os.path.abspath(final))
                resultados.append({**_info_archivo(final), "tipo": os.path.splitext(final)[1][1:]})
        trabajo["resultados"] = resultados
        trabajo["estado"] = "listo"
        trabajo["progreso"] = 1
    except Exception as e:
        trabajo["estado"] = "error"
        trabajo["error"] = str(e)
    finally:
        trabajo["fin"] = time.time()
        trabajo.pop("proceso", None)


@app.post("/api/trabajos", dependencies=[api])
def crear_trabajo(pedido: PedidoTrabajo):
    if _trabajo_activo():
        raise HTTPException(409, "Ya hay un trabajo en curso.")
    if not os.path.isfile(pedido.video):
        raise HTTPException(400, "No se encontró el video.")
    _validar_modelo(pedido.modelo)
    trabajo = {"id": uuid.uuid4().hex[:10], "estado": "corriendo", "etapa": "Iniciando", "progreso": 0,
               "log": [], "resultados": [], "error": None, "aviso_cpu": False, "idioma_detectado": None,
               "cancelado": False, "inicio": time.time(), "fin": None}
    TRABAJOS[trabajo["id"]] = trabajo
    threading.Thread(target=_ejecutar, args=(trabajo, pedido), daemon=True).start()
    return {"id": trabajo["id"]}


@app.get("/api/trabajos/{id_trabajo}", dependencies=[api])
def ver_trabajo(id_trabajo: str):
    t = TRABAJOS.get(id_trabajo)
    if not t:
        raise HTTPException(404, "Trabajo no encontrado")
    datos = {k: v for k, v in t.items() if not k.startswith("_") and k != "proceso"}
    datos["transcurrido"] = (t["fin"] or time.time()) - t["inicio"]
    return datos


@app.post("/api/trabajos/{id_trabajo}/cancelar", dependencies=[api])
def cancelar_trabajo(id_trabajo: str):
    t = TRABAJOS.get(id_trabajo)
    if t and t["estado"] == "corriendo":
        t["cancelado"] = True
        proceso = t.get("proceso")
        if proceso:
            proceso.kill()
    return {"ok": True}


# ------------------------------------------------------------------
# Convertir libreto a 3 columnas
# ------------------------------------------------------------------

class PedidoConvertir(BaseModel):
    texto: str | None = None
    ruta: str | None = None


@app.post("/api/libreto/convertir", dependencies=[api])
def convertir(pedido: PedidoConvertir):
    texto = pedido.texto
    if pedido.ruta:
        if pedido.ruta.lower().endswith(".docx"):
            from docx import Document
            texto = "\n".join(p.text for p in Document(pedido.ruta).paragraphs)
        else:
            with open(pedido.ruta, encoding="utf-8", errors="ignore") as f:
                texto = f.read()
    if not texto or not texto.strip():
        raise HTTPException(400, "Pega el texto o elige un archivo .docx, .txt, .srt o .ass.")

    filas, formato = detectar_y_parsear(texto)
    if not filas:
        raise HTTPException(400, "No se detectó ninguna línea. Revisa que el archivo tenga el formato esperado.")
    return {
        "formato": formato,
        "filas": [{"timecode": f.get("timecode", ""), "personaje": f["personaje"],
                   "dialogo": f["dialogo"], "revisar": bool(f.get("revisar"))} for f in filas],
    }


class PedidoExportar(BaseModel):
    filas: list[dict]
    nombre: str = ""
    formato_mmss: bool = False
    carpeta: str | None = None
    origen: str | None = None


@app.post("/api/libreto/exportar", dependencies=[api])
def exportar(pedido: PedidoExportar):
    filas = [{"timecode": (f.get("timecode") or "").strip(), "personaje": (f.get("personaje") or "").strip(),
              "dialogo": (f.get("dialogo") or "").strip()} for f in pedido.filas]
    filas = [f for f in filas if f["dialogo"]]
    if not filas:
        raise HTTPException(400, "No hay filas para exportar.")
    base = os.path.splitext(os.path.basename(pedido.origen))[0] + "_3columnas" if pedido.origen else "guion_3_columnas"
    nombre = _nombre_seguro(pedido.nombre, ".docx", base + ".docx")
    ruta = _ruta_libre(_carpeta_destino(pedido.carpeta, pedido.origen), nombre)
    generar_docx_3_columnas(filas, ruta, formato_tc="mmss" if pedido.formato_mmss else "completo")
    RUTAS_PERMITIDAS.add(os.path.abspath(ruta))
    return {**_info_archivo(ruta), "tipo": "docx", "lineas": len(filas)}


# ------------------------------------------------------------------
# Actualizaciones
# ------------------------------------------------------------------

_ACTUALIZACION = {}


def _version_tupla(v):
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


@app.get("/api/actualizacion", dependencies=[api])
def buscar_actualizacion():
    if "datos" not in _ACTUALIZACION:
        try:
            pedido = urllib.request.Request(f"https://api.github.com/repos/{REPO_GITHUB}/releases/latest",
                                            headers={"Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(pedido, timeout=8) as r:
                rel = json.load(r)
            ultima = rel.get("tag_name", "")
            _ACTUALIZACION["datos"] = {
                "hay": _version_tupla(ultima) > _version_tupla(VERSION),
                "version": ultima.lstrip("v"), "url": rel.get("html_url"),
            }
        except Exception:
            _ACTUALIZACION["datos"] = {"hay": False}
    return _ACTUALIZACION["datos"]


@app.post("/api/abrir-web", dependencies=[api])
def abrir_web(datos: Ruta):
    """Abre en el navegador del sistema los enlaces de la app (releases, páginas de modelos)."""
    import webbrowser
    if datos.ruta.startswith(("https://github.com/", "https://huggingface.co/")):
        webbrowser.open(datos.ruta)
    return {"ok": True}


# Lo llena app.py cuando la interfaz corre en la ventana de escritorio (pywebview)
ESCRITORIO = {"activo": False}
