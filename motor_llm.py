# -*- coding: utf-8 -*-
"""
Motor de los modelos de traducción: llama.cpp (llama-server), sin internet.

- Descarga una versión fija de llama.cpp desde sus releases oficiales de GitHub
  la primera vez que se usa (unos 30 MB). En Windows y Linux se usa la versión
  Vulkan, que acelera con GPUs NVIDIA, AMD e Intel y cae a CPU si no hay GPU;
  en Mac, la versión con Metal.
- Detecta los dispositivos que llama.cpp puede usar (y su memoria libre).
- Levanta llama-server en 127.0.0.1 con el modelo elegido, lo reutiliza entre
  traducciones y lo apaga al cerrar la app o tras un rato sin uso.

Se habla con el servidor por su API compatible con OpenAI (/v1/chat/completions).
"""

import atexit
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import tarfile
import threading
import time
import urllib.request
import zipfile

from rutas import CARPETA_DATOS

VERSION_LLAMA = "b11167"
CARPETA_MOTOR = os.path.join(CARPETA_DATOS, "motor_llm")
ARCHIVO_INFO = os.path.join(CARPETA_MOTOR, "instalado.json")

SISTEMA = platform.system()
MAQUINA = platform.machine().lower()
_SIN_VENTANA = {"creationflags": 0x08000000} if SISTEMA == "Windows" else {}
EJECUTABLE = "llama-server.exe" if SISTEMA == "Windows" else "llama-server"


def _nombre_paquete():
    if SISTEMA == "Windows":
        return f"llama-{VERSION_LLAMA}-bin-win-vulkan-x64.zip"
    if SISTEMA == "Darwin":
        return f"llama-{VERSION_LLAMA}-bin-macos-{'arm64' if MAQUINA == 'arm64' else 'x64'}.tar.gz"
    return f"llama-{VERSION_LLAMA}-bin-ubuntu-vulkan-x64.tar.gz"


def _ruta_ejecutable():
    for raiz, _, archivos in os.walk(CARPETA_MOTOR):
        if EJECUTABLE in archivos:
            return os.path.join(raiz, EJECUTABLE)
    return None


def instalado():
    return os.path.exists(ARCHIVO_INFO) and _ruta_ejecutable() is not None


# ------------------------------------------------------------------
# Instalación
# ------------------------------------------------------------------

