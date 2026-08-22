# -*- coding: utf-8 -*-
"""
convertir_libreto.py

Convierte distintos formatos de entrada a una tabla simple de 3 columnas:

    TIME CODE  |  PERSONAJE  |  DIÁLOGO

Soporta cuatro formatos de entrada (detectados automáticamente por contenido):

1. Libreto tradicional (bloques de escena numerados con timecode de referencia
   entre paréntesis, líneas de PERSONAJE + DIÁLOGO en dos columnas por
   tabulador o espacios). TIME CODE queda VACÍO — eso lo calcula después
   alinear_timecodes.py a partir del video con Whisper.

2. Guion numerado tipo screenplay: escenas como "1)  LOCATION - / EXT. DAY",
   y cada línea de diálogo como "N.  PERSONAJE" seguido del diálogo en la
   línea de abajo (en vez de en la misma línea). Común en guiones originales
   en inglés (as-recorded). TIME CODE también queda VACÍO.

3. Subtítulos .srt existentes. TIME CODE se llena con el tiempo real de
   inicio de cada línea (ya viene en el archivo). PERSONAJE queda VACÍO
   para revisar a mano con el video en pantalla — esto evita copiar bloques
   de texto y calcular timecodes de nuevo, solo hace falta asignar quién
   habla en cada línea.

4. Subtítulos .ass existentes (fansubs). Igual que .srt: TIME CODE real,
   PERSONAJE vacío para revisión manual, limpia las etiquetas de estilo
   ({\\...}) y los saltos de línea propios del formato.

Uso por línea de comandos:
    python convertir_libreto.py --entrada libreto.txt --salida guion_3_columnas.docx
    python convertir_libreto.py --entrada subtitulos.srt --salida guion_3_columnas.docx
    python convertir_libreto.py --entrada fansub.ass --salida guion_3_columnas.docx
"""

import argparse
import re

from docx import Document
from docx.shared import Cm

# Detecta líneas de marca de escena como "1 (10:00:02:00)" — solo se usan
# para saber dónde termina el encabezado (título, número de episodio, etc.);
# no se incluyen en la tabla de salida.
PATRON_ESCENA = re.compile(r"^\s*\d+\s*\([\d:]+\)\s*$")

PATRON_TIEMPO_SRT = re.compile(r"(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})")


