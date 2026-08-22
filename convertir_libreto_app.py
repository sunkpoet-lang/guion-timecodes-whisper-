# -*- coding: utf-8 -*-
"""
convertir_libreto_app.py

Interfaz web local para convertir a una tabla de 3 columnas:

    TIME CODE  |  PERSONAJE  |  DIÁLOGO

Soporta 3 formatos de entrada, detectados automáticamente:
- Libreto tradicional (.docx/.txt) → TIME CODE queda vacío (se llena
  después con la otra herramienta, Whisper + video).
- Subtítulos .srt o .ass ya existentes → TIME CODE se llena con el tiempo
  real del archivo, PERSONAJE queda vacío para asignar a mano viendo el
  video (evita copiar bloques de texto y recalcular timecodes).

Requisitos:
    pip install gradio python-docx

Uso:
    python convertir_libreto_app.py
"""

import os
import uuid

import gradio as gr
from docx import Document

from convertir_libreto import detectar_y_parsear, generar_docx_3_columnas

CARPETA_SCRIPT = os.path.dirname(os.path.abspath(__file__))
CARPETA_SALIDAS = os.path.join(CARPETA_SCRIPT, "salidas_conversion")
os.makedirs(CARPETA_SALIDAS, exist_ok=True)


def _leer_archivo(archivo):
    """Extrae texto plano de un .docx (uniendo párrafos, conserva tabuladores), o de .txt/.srt/.ass."""
    ruta = archivo.name if hasattr(archivo, "name") else archivo
    if ruta.lower().endswith(".docx"):
        doc = Document(ruta)
        return "\n".join(p.text for p in doc.paragraphs)
    with open(ruta, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def procesar(texto_pegado, archivo):
    texto = _leer_archivo(archivo) if archivo is not None else texto_pegado
    if not texto or not texto.strip():
        return [], "Pega el texto arriba, o sube un archivo .docx/.txt/.srt/.ass."

    filas, formato = detectar_y_parsear(texto)
    if not filas:
        return [], "No se detectó ninguna línea. Revisa que el archivo tenga el formato esperado."

    tabla = [[f.get("timecode", ""), f["personaje"], f["dialogo"]] for f in filas]
    revisar = sum(1 for f in filas if f["revisar"])

    nombre_formato = {"libreto": "libreto tradicional", "srt": "subtítulos .srt", "ass": "subtítulos .ass"}.get(formato, formato)
    mensaje = f"Formato detectado: {nombre_formato}. {len(filas)} líneas."

    if formato in ("srt", "ass"):
        mensaje += " TIME CODE tomado del archivo — asigna PERSONAJE viendo el video antes de exportar."
    elif revisar:
        mensaje += f" ⚠ {revisar} marcada(s) con '?' en PERSONAJE — revísalas en la tabla antes de exportar."
    else:
        mensaje += " Revisa la tabla y corrige lo que haga falta antes de exportar."

    return tabla, mensaje


def exportar(tabla, nombre_salida, formato_mmss):
    if tabla is None or len(tabla) == 0:
        return None, "No hay nada que exportar. Convierte el archivo primero."

    nombre_salida = (nombre_salida or "").strip() or "guion_3_columnas.docx"
    if not nombre_salida.lower().endswith(".docx"):
        nombre_salida += ".docx"

    identificador = uuid.uuid4().hex[:8]
    ruta_salida = os.path.join(CARPETA_SALIDAS, f"{identificador}_{nombre_salida}")

    filas = [
        {"timecode": (fila[0] or "").strip(), "personaje": (fila[1] or "").strip(), "dialogo": (fila[2] or "").strip()}
        for fila in tabla
    ]
    filas = [f for f in filas if f["dialogo"]]  # descarta filas vacías que Gradio pueda agregar

    generar_docx_3_columnas(filas, ruta_salida, formato_tc="mmss" if formato_mmss else "completo")

    return ruta_salida, f"Documento generado: {os.path.basename(ruta_salida)} ({len(filas)} líneas)"


CSS_INSIGNIAS = """
.insignia { display:inline-flex; align-items:center; gap:6px; padding:4px 10px;
            border-radius:6px; font-size:12px; font-weight:600; margin-bottom:6px; }
.insignia-docx { background:#E6F1FB; color:#0C447C; }

.panel-pasos { background:#f2f2f2; border-radius:8px; padding:12px 16px; margin-bottom:10px; }
.pasos-titulo { font-size:12px; font-weight:600; color:#555555; margin:0 0 8px; }
.pasos-grid { display:grid; grid-template-columns:repeat(3, 1fr); gap:10px; }
.paso-item { display:flex; gap:8px; font-size:11.5px; color:#555555; }
.paso-num { font-weight:700; color:#185FA5; }
"""

with gr.Blocks(title="Convertir libreto a 3 columnas") as demo:
    gr.Markdown("## Convertir a 3 columnas")

    gr.HTML("""
    <div style="background:#f2f2f2; border-radius:8px; padding:12px 16px; margin-bottom:10px;">
      <p style="font-size:12px; font-weight:600; color:#333333 !important; margin:0 0 8px;">Cómo usar esta página</p>
      <div style="display:grid; grid-template-columns:repeat(3, 1fr); gap:10px;">
        <div style="display:flex; gap:8px; font-size:11.5px;"><span style="font-weight:700; color:#185FA5 !important;">1</span><span style="color:#333333 !important;">Pega el texto o sube el archivo</span></div>
        <div style="display:flex; gap:8px; font-size:11.5px;"><span style="font-weight:700; color:#185FA5 !important;">2</span><span style="color:#333333 !important;">Dale Convertir y revisa la tabla</span></div>
        <div style="display:flex; gap:8px; font-size:11.5px;"><span style="font-weight:700; color:#185FA5 !important;">3</span><span style="color:#333333 !important;">Corrige lo necesario y exporta</span></div>
      </div>
    </div>
    """)

    gr.Markdown(
        "Detecta automáticamente el formato: libreto tradicional (PERSONAJE + DIÁLOGO en la misma línea), "
        "guion numerado tipo screenplay (\"N.  PERSONAJE\" con el diálogo en la línea de abajo), o "
        "subtítulos .srt/.ass ya existentes. Con libreto o guion numerado, TIME CODE queda vacío para "
        "llenarse después con la herramienta de Whisper. Con .srt/.ass, TIME CODE ya viene del archivo y "
        "PERSONAJE queda vacío para asignarlo viendo el video."
    )

    with gr.Row():
        texto_input = gr.Textbox(
            label="Pega aquí el texto (libreto, .srt o .ass)",
            lines=15,
            placeholder="1 (10:00:02:00)\n\nJEREMY\tRequin!\nPETIT DRAGON\tRequin!\n...",
        )
        archivo_input = gr.File(label="…o sube un archivo (.docx / .txt / .srt / .ass)",
                                 file_types=[".docx", ".txt", ".srt", ".ass"])

    boton_convertir = gr.Button("Convertir", variant="primary")
    estado_output = gr.Textbox(label="Estado", interactive=False)

    tabla_output = gr.Dataframe(
        headers=["TIME CODE", "PERSONAJE", "DIÁLOGO"],
        datatype=["str", "str", "str"],
        row_count=(0, "dynamic"),
        column_count=(3, "fixed"),
        interactive=True,
        label="Revisa y corrige aquí antes de exportar (doble clic en una celda para editarla)",
        wrap=True,
        type="array",
    )

    boton_convertir.click(
        fn=procesar,
        inputs=[texto_input, archivo_input],
        outputs=[tabla_output, estado_output],
    )

    gr.Markdown("---")

    with gr.Row():
        nombre_salida_input = gr.Textbox(label="Nombre del archivo de salida", value="guion_3_columnas.docx")

    mmss_input = gr.Checkbox(
        label="TIME CODE en formato MM:SS (convención de doblaje)",
        value=False,
        info="Solo tiene efecto si el TIME CODE viene de un .srt/.ass (con libreto tradicional queda vacío "
             "de todas formas). Ej: 0114 = 1 min 14 s, en vez de 00:01:14,300.",
    )

    boton_exportar = gr.Button("Exportar a Word", variant="primary")
    estado_exportar = gr.Textbox(label="Estado de exportación", interactive=False)

    gr.HTML('<span class="insignia insignia-docx">📄 WORD (3 columnas)</span>')
    archivo_output = gr.File(label="Documento generado")

    boton_exportar.click(
        fn=exportar,
        inputs=[tabla_output, nombre_salida_input, mmss_input],
        outputs=[archivo_output, estado_exportar],
    )

if __name__ == "__main__":
    demo.launch(css=CSS_INSIGNIAS)