def instalar(progreso=None, cancelado=lambda: False):
    progreso = progreso or (lambda *a: None)
    nombre = _nombre_paquete()
    url = f"https://github.com/ggml-org/llama.cpp/releases/download/{VERSION_LLAMA}/{nombre}"
    shutil.rmtree(CARPETA_MOTOR, ignore_errors=True)
    os.makedirs(CARPETA_MOTOR)
    destino = os.path.join(CARPETA_MOTOR, nombre)

    progreso("Descargando llama.cpp…", 0, 0)
    with urllib.request.urlopen(url, timeout=60) as r, open(destino, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        hechos = 0
        while True:
            if cancelado():
                raise RuntimeError("Descarga cancelada.")
            bloque = r.read(1024 * 1024)
            if not bloque:
                break
            f.write(bloque)
            hechos += len(bloque)
            progreso("Descargando llama.cpp…", hechos, total)

    progreso("Extrayendo…", hechos, total)
    if nombre.endswith(".zip"):
        with zipfile.ZipFile(destino) as z:
            z.extractall(CARPETA_MOTOR)
    else:
        with tarfile.open(destino) as t:
            t.extractall(CARPETA_MOTOR)
    os.remove(destino)

    ejecutable = _ruta_ejecutable()
    if not ejecutable:
        raise RuntimeError("El paquete de llama.cpp no trae llama-server.")
    if SISTEMA != "Windows":
        os.chmod(ejecutable, 0o755)
    with open(ARCHIVO_INFO, "w", encoding="utf-8") as f:
        json.dump({"version": VERSION_LLAMA}, f)
    _DISPOSITIVOS.clear()


def desinstalar():
    SERVIDOR.detener()
    shutil.rmtree(CARPETA_MOTOR, ignore_errors=True)
    _DISPOSITIVOS.clear()


# ------------------------------------------------------------------
# Dispositivos (GPU que ve llama.cpp)
# ------------------------------------------------------------------

_DISPOSITIVOS = {}
PATRON_DISPOSITIVO = re.compile(r"^\s*(\w+?\d+):\s*(.+?)\s*\((\d+) MiB,\s*(\d+) MiB free\)", re.MULTILINE)


def dispositivos():
    """[{id, nombre, memoria_mb, libre_mb}] de las GPUs que llama.cpp puede usar (vacío = solo CPU)."""
    if "lista" in _DISPOSITIVOS:
        return _DISPOSITIVOS["lista"]
    lista = []
    ejecutable = _ruta_ejecutable()
    if ejecutable:
        try:
            salida = subprocess.run([ejecutable, "--list-devices"], capture_output=True, text=True,
                                    timeout=40, cwd=os.path.dirname(ejecutable), **_SIN_VENTANA)
            texto = salida.stdout + salida.stderr
            for m in PATRON_DISPOSITIVO.finditer(texto):
                lista.append({"id": m.group(1), "nombre": m.group(2),
                              "memoria_mb": int(m.group(3)), "libre_mb": int(m.group(4))})
        except Exception:
            pass
        _DISPOSITIVOS["lista"] = lista
    return lista


# ------------------------------------------------------------------
# Servidor
# ------------------------------------------------------------------

def _puerto_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServidorLlama:
    MINUTOS_INACTIVO = 10

    def __init__(self):
        self.proceso = None
        self.modelo = None
        self.en_gpu = None
        self.puerto = None
        self.ultimo_uso = 0
        self._candado = threading.Lock()
        threading.Thread(target=self._vigilar_inactividad, daemon=True).start()

    def activo(self):
        return self.proceso is not None and self.proceso.poll() is None

    def iniciar(self, ruta_modelo, en_gpu, contexto=8192, log=None):
        """Arranca (o reutiliza) llama-server con el modelo. Espera a que el modelo termine de cargar."""
        with self._candado:
            self.ultimo_uso = time.time()
            if self.activo() and self.modelo == ruta_modelo and self.en_gpu == en_gpu:
                return
            self._detener_sin_candado()
            ejecutable = _ruta_ejecutable()
            if not ejecutable:
                raise RuntimeError("El motor de traducción no está instalado.")
            self.puerto = _puerto_libre()
            comando = [
                ejecutable, "-m", ruta_modelo, "--host", "127.0.0.1", "--port", str(self.puerto),
                "-c", str(contexto), "-np", "1", "--jinja", "--no-webui",
                "-ngl", "999" if en_gpu else "0",
            ]
            registro = open(os.path.join(CARPETA_MOTOR, "llama-server.log"), "w", encoding="utf-8", errors="replace")
            self.proceso = subprocess.Popen(comando, stdout=registro, stderr=subprocess.STDOUT,
                                            cwd=os.path.dirname(ejecutable), **_SIN_VENTANA)
            self.modelo, self.en_gpu = ruta_modelo, en_gpu

        if log:
            log("Cargando el modelo de traducción…")
        limite = time.time() + 600
        while time.time() < limite:
            if not self.activo():
                raise RuntimeError("El motor de traducción se cerró al cargar el modelo. " + self._ultimas_lineas_log())
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.puerto}/health", timeout=2) as r:
                    if r.status == 200:
                        return
            except Exception:
                pass
            time.sleep(0.5)
        self.detener()
        raise RuntimeError("El modelo de traducción tardó demasiado en cargar.")

    def _ultimas_lineas_log(self):
        try:
            with open(os.path.join(CARPETA_MOTOR, "llama-server.log"), encoding="utf-8", errors="replace") as f:
                lineas = [l.strip() for l in f if l.strip()]
            return " | ".join(lineas[-3:])
        except OSError:
            return ""

    def chat(self, mensajes, esquema=None, max_tokens=4096, temperatura=0.2, timeout=600):
        """Llama a /v1/chat/completions. Con esquema, la salida está obligada a ser ese JSON."""
        self.ultimo_uso = time.time()
        cuerpo = {
            "messages": mensajes, "temperature": temperatura, "max_tokens": max_tokens,
            "chat_template_kwargs": {"enable_thinking": False},  # sin "razonamiento": solo la traducción
        }
        if esquema:
            cuerpo["response_format"] = {"type": "json_schema", "json_schema": {"name": "respuesta", "schema": esquema}}
        pedido = urllib.request.Request(
            f"http://127.0.0.1:{self.puerto}/v1/chat/completions", data=json.dumps(cuerpo).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(pedido, timeout=timeout) as r:
            datos = json.load(r)
        self.ultimo_uso = time.time()
        texto = datos["choices"][0]["message"].get("content") or ""
        return re.sub(r"<think>.*?</think>", "", texto, flags=re.DOTALL).strip(), datos.get("usage", {})

    def _detener_sin_candado(self):
        if self.proceso and self.proceso.poll() is None:
            self.proceso.terminate()
            try:
                self.proceso.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proceso.kill()
        self.proceso = None
        self.modelo = None

    def detener(self):
        with self._candado:
            self._detener_sin_candado()

    def _vigilar_inactividad(self):
        while True:
            time.sleep(30)
            if self.activo() and time.time() - self.ultimo_uso > self.MINUTOS_INACTIVO * 60:
                self.detener()


SERVIDOR = ServidorLlama()
atexit.register(SERVIDOR.detener)
