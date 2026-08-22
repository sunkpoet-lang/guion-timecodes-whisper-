# -*- coding: utf-8 -*-
"""
Interfaz web local (Gradio) para generar guiones con time codes usando Whisper.

Requisitos (además de lo que ya tienes instalado):
    pip install gradio

Uso:
    python gradio_app.py

Se abre automáticamente en el navegador (normalmente http://127.0.0.1:7860).
Para compartirlo con colegas en la misma red, cambia al final del archivo
demo.launch() por demo.launch(share=True) — Gradio genera un link temporal
accesible desde fuera de tu red (útil para pruebas, pero expone tu equipo
mientras el link esté activo; ciérralo cuando termines).

------------------------------------------------------------------
CÓMO FUNCIONA POR DENTRO (importante):

Este archivo NO reimplementa la lógica de Whisper ni de alineación —
llama a alinear_timecodes.py como un proceso aparte, exactamente igual
que si lo corrieras tú mismo en la terminal.

Esto es intencional: si ese proceso se cierra de golpe por el problema
conocido de ciertos drivers de GPU al terminar de transcribir, solo
muere ESE proceso — el servidor de Gradio y la página en el navegador
siguen funcionando con normalidad. Esta interfaz detecta cuando eso
pasa (el archivo de salida no se generó, pero sí existe el respaldo de
Whisper) y automáticamente vuelve a llamar al script con
--continuar_desde para terminar el trabajo, sin que el usuario tenga
que hacer nada ni enterarse de que algo falló a medio camino.
------------------------------------------------------------------
"""

import os
import platform
import re
import subprocess
import sys
import uuid

import gradio as gr

CARPETA_SCRIPT = os.path.dirname(os.path.abspath(__file__))
SCRIPT_ALINEAR = os.path.join(CARPETA_SCRIPT, "alinear_timecodes.py")
CARPETA_SALIDAS = os.path.join(CARPETA_SCRIPT, "salidas_gradio")
os.makedirs(CARPETA_SALIDAS, exist_ok=True)

IDIOMAS = {"Inglés": "en", "Español": "es", "Francés": "fr", "Japonés": "ja"}
MODOS = {
    "Proporcional (guion traducido a otro idioma)": "proporcional",
    "Texto (guion en el mismo idioma que el audio)": "texto",
}
TAREAS = {
    "Transcribir (mismo idioma del audio)": "transcribir",
    "Traducir a inglés": "traducir_a_ingles",
}

OPCION_CON_GUION = "Ya tengo transcripción/traducción (genera Word con TIME CODE)"
OPCION_ASREC = "Ya tengo un ASREC sin TIME CODE (mismo idioma que el audio)"
OPCION_SIN_GUION = "No tengo transcripción (genera subtítulos .srt directo del video)"


def _detectar_gpu_generica():
    """
    Detecta el nombre de CUALQUIER GPU presente (NVIDIA, AMD, Intel), sin
    depender de nvidia-smi. Solo se usa cuando nvidia-smi ya falló, para
    poder avisar específicamente "tienes una GPU, pero no es NVIDIA" en vez
    de simplemente "no se detectó GPU".
    """
    sistema = platform.system()
    try:
        if sistema == "Windows":
            try:
                salida = subprocess.check_output(
                    ["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_VideoController).Name"],
                    stderr=subprocess.DEVNULL, timeout=8,
                ).decode("utf-8", errors="ignore")
            except Exception:
                salida = subprocess.check_output(
                    ["wmic", "path", "win32_VideoController", "get", "name"],
                    stderr=subprocess.DEVNULL, timeout=8,
                ).decode("utf-8", errors="ignore")
            lineas = [l.strip() for l in salida.splitlines() if l.strip() and "name" not in l.lower()]
            return lineas[0] if lineas else None

        elif sistema == "Linux":
            salida = subprocess.check_output(
                ["lspci"], stderr=subprocess.DEVNULL, timeout=8
            ).decode("utf-8", errors="ignore")
            for linea in salida.splitlines():
                if "VGA" in linea or "3D controller" in linea:
                    return linea.split(":")[-1].strip()
            return None

        elif sistema == "Darwin":
            salida = subprocess.check_output(
                ["system_profiler", "SPDisplaysDataType"], stderr=subprocess.DEVNULL, timeout=8
            ).decode("utf-8", errors="ignore")
            for linea in salida.splitlines():
                if "Chipset Model" in linea:
                    return linea.split(":")[-1].strip()
            return None
    except Exception:
        return None
    return None