def formatear_mmss(tc: str):
    """
    Convierte un timecode 'HH:MM:SS,mmm' (el que traen los .srt/.ass importados)
    al formato corto usado en doblaje: 'MMSS' (minutos y segundos, 2 dígitos
    cada uno, sin separadores ni milisegundos). Ej: '00:01:14,300' -> '0114'.
    Si viene vacío (libreto tradicional, sin timecode todavía) lo deja vacío.
    Si el formato no se puede interpretar, lo deja tal cual sin inventar nada.
    """
    tc = (tc or "").strip()
    if not tc or "?" in tc:
        return tc
    try:
        horas_min_seg, ms = tc.split(",")
        horas, minutos, segundos = horas_min_seg.split(":")
        segundos_totales = int(horas) * 3600 + int(minutos) * 60 + int(segundos) + int(ms) / 1000
    except (ValueError, IndexError):
        return tc
    m = int(segundos_totales // 60)
    s = int(segundos_totales % 60)
    return f"{m:02d}{s:02d}"


def separar_personaje_dialogo(linea: str):
    """
    Intenta separar una línea de texto en (personaje, dialogo).
    1) Si hay un tabulador, separa ahí (más confiable — así se pega texto
       copiado de un documento con columnas alineadas por tabulación).
    2) Si no hay tabulador, separa en la primera racha de 2+ espacios
       seguidos (típico cuando las columnas se alinearon con espacios).
    3) Si no se puede separar de ninguna forma, devuelve (None, línea)
       para marcarla y que se revise a mano.
    """
    if "\t" in linea:
        personaje, dialogo = linea.split("\t", 1)
        return personaje.strip(), dialogo.strip()

    partes = re.split(r" {2,}", linea, maxsplit=1)
    if len(partes) == 2 and partes[0].strip():
        return partes[0].strip(), partes[1].strip()

    return None, linea.strip()


def parsear_libreto(texto: str):
    """
    Devuelve una lista de dicts: {"timecode": "", "personaje": str, "dialogo": str, "revisar": bool}

    Se ignoran:
    - Todo lo que aparece ANTES de la primera marca de escena (título de la
      serie, número de episodio, etc.)
    - Las propias líneas de marca de escena ("N (timecode)")
    - Líneas en blanco
    """
    lineas = texto.replace("\ufeff", "").splitlines()
    filas = []
    encontro_primera_escena = False

    for linea in lineas:
        linea = linea.rstrip()
        if not linea.strip():
            continue

        if PATRON_ESCENA.match(linea):
            encontro_primera_escena = True
            continue

        if not encontro_primera_escena:
            # Todavía en el encabezado (título, "EPISODE 411", etc.)
            continue

        personaje, dialogo = separar_personaje_dialogo(linea)
        if personaje is None:
            filas.append({"timecode": "", "personaje": "?", "dialogo": dialogo, "revisar": True})
        else:
            filas.append({"timecode": "", "personaje": personaje, "dialogo": dialogo, "revisar": False})

    return filas


# Escena tipo "1)  CONSTRUCTION SITE - / EXT. DAY" (paréntesis de cierre ")")
PATRON_ESCENA_NUMERADA = re.compile(r"^\s*\d+\)\s+.+$")

# Palabras típicas de encabezado de escena, por si Word le quitó la numeración
# automática y solo queda el texto (ej. "CONSTRUCTION SITE - / EXT. DAY").
PATRON_ENCABEZADO_ESCENA_SIN_NUM = re.compile(r"\b(EXT\.|INT\.)\b", re.IGNORECASE)

# Cue de personaje: nombre en MAYÚSCULAS solo en su línea, con número opcional
# al inicio ("1.  FRANK") y timecode opcional al final ("FRANK (10:00:00:00)").
# El número es opcional a propósito: si el guion viene de un Word con numeración
# automática (listas numeradas), el texto real del párrafo NO incluye el número
# — Word solo lo dibuja, no forma parte del contenido — así que el patrón debe
# poder reconocer el cue aunque el "1." no esté presente en el texto extraído.
PATRON_CUE_PERSONAJE = re.compile(
    r"^\s*(?:\d+[.\)]\s*)?"
    r"([A-ZÁÉÍÓÚÑÜ][A-ZÁÉÍÓÚÑÜ'\-]*(?:\s+[A-ZÁÉÍÓÚÑÜ][A-ZÁÉÍÓÚÑÜ'\-]*){0,3})"
    r"(?:\s*\([\d:]+\))?\s*$",
    re.MULTILINE,
)


def _es_guion_numerado(texto: str) -> bool:
    """
    Detecta si el texto usa el formato de cues '(N.) PERSONAJE' en su propia
    línea. Pide al menos 2 coincidencias para evitar falsos positivos con una
    sola línea corta en mayúsculas que aparezca de casualidad en otro formato.
    """
    coincidencias = PATRON_CUE_PERSONAJE.findall(texto)
    return len(coincidencias) >= 2


def parsear_guion_numerado(texto: str):
    """
    Parsea un guion tipo screenplay donde cada línea de diálogo tiene el
    personaje en su PROPIA línea (con o sin número delante — ver nota en
    PATRON_CUE_PERSONAJE sobre numeración automática de Word), a veces con
    un timecode de referencia entre paréntesis que se ignora, y el diálogo
    en la(s) línea(s) siguiente(s), hasta la próxima cue o encabezado de escena.

    Los encabezados de escena ("1)  LOCATION - / EXT. DAY", con o sin el "1)")
    se ignoran, igual que cualquier texto antes de la primera cue de personaje.
    Las acotaciones entre paréntesis dentro del diálogo (ej. "(Whisper) OK.")
    se conservan tal cual, como parte del texto de DIÁLOGO.
    """
    lineas = texto.replace("\ufeff", "").splitlines()
    filas = []
    personaje_actual = None
    buffer_dialogo = []

    def cerrar_entrada():
        if personaje_actual is not None and buffer_dialogo:
            dialogo = " ".join(buffer_dialogo).strip()
            if dialogo:
                filas.append({"timecode": "", "personaje": personaje_actual, "dialogo": dialogo, "revisar": False})

    for linea in lineas:
        linea_limpia = linea.strip()
        if not linea_limpia:
            continue

        es_encabezado = PATRON_ESCENA_NUMERADA.match(linea) or PATRON_ENCABEZADO_ESCENA_SIN_NUM.search(linea)
        if es_encabezado:
            cerrar_entrada()
            personaje_actual = None
            buffer_dialogo = []
            continue

        cue = PATRON_CUE_PERSONAJE.match(linea)
        if cue:
            cerrar_entrada()
            personaje_actual = cue.group(1).strip()
            buffer_dialogo = []
            continue

        if personaje_actual is not None:
            buffer_dialogo.append(linea_limpia)

    cerrar_entrada()
    return filas


def parsear_srt(texto: str):
    """
    Devuelve una lista de dicts: {"timecode": "HH:MM:SS,mmm", "personaje": "", "dialogo": str, "revisar": False}
    a partir de un archivo .srt. PERSONAJE queda vacío a propósito, para
    asignarlo a mano viendo el video (esta herramienta no adivina quién habla).
    """
    bloques = re.split(r"\n\s*\n", texto.replace("\ufeff", "").strip())
    filas = []

    for bloque in bloques:
        lineas = [l for l in bloque.splitlines() if l.strip()]
        if not lineas:
            continue

        idx = 1 if lineas[0].strip().isdigit() else 0
        if idx >= len(lineas):
            continue

        match = PATRON_TIEMPO_SRT.search(lineas[idx])
        if not match:
            match = PATRON_TIEMPO_SRT.search(lineas[0])
            idx = 0
        if not match:
            continue

        inicio = match.group(1).replace(".", ",")
        texto_dialogo = " ".join(lineas[idx + 1:]).strip()
        texto_dialogo = re.sub(r"<[^>]+>", "", texto_dialogo)  # limpia tags tipo <i>...</i>

        if texto_dialogo:
            filas.append({"timecode": inicio, "personaje": "", "dialogo": texto_dialogo, "revisar": False})

    return filas


def _convertir_tiempo_ass(t: str):
    """Convierte el formato de tiempo de .ass (H:MM:SS.cc, centésimas) a 'HH:MM:SS,mmm'."""
    m = re.match(r"(\d+):(\d{2}):(\d{2})\.(\d{2})", t.strip())
    if not m:
        return t.strip()
    h, mi, s, cs = m.groups()
    ms = int(cs) * 10
    return f"{int(h):02d}:{mi}:{s},{ms:03d}"


def parsear_ass(texto: str):
    """
    Devuelve una lista de dicts a partir de un archivo .ass (formato de
    fansubs). PERSONAJE queda vacío a propósito, aunque el formato .ass
    tiene un campo "Name" (a veces usado para el personaje) — se ignora
    deliberadamente para que la revisión manual sea consistente con .srt.
    """
    filas = []
    en_eventos = False
    campos = None

    for linea in texto.replace("\ufeff", "").splitlines():
        linea = linea.strip()
        if not linea:
            continue

        if linea.lower().startswith("[events]"):
            en_eventos = True
            continue
        if linea.startswith("[") and linea.lower() != "[events]":
            en_eventos = False
            continue
        if not en_eventos:
            continue

        if linea.lower().startswith("format:"):
            campos = [c.strip().lower() for c in linea[len("format:"):].split(",")]
            continue

        if linea.lower().startswith("dialogue:") and campos:
            resto = linea[len("dialogue:"):].strip()
            partes = resto.split(",", len(campos) - 1)
            if len(partes) < len(campos):
                continue
            valores = dict(zip(campos, partes))

            inicio_ass = valores.get("start", "").strip()
            texto_dialogo = valores.get("text", "").strip()
            texto_dialogo = re.sub(r"\{[^}]*\}", "", texto_dialogo)  # limpia tags de estilo {\...}
            texto_dialogo = texto_dialogo.replace("\\N", " ").replace("\\n", " ").strip()

            if inicio_ass and texto_dialogo:
                filas.append({
                    "timecode": _convertir_tiempo_ass(inicio_ass),
                    "personaje": "",
                    "dialogo": texto_dialogo,
                    "revisar": False,
                })

    return filas


def detectar_y_parsear(texto: str):
    """
    Detecta automáticamente el formato del texto (libreto tradicional, guion
    numerado tipo screenplay, .srt, o .ass) y llama al parser correspondiente.
    """
    texto_muestra = texto[:2000]
    if "[Script Info]" in texto_muestra or re.search(r"^\s*\[Events\]", texto_muestra, re.MULTILINE) \
            or re.search(r"^Dialogue:", texto_muestra, re.MULTILINE):
        return parsear_ass(texto), "ass"

    if PATRON_TIEMPO_SRT.search(texto_muestra):
        return parsear_srt(texto), "srt"

    if _es_guion_numerado(texto_muestra):
        return parsear_guion_numerado(texto), "guion_numerado"

    return parsear_libreto(texto), "libreto"


def generar_docx_3_columnas(filas, ruta_salida: str, formato_tc: str = "completo"):
    """
    Genera un Word con tabla TIME CODE | PERSONAJE | DIÁLOGO.

    formato_tc="completo" (default): TIME CODE tal cual viene (HH:MM:SS,mmm si
        es de un .srt/.ass, o vacío si es de un libreto tradicional).
    formato_tc="mmss": convierte el TIME CODE al formato corto de doblaje
        (MMSS, sin separadores ni milisegundos). Si viene vacío, se queda vacío.
    """
    doc = Document()
    doc.add_heading("Guion (formato 3 columnas)", level=1)

    tabla = doc.add_table(rows=1, cols=3)
    tabla.style = "Table Grid"
    encabezados = tabla.rows[0].cells
    encabezados[0].text = "TIME CODE"
    encabezados[1].text = "PERSONAJE"
    encabezados[2].text = "DIÁLOGO"
    for celda in encabezados:
        for p in celda.paragraphs:
            for run in p.runs:
                run.bold = True

    tabla.columns[0].width = Cm(3)
    tabla.columns[1].width = Cm(3.5)
    tabla.columns[2].width = Cm(10)

    for fila in filas:
        celdas = tabla.add_row().cells
        timecode = fila.get("timecode", "")
        celdas[0].text = formatear_mmss(timecode) if formato_tc == "mmss" else timecode
        celdas[1].text = fila["personaje"]
        celdas[2].text = fila["dialogo"]

    doc.save(ruta_salida)


def main():
    parser = argparse.ArgumentParser(description="Convierte un libreto/subtítulos a formato de 3 columnas.")
    parser.add_argument("--entrada", required=True, help="Ruta a un .txt (libreto), .srt o .ass")
    parser.add_argument("--salida", default="guion_3_columnas.docx", help="Ruta del .docx de salida")
    parser.add_argument("--formato_tc", default="completo", choices=["completo", "mmss"],
                         help="Formato del TIME CODE en el Word (solo aplica si viene de .srt/.ass): "
                              "'completo' (HH:MM:SS,mmm, default) o 'mmss' (convención de doblaje: MMSS).")
    args = parser.parse_args()

    with open(args.entrada, "r", encoding="utf-8") as f:
        texto = f.read()

    filas, formato = detectar_y_parsear(texto)
    revisar = sum(1 for f in filas if f["revisar"])
    print(f"Formato detectado: {formato}. Se detectaron {len(filas)} líneas ({revisar} marcadas para revisar).")
    if formato in ("srt", "ass"):
        print("TIME CODE tomado del archivo de subtítulos. PERSONAJE queda vacío para asignar a mano.")

    generar_docx_3_columnas(filas, args.salida, formato_tc=args.formato_tc)
    print(f"Documento generado: {args.salida}")


if __name__ == "__main__":
    main()
