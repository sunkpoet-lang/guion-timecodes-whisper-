# -*- coding: utf-8 -*-
"""
Guion con Time Codes — punto de entrada de la app.

    python app.py              abre la app en su propia ventana
    python app.py --navegador  la abre en el navegador (útil en Linux sin GTK/Qt)

La interfaz (carpeta web/) la sirve servidor.py en 127.0.0.1 en un puerto libre.
En la ventana de escritorio (pywebview) además hay diálogos nativos para elegir
archivos y carpetas, y arrastrar y soltar entrega la ruta real del archivo (no
hace falta copiar videos de varios GB).

Dentro del ejecutable (.exe) este mismo programa también hace de proceso de
Whisper: servidor.py lo lanza con "--worker ..." para correr alinear_timecodes.py
aparte (ver la explicación en servidor.py).
"""

import os
import socket
import sys
import threading
import time


def _modo_worker():
    # En el .exe sin consola, stdout puede venir vacío si no hay a dónde escribir
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = sys.stdout
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    import alinear_timecodes
    sys.argv = ["alinear_timecodes.py"] + sys.argv[2:]
    alinear_timecodes.main()


def _puerto_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _iniciar_servidor(puerto):
    import uvicorn
    import servidor
    config = uvicorn.Config(servidor.app, host="127.0.0.1", port=puerto, log_level="warning", log_config=None)
    hilo = threading.Thread(target=uvicorn.Server(config).run, daemon=True)
    hilo.start()
    for _ in range(200):
        try:
            with socket.create_connection(("127.0.0.1", puerto), timeout=0.2):
                return servidor
        except OSError:
            time.sleep(0.05)
    raise RuntimeError("El servidor local no arrancó.")


class ApiEscritorio:
    """Funciones que la interfaz llama como window.pywebview.api.<nombre>()."""

    TIPOS = {
        "video": ("Video o audio (*.mp4;*.mov;*.mkv;*.avi;*.mxf;*.wav;*.mp3;*.m4a)", "Todos los archivos (*.*)"),
        "word": ("Documento de Word (*.docx)",),
        "libreto": ("Libreto o subtítulos (*.docx;*.txt;*.srt;*.ass)", "Todos los archivos (*.*)"),
        "traducir": ("Guion (*.docx;*.xlsx;*.txt;*.srt;*.ass)", "Todos los archivos (*.*)"),
        "glosario": ("Glosario de Excel (*.xlsx)",),
        "estilo": ("Reglas de estilo (*.md;*.txt)",),
        "perfil": ("Perfil de traducción (*.json)",),
    }

    def __init__(self):
        self._ventana = None  # con _ para que pywebview no la recorra como parte de la API

    def elegir_archivo(self, tipo):
        import webview
        rutas = self._ventana.create_file_dialog(webview.FileDialog.OPEN, file_types=self.TIPOS.get(tipo, ()))
        return rutas[0] if rutas else None

    def elegir_carpeta(self):
        import webview
        rutas = self._ventana.create_file_dialog(webview.FileDialog.FOLDER)
        return rutas[0] if rutas else None


def _conectar_soltar_archivos(ventana):
    """Arrastrar y soltar: pywebview entrega la ruta completa del archivo (pywebviewFullPath)."""
    import json
    from webview.dom import DOMEventHandler

    def al_soltar(evento):
        archivos = evento.get("dataTransfer", {}).get("files", [])
        rutas = [a.get("pywebviewFullPath") for a in archivos if a.get("pywebviewFullPath")]
        if rutas:
            ventana.evaluate_js(f"window.recibirArchivosSoltados({json.dumps(rutas)})")

    def al_cargar():
        # dragover ya lo cancela web/app.js; aquí solo hace falta el drop para recibir las rutas
        ventana.dom.document.events.drop += DOMEventHandler(al_soltar, True, True)

    ventana.events.loaded += al_cargar


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        _modo_worker()
        return

    forzar_navegador = "--navegador" in sys.argv
    puerto = _puerto_libre()
    servidor = _iniciar_servidor(puerto)
    url = f"http://127.0.0.1:{puerto}/?t={servidor.TOKEN}"

    if not forzar_navegador:
        try:
            import webview
            api = ApiEscritorio()
            ventana = webview.create_window(
                "Guion con Time Codes", url, js_api=api, width=1280, height=860,
                min_size=(900, 640), background_color="#101114", text_select=True,
            )
            api._ventana = ventana
            servidor.ESCRITORIO["activo"] = True
            _conectar_soltar_archivos(ventana)
            webview.start(private_mode=False, storage_path=os.path.join(_carpeta_datos(), "webview"))
            return
        except Exception as e:  # sin WebView2 / GTK / Qt: se usa el navegador
            print(f"No se pudo abrir la ventana de escritorio ({e}). Abriendo en el navegador…")
            servidor.ESCRITORIO["activo"] = False

    import webbrowser
    webbrowser.open(url)
    print(f"La app está abierta en {url}\nCierra esta ventana para salir.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


def _carpeta_datos():
    from rutas import CARPETA_DATOS
    return CARPETA_DATOS


if __name__ == "__main__":
    main()