def _detectar_ram_gb():
    """
    Detecta la RAM total del equipo con comandos nativos del sistema operativo,
    sin depender de ninguna librería externa (no requiere instalar psutil ni nada).
    """
    sistema = platform.system()
    try:
        if sistema == "Windows":
            try:
                salida = subprocess.check_output(
                    ["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory"],
                    stderr=subprocess.DEVNULL, timeout=8,
                ).decode("utf-8", errors="ignore").strip()
                bytes_totales = int(salida)
            except Exception:
                salida = subprocess.check_output(
                    ["wmic", "ComputerSystem", "get", "TotalPhysicalMemory"],
                    stderr=subprocess.DEVNULL, timeout=8,
                ).decode("utf-8", errors="ignore")
                lineas = [l.strip() for l in salida.splitlines() if l.strip().isdigit()]
                bytes_totales = int(lineas[0]) if lineas else None
            return round(bytes_totales / (1024 ** 3), 1) if bytes_totales else None

        elif sistema == "Darwin":
            salida = subprocess.check_output(
                ["sysctl", "-n", "hw.memsize"], stderr=subprocess.DEVNULL, timeout=5
            ).decode("utf-8", errors="ignore").strip()
            return round(int(salida) / (1024 ** 3), 1)

        elif sistema == "Linux":
            with open("/proc/meminfo") as f:
                for linea in f:
                    if linea.startswith("MemTotal:"):
                        kb = int(linea.split()[1])
                        return round(kb / (1024 ** 2), 1)
    except Exception:
        return None
    return None


def detectar_hardware():
    """
    Detecta GPU NVIDIA (vía nvidia-smi, sin necesitar PyTorch), núcleos de CPU
    y RAM disponible (con comandos nativos del sistema operativo, sin librerías
    extra). Si no hay GPU NVIDIA, intenta detectar si hay alguna OTRA marca de
    GPU presente (AMD/Intel) solo para poder explicar por qué no se usa —
    faster-whisper únicamente acelera con GPUs NVIDIA (CUDA).
    Cualquier parte que no se pueda detectar queda en None sin interrumpir
    el arranque de la app.
    """
    info = {
        "gpu_name": None, "gpu_vram_gb": None,
        "otra_gpu_name": None,
        "cpu_cores": os.cpu_count() or 1, "ram_gb": _detectar_ram_gb(),
    }

    try:
        salida = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            stderr=subprocess.DEVNULL, timeout=5,
        ).decode("utf-8", errors="ignore").strip()
        if salida:
            nombre, vram_mb = [p.strip() for p in salida.splitlines()[0].split(",")]
            info["gpu_name"] = nombre
            info["gpu_vram_gb"] = round(float(vram_mb) / 1024, 1)
    except Exception:
        pass

    if info["gpu_name"] is None:
        otra = _detectar_gpu_generica()
        # Ignora coincidencias de NVIDIA aquí (ya se habría detectado arriba si
        # nvidia-smi funcionara; si aparece por este otro método pero nvidia-smi
        # falló, igual no podemos usarla para acelerar — se reporta tal cual).
        info["otra_gpu_name"] = otra

    return info


def sugerir_modelo(info):
    """Devuelve (modelo_sugerido, dispositivo, motivo) según el hardware detectado."""
    if info["gpu_vram_gb"] is not None:
        vram = info["gpu_vram_gb"]
        nombre = info["gpu_name"] or "tu GPU"
        if vram >= 10:
            modelo, motivo = "large-v3", f"{nombre} ({vram} GB) tiene VRAM de sobra para el modelo más preciso."
        elif vram >= 6:
            modelo, motivo = "medium", f"{nombre} ({vram} GB) corre bien este tamaño con buena velocidad."
        elif vram >= 4:
            modelo, motivo = "small", f"{nombre} ({vram} GB) tiene VRAM limitada — este tamaño es más seguro."
        else:
            modelo, motivo = "base", f"{nombre} ({vram} GB) tiene poca VRAM — se sugiere el modelo más ligero."
        return modelo, "GPU", motivo

    ram = info["ram_gb"]
    if ram and ram >= 16:
        return "small", "CPU", "no se detectó GPU compatible; con esta RAM, CPU puede con 'small' a buen ritmo."
    return "base", "CPU", "no se detectó GPU compatible y la RAM es limitada — se sugiere el modelo más ligero."


HARDWARE = detectar_hardware()
MODELO_SUGERIDO, DISPOSITIVO_SUGERIDO, MOTIVO_SUGERIDO = sugerir_modelo(HARDWARE)


def _panel_deteccion_html():
    estilo_label = "color:#999999 !important; padding:3px 0; width:60px;"
    estilo_val = "text-align:right; padding:3px 0; color:#dddddd !important;"

    filas = [f"<tr><td style='{estilo_label}'>CPU</td><td style='{estilo_val}'>{HARDWARE['cpu_cores']} núcleos</td></tr>"]
    if HARDWARE["ram_gb"]:
        filas.append(f"<tr><td style='{estilo_label}'>RAM</td><td style='{estilo_val}'>{HARDWARE['ram_gb']} GB</td></tr>")

    if HARDWARE["gpu_name"]:
        filas.append(
            f"<tr><td style='{estilo_label}'>GPU</td>"
            f"<td style='{estilo_val}'>{HARDWARE['gpu_name']} · {HARDWARE['gpu_vram_gb']} GB VRAM</td></tr>"
        )
    elif HARDWARE["otra_gpu_name"]:
        filas.append(f"<tr><td style='{estilo_label}'>GPU</td><td style='{estilo_val}'>{HARDWARE['otra_gpu_name']}</td></tr>")
    else:
        filas.append(f"<tr><td style='{estilo_label}'>GPU</td><td style='{estilo_val}'>No disponible</td></tr>")

    if DISPOSITIVO_SUGERIDO == "GPU":
        color_msg = "#173404"
        bg_msg = "#EAF3DE"
        icono = "✓"
        mensaje = f'usando <b style="color:{color_msg} !important;">{MODELO_SUGERIDO}</b>'
        prefijo = "Se detectó GPU — "
    else:
        color_msg = "#412402"
        bg_msg = "#FAEEDA"
        icono = "⚠"
        if HARDWARE["otra_gpu_name"]:
            prefijo = f"Se detectó {HARDWARE['otra_gpu_name']}, pero Whisper solo acelera con GPUs NVIDIA — "
        else:
            prefijo = "No se detectó GPU — "
        mensaje = f'usando CPU con <b style="color:{color_msg} !important;">{MODELO_SUGERIDO}</b>'

    return f"""
    <div style="border:0.5px solid #666666; border-radius:8px; padding:10px 14px; margin-bottom:6px;">
      <div style="background:{bg_msg}; padding:6px 12px; border-radius:6px; font-size:12.5px; font-weight:600;
                  display:flex; align-items:center; gap:6px; width:fit-content; margin-bottom:10px;">
        <span style="color:{color_msg} !important;">{icono}</span>
        <span style="color:{color_msg} !important;">{prefijo}{mensaje}</span>
      </div>
      <table style="width:100%; font-size:12px;">{''.join(filas)}</table>
      <p style="font-size:11px; color:#999999 !important; margin:8px 0 0;">{MOTIVO_SUGERIDO}</p>
    </div>
    """

PATRON_PORCENTAJE = re.compile(r"Transcribiendo:\s+(\d+)%")


def _ruta(archivo_subido):
    """Gradio entrega objetos con .name (ruta temporal) o directamente strings, según versión."""
    return archivo_subido.name if hasattr(archivo_subido, "name") else archivo_subido


def _correr_script_streaming(args_lista):
    """
    Corre alinear_timecodes.py con los argumentos dados y va entregando (yield)
    fragmentos de su salida conforme se producen — incluyendo las actualizaciones
    de la barra de progreso, que usan retorno de carro (\\r) en vez de salto de
    línea normal. Por eso se lee carácter por carácter en vez de por líneas
    completas: así no hay que esperar a que termine el proceso para ver avance.

    Al final entrega (None, codigo_de_salida) para señalar que ya terminó.
    """
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"  # evita que Python retenga la salida en buffer

    proceso = subprocess.Popen(
        [sys.executable, "-u", SCRIPT_ALINEAR] + args_lista,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=CARPETA_SCRIPT,
        env=env,
    )

    buffer = ""
    while True:
        caracter = proceso.stdout.read(1)
        if caracter == "" and proceso.poll() is not None:
            break
        if caracter:
            buffer += caracter
            if caracter in ("\n", "\r"):
                yield buffer, None
                buffer = ""

    if buffer:
        yield buffer, None

    proceso.wait()
    yield None, proceso.returncode


def generar(modo_trabajo, video_file, guion_file, idioma_label, modo_label, modelo_label,
            nombre_salida, exportar_srt, tarea_label, formato_mmss, progreso=gr.Progress()):
    """
    Función conectada al botón principal. Es un generador: cada 'yield' hace
    que Gradio actualice la interfaz en vivo (estado, registro, barra de
    progreso), sin esperar a que todo el proceso termine.
    """
    if video_file is None:
        yield "Falta subir el video.", "", None, None
        return

    identificador = uuid.uuid4().hex[:8]
    idioma_audio = IDIOMAS.get(idioma_label, "es")
    tarea = TAREAS.get(tarea_label, "transcribir")

    # =========================================================
    # MODO SIN GUION: subtítulos directos de lo que dice Whisper
    # =========================================================
    if modo_trabajo == OPCION_SIN_GUION:
        nombre_srt = (nombre_salida or "").strip() or "subtitulos"
        nombre_srt = nombre_srt.rsplit(".", 1)[0] + ".srt"
        ruta_srt = os.path.join(CARPETA_SALIDAS, f"{identificador}_{nombre_srt}")
        respaldo_json = ruta_srt.rsplit(".", 1)[0] + "_respaldo_whisper.json"

        args_base = [
            "--video", _ruta(video_file),
            "--salida", ruta_srt,
            "--idioma_audio", idioma_audio,
            "--modelo", modelo_label,
            "--tarea", tarea,
        ]
        # (sin --guion: alinear_timecodes.py entra solo al modo de subtítulos directos)

        log = ""
        estado = "Transcribiendo…"
        yield estado, log, None, None

        for fragmento, codigo in _correr_script_streaming(args_base):
            if fragmento is not None:
                log += fragmento
                match = PATRON_PORCENTAJE.search(fragmento)
                if match:
                    pct = int(match.group(1))
                    progreso(pct / 100, desc=f"Transcribiendo… {pct}%")
                yield estado, log, None, None

        exito = os.path.exists(ruta_srt)

        if not exito and os.path.exists(respaldo_json):
            estado = "La transcripción terminó pero el proceso se cerró antes de guardar. Completando con el respaldo…"
            yield estado, log, None, None

            args_continuar = args_base + ["--continuar_desde", respaldo_json]
            for fragmento, codigo in _correr_script_streaming(args_continuar):
                if fragmento is not None:
                    log += fragmento
                    yield estado, log, None, None

            exito = os.path.exists(ruta_srt)

        if exito:
            yield "Listo. Subtítulos generados.", log, None, ruta_srt
        else:
            yield "No se pudo generar el archivo. Revisa el registro.", log, None, None
        return

    # =========================================================
    # MODO CON GUION: alinea un guion existente, genera Word (+ SRT opcional)
    # =========================================================
    if guion_file is None:
        yield "Falta subir el guion en Word.", "", None, None
        return

    nombre_docx = (nombre_salida or "").strip() or "resultado_con_timecodes.docx"
    if not nombre_docx.lower().endswith(".docx"):
        nombre_docx += ".docx"

    ruta_salida = os.path.join(CARPETA_SALIDAS, f"{identificador}_{nombre_docx}")
    respaldo_json = ruta_salida.rsplit(".", 1)[0] + "_respaldo_whisper.json"
    ruta_srt = ruta_salida.rsplit(".", 1)[0] + ".srt"

    args_base = [
        "--video", _ruta(video_file),
        "--guion", _ruta(guion_file),
        "--salida", ruta_salida,
        "--idioma_audio", idioma_audio,
        "--modo", MODOS.get(modo_label, "texto"),
        "--modelo", modelo_label,
        "--formato_tc", "mmss" if formato_mmss else "completo",
    ]
    if exportar_srt:
        args_base.append("--exportar_srt")

    log = ""
    estado = "Transcribiendo…"
    yield estado, log, None, None

    for fragmento, codigo in _correr_script_streaming(args_base):
        if fragmento is not None:
            log += fragmento
            match = PATRON_PORCENTAJE.search(fragmento)
            if match:
                pct = int(match.group(1))
                progreso(pct / 100, desc=f"Transcribiendo… {pct}%")
            yield estado, log, None, None

    exito = os.path.exists(ruta_salida)

    if not exito and os.path.exists(respaldo_json):
        estado = "La transcripción terminó pero el proceso se cerró antes de guardar. Completando con el respaldo…"
        yield estado, log, None, None

        args_continuar = args_base + ["--continuar_desde", respaldo_json]
        for fragmento, codigo in _correr_script_streaming(args_continuar):
            if fragmento is not None:
                log += fragmento
                yield estado, log, None, None

        exito = os.path.exists(ruta_salida)

    srt_generado = ruta_srt if os.path.exists(ruta_srt) else None

    if exito:
        yield "Listo. Documento generado.", log, ruta_salida, srt_generado
    else:
        yield "No se pudo generar el documento. Revisa el registro para más detalles.", log, None, None


CSS_INSIGNIAS = """
.insignia { display:inline-flex; align-items:center; gap:6px; padding:4px 10px;
            border-radius:6px; font-size:12px; font-weight:600; margin-bottom:6px; }
.insignia-video { background:#FAECE7; color:#712B13; }
.insignia-docx  { background:#E6F1FB; color:#0C447C; }
.insignia-srt   { background:#E1F5EE; color:#04342C; }

.panel-deteccion { border:0.5px solid #cccccc; border-radius:8px; padding:10px 14px; margin-bottom:6px; }
.det-ok   { background:#EAF3DE; color:#173404; padding:6px 12px; border-radius:6px; font-size:12.5px;
            font-weight:600; display:flex; align-items:center; gap:6px; width:fit-content; margin-bottom:10px; }
.det-warn { background:#FAEEDA; color:#412402; padding:6px 12px; border-radius:6px; font-size:12.5px;
            font-weight:600; display:flex; align-items:center; gap:6px; width:fit-content; margin-bottom:10px; }
.det-tabla { width:100%; font-size:12px; }
.det-label { color:#888888; padding:2px 0; width:60px; }
.det-val { text-align:right; padding:2px 0; }
.det-motivo { font-size:11px; color:#888888; margin:8px 0 0; }

.panel-pasos { background:#f2f2f2; border-radius:8px; padding:12px 16px; margin-bottom:10px; }
.pasos-titulo { font-size:12px; font-weight:600; color:#555555; margin:0 0 8px; }
.pasos-grid { display:grid; grid-template-columns:repeat(3, 1fr); gap:10px; }
.paso-item { display:flex; gap:8px; font-size:11.5px; color:#555555; }
.paso-num { font-weight:700; color:#185FA5; }

.panel-requisitos { background:#E6F1FB; border-radius:8px; padding:12px 16px; margin-bottom:10px; }
.requisitos-titulo { font-size:12px; font-weight:600; color:#0C447C; margin:0 0 6px; }
.requisitos-texto { font-size:11.5px; color:#0C447C; margin:0; line-height:1.6; }

.tabla-ejemplo { width:100%; font-size:11.5px; border-collapse:collapse; margin-top:6px; }
.tabla-ejemplo th { text-align:left; padding:6px 8px; border-bottom:1px solid #cccccc; font-weight:600; }
.tabla-ejemplo td { padding:6px 8px; border-bottom:0.5px solid #dddddd; color:#555555; }
"""

with gr.Blocks(title="Guion con time codes - Whisper") as demo:
    gr.Markdown("## Guion con time codes - Whisper")

    gr.HTML("""
    <div style="background:#f2f2f2; border-radius:8px; padding:12px 16px; margin-bottom:10px;">
      <p style="font-size:12px; font-weight:600; color:#333333 !important; margin:0 0 8px;">Cómo usar esta página</p>
      <div style="display:grid; grid-template-columns:repeat(3, 1fr); gap:10px;">
        <div style="display:flex; gap:8px; font-size:11.5px;"><span style="font-weight:700; color:#185FA5 !important;">1</span><span style="color:#333333 !important;">Elige si ya tienes guion o no</span></div>
        <div style="display:flex; gap:8px; font-size:11.5px;"><span style="font-weight:700; color:#185FA5 !important;">2</span><span style="color:#333333 !important;">Sube el video (y el guion si aplica)</span></div>
        <div style="display:flex; gap:8px; font-size:11.5px;"><span style="font-weight:700; color:#185FA5 !important;">3</span><span style="color:#333333 !important;">Genera y descarga el resultado</span></div>
      </div>
    </div>
    """)

    gr.HTML("""
    <div style="background:#E6F1FB; border-radius:8px; padding:12px 16px; margin-bottom:10px;">
      <p style="font-size:12px; font-weight:600; color:#0C447C !important; margin:0 0 6px;">Formato del guion que necesitas subir (si ya tienes uno)</p>
      <p style="font-size:11.5px; color:#0C447C !important; margin:0; line-height:1.6;">
        <span style="color:#0C447C !important;">Un .docx con una tabla de 2 columnas:</span>
        <b style="color:#0C447C !important;">PERSONAJE</b>
        <span style="color:#0C447C !important;">y</span>
        <b style="color:#0C447C !important;">DIÁLOGO</b>
        <span style="color:#0C447C !important;">(encabezados con esos nombres, o "CHARACTER"/"DIALOGUE"). Sale directo de la
        herramienta "Convertir libreto a 3 columnas". Sin tabla, también acepta párrafos con formato
        "PERSONAJE: diálogo".</span>
      </p>
    </div>
    """)

    modo_trabajo_input = gr.Radio(
        choices=[OPCION_CON_GUION, OPCION_ASREC, OPCION_SIN_GUION],
        value=OPCION_CON_GUION,
        label="¿Qué necesitas?",
    )

    with gr.Row():
        with gr.Column():
            gr.HTML('<span class="insignia insignia-video">🎬 VIDEO</span>')
            video_input = gr.File(label="Video del episodio", file_types=[".mov", ".mp4", ".avi", ".mkv"])
        with gr.Column():
            gr.HTML('<span class="insignia insignia-docx">📄 WORD</span>')
            guion_input = gr.File(label="Guion en Word (transcripción/traducción ya lista)", file_types=[".docx"])

    with gr.Row():
        idioma_input = gr.Dropdown(choices=list(IDIOMAS.keys()), value="Inglés", label="Idioma del audio")
        modo_input = gr.Dropdown(
            choices=list(MODOS.keys()),
            value="Proporcional (guion traducido a otro idioma)",
            label="Modo de alineación",
        )

    tarea_input = gr.Dropdown(
        choices=list(TAREAS.keys()),
        value="Transcribir (mismo idioma del audio)",
        label="Tarea de Whisper",
        info="\"Traducir a inglés\" solo traduce A INGLÉS (limitación del modelo) — útil para generar "
             "subtítulos en inglés desde audio en japonés u otro idioma, sin traducción previa.",
        visible=False,
    )

    gr.HTML(_panel_deteccion_html())

    modelo_input = gr.Dropdown(
        choices=["tiny", "base", "small", "medium", "large-v3"],
        value=MODELO_SUGERIDO,
        label="Modelo de Whisper",
        info="Modelos más grandes = más precisos pero más lentos y con más uso de memoria. "
             "Ya se preseleccionó el recomendado para tu equipo — puedes cambiarlo si quieres.",
    )

    salida_input = gr.Textbox(label="Nombre del archivo de salida", value="resultado_con_timecodes.docx")
    srt_input = gr.Checkbox(
        label="Exportar también subtítulos (.srt)",
        value=False,
        info="Reutiliza los mismos timecodes del Word — útil para revisar sincronía en un reproductor de video.",
    )
    mmss_input = gr.Checkbox(
        label="TIME CODE en formato MM:SS (convención de doblaje)",
        value=False,
        info="Escribe el TIME CODE del Word como MMSS (ej. 0114 = 1 min 14 s) en vez de HH:MM:SS,mmm. "
             "No afecta el .srt, que siempre queda con el formato completo.",
    )

    def _actualizar_campos(modo_trabajo, video_file):
        con_guion = modo_trabajo in (OPCION_CON_GUION, OPCION_ASREC)
        extension = ".docx" if con_guion else ".srt"

        if video_file is not None:
            nombre_base = os.path.splitext(os.path.basename(_ruta(video_file)))[0]
        else:
            nombre_base = "resultado_con_timecodes" if con_guion else "subtitulos"

        if modo_trabajo == OPCION_ASREC:
            modo_valor = "Texto (guion en el mismo idioma que el audio)"
        else:
            modo_valor = "Proporcional (guion traducido a otro idioma)"

        return (
            gr.update(visible=con_guion),   # guion_input
            gr.update(visible=con_guion, value=modo_valor),   # modo_input
            gr.update(visible=con_guion),   # srt_input (checkbox opcional; en modo sin guion, el srt ES la salida)
            gr.update(visible=not con_guion),  # tarea_input (traducir a inglés solo aplica sin guion)
            gr.update(value=nombre_base + extension),  # salida_input
        )

    modo_trabajo_input.change(
        fn=_actualizar_campos,
        inputs=[modo_trabajo_input, video_input],
        outputs=[guion_input, modo_input, srt_input, tarea_input, salida_input],
    )
    video_input.change(
        fn=_actualizar_campos,
        inputs=[modo_trabajo_input, video_input],
        outputs=[guion_input, modo_input, srt_input, tarea_input, salida_input],
    )

    boton = gr.Button("Generar", variant="primary")

    estado_output = gr.Textbox(label="Estado", interactive=False)
    log_output = gr.Textbox(label="Registro", lines=12, interactive=False, max_lines=25)
    with gr.Row():
        with gr.Column():
            gr.HTML('<span class="insignia insignia-docx">📄 WORD (TIME CODE)</span>')
            archivo_output = gr.File(label="Documento generado")
        with gr.Column():
            gr.HTML('<span class="insignia insignia-srt">💬 SUBS</span>')
            srt_output = gr.File(label="Subtítulos")

    boton.click(
        fn=generar,
        inputs=[modo_trabajo_input, video_input, guion_input, idioma_input, modo_input,
                modelo_input, salida_input, srt_input, tarea_input, mmss_input],
        outputs=[estado_output, log_output, archivo_output, srt_output],
    )

    gr.HTML("""
    <p style="font-size:12px; font-weight:500; color:#555555; margin:16px 0 0;">Así se ve el Word que vas a obtener</p>
    <table style="width:100%; font-size:11.5px; border-collapse:collapse; margin-top:6px; color:#333333 !important;">
      <tr>
        <th style="text-align:left; padding:6px 8px; border-bottom:1px solid #999999; font-weight:600; color:#333333 !important;">TC</th>
        <th style="text-align:left; padding:6px 8px; border-bottom:1px solid #999999; font-weight:600; color:#333333 !important;">PERSONAJE</th>
        <th style="text-align:left; padding:6px 8px; border-bottom:1px solid #999999; font-weight:600; color:#333333 !important;">DIÁLOGO</th>
      </tr>
      <tr><td style="padding:6px 8px; border-bottom:0.5px solid #666666; color:#cccccc !important;">0034</td><td style="padding:6px 8px; border-bottom:0.5px solid #666666; color:#cccccc !important;">MONGO</td><td style="padding:6px 8px; border-bottom:0.5px solid #666666; color:#cccccc !important;">[REAC]</td></tr>
      <tr><td style="padding:6px 8px; border-bottom:0.5px solid #666666; color:#cccccc !important;">0048</td><td style="padding:6px 8px; border-bottom:0.5px solid #666666; color:#cccccc !important;">JACK</td><td style="padding:6px 8px; border-bottom:0.5px solid #666666; color:#cccccc !important;">Fuera de mi camino.</td></tr>
      <tr><td style="padding:6px 8px; border-bottom:0.5px solid #666666; color:#cccccc !important;">0051</td><td style="padding:6px 8px; border-bottom:0.5px solid #666666; color:#cccccc !important;">JEREMY</td><td style="padding:6px 8px; border-bottom:0.5px solid #666666; color:#cccccc !important;">Oigan, supe que se ahogaron.</td></tr>
      <tr><td style="padding:6px 8px; border-bottom:0.5px solid #666666; color:#cccccc !important;">0107</td><td style="padding:6px 8px; border-bottom:0.5px solid #666666; color:#cccccc !important;">SHARK</td><td style="padding:6px 8px; border-bottom:0.5px solid #666666; color:#cccccc !important;">¡Es hora del sorteo!</td></tr>
      <tr><td style="padding:6px 8px; color:#cccccc !important;">0114</td><td style="padding:6px 8px; color:#cccccc !important;">TAJ</td><td style="padding:6px 8px; color:#cccccc !important;">¡Ay, no! No en su cancha.</td></tr>
    </table>
    <p style="font-size:10.5px; color:#888888 !important; margin:6px 0 0;">Ejemplo ilustrativo — el TC real depende del audio de tu video.</p>
    """)

if __name__ == "__main__":
    demo.launch(css=CSS_INSIGNIAS)
