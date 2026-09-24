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

5. Guion "as broadcast": "PERSONAJE:   diálogo" en la misma línea, omitiendo
   las anotaciones para traductores entre paréntesis.

6. Un Word que ya trae el guion en tabla (por ejemplo los ASR de CaptionMax,
   "# | Timecode | Character | Dialogue"): se toman solo esas tres columnas.

La salida puede ser Word (.docx) o Excel (.xlsx).

Uso por línea de comandos:
    python convertir_libreto.py --entrada libreto.txt --salida guion_3_columnas.docx
    python convertir_libreto.py --entrada Saltix_23_ASR.docx --salida guion_3_columnas.xlsx
    python convertir_libreto.py --entrada subtitulos.srt --salida guion_3_columnas.docx
    python convertir_libreto.py --entrada fansub.ass --salida guion_3_columnas.docx
"""

import argparse
import re
import unicodedata

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


# Versión más flexible para PARSEAR (no para detectar el formato): acepta nombres
# en mayúsculas/minúsculas ("Gonzo"), listas ("PAM, HAMMER, HULK") y hasta 8
# palabras. Como también podría coincidir con un diálogo corto, solo se toma
# como cue si la línea anterior está en blanco (el diálogo va pegado a su cue).
PATRON_CUE_FLEXIBLE = re.compile(
    r"^\s*(?:\d+[.\)]\s*)?"
    r"([A-ZÁÉÍÓÚÑÜ][\wÁÉÍÓÚÑÜáéíóúñü'’\-]*(?:[ ,]+[A-ZÁÉÍÓÚÑÜ][\wÁÉÍÓÚÑÜáéíóúñü'’\-]*){0,7})"
    r"(?:\s*\([\d:]+\))?\s*$"
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

    precedida_por_blanco = True
    for linea in lineas:
        linea_limpia = linea.strip()
        if not linea_limpia:
            precedida_por_blanco = True
            continue
        despues_de_blanco, precedida_por_blanco = precedida_por_blanco, False

        es_encabezado = PATRON_ESCENA_NUMERADA.match(linea) or PATRON_ENCABEZADO_ESCENA_SIN_NUM.search(linea)
        if es_encabezado:
            cerrar_entrada()
            personaje_actual = None
            buffer_dialogo = []
            continue

        cue = PATRON_CUE_PERSONAJE.match(linea) or (despues_de_blanco and PATRON_CUE_FLEXIBLE.match(linea))
        if cue:
            cerrar_entrada()
            personaje_actual = cue.group(1).strip()
            buffer_dialogo = []
            continue

        if personaje_actual is not None:
            buffer_dialogo.append(linea_limpia)

    cerrar_entrada()
    return filas


# Guion "as broadcast": "PERSONAJE:   diálogo" en la misma línea (dos puntos y
# 2+ espacios o tabulador), o "PERSONAJE<tab>diálogo" sin dos puntos.
PATRON_CUE_DOS_PUNTOS = re.compile(r"^([A-ZÁÉÍÓÚÑÜ][A-ZÁÉÍÓÚÑÜ0-9 .'\-]{0,40}):(?:\s{2,}|\t)(.*)$")
PATRON_CUE_TAB_SIN_DOS_PUNTOS = re.compile(r"^([A-ZÁÉÍÓÚÑÜ][A-ZÁÉÍÓÚÑÜ0-9 .'\-]{0,40})\t(.*)$")


def _es_guion_broadcast(texto: str) -> bool:
    return sum(1 for l in texto.splitlines() if PATRON_CUE_DOS_PUNTOS.match(l)) >= 2


def parsear_guion_broadcast(texto: str):
    """
    Parsea un guion "as broadcast": cada línea empieza con "PERSONAJE:" y el
    diálogo sigue en la misma línea (y puede continuar en las de abajo).

    Se omiten:
    - Las anotaciones para traductores: párrafos entre paréntesis que vienen
      DESPUÉS de una línea en blanco (pueden ocupar varias líneas). Un
      paréntesis pegado al diálogo, sin línea en blanco antes, sí se conserva.
    - Las líneas todo en MAYÚSCULAS sin dos puntos (encabezados de escena,
      títulos): cierran la entrada actual.
    """
    lineas = texto.replace("﻿", "").splitlines()
    filas = []
    personaje_actual = None
    buffer_dialogo = []
    en_anotacion = False
    precedida_por_blanco = True

    def cerrar_entrada():
        if personaje_actual is not None and buffer_dialogo:
            dialogo = re.sub(r"\s+", " ", " ".join(buffer_dialogo).replace(" ", " ")).strip()
            if dialogo:
                filas.append({"timecode": "", "personaje": personaje_actual, "dialogo": dialogo, "revisar": False})

    for linea_cruda in lineas:
        linea = linea_cruda.strip()
        if not linea:
            precedida_por_blanco = True
            continue

        cue = PATRON_CUE_DOS_PUNTOS.match(linea_cruda) or PATRON_CUE_TAB_SIN_DOS_PUNTOS.match(linea_cruda)

        if en_anotacion and not cue:
            if linea.endswith(")"):
                en_anotacion = False
            precedida_por_blanco = False
            continue
        en_anotacion = False

        if cue:
            cerrar_entrada()
            personaje_actual = cue.group(1).strip()
            resto = cue.group(2).strip()
            buffer_dialogo = [resto] if resto else []
            precedida_por_blanco = False
            continue

        if linea.startswith("(") and buffer_dialogo and precedida_por_blanco:
            if not linea.endswith(")"):
                en_anotacion = True
            precedida_por_blanco = False
            continue

        if linea == linea.upper() and linea != linea.lower():
            cerrar_entrada()
            personaje_actual = None
            buffer_dialogo = []
            precedida_por_blanco = False
            continue

        if personaje_actual is not None:
            buffer_dialogo.append(linea)
        precedida_por_blanco = False

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
    texto_muestra = texto[:6000]
    if "[Script Info]" in texto_muestra or re.search(r"^\s*\[Events\]", texto_muestra, re.MULTILINE) \
            or re.search(r"^Dialogue:", texto_muestra, re.MULTILINE):
        return parsear_ass(texto), "ass"

    if PATRON_TIEMPO_SRT.search(texto_muestra):
        return parsear_srt(texto), "srt"

    if _es_guion_broadcast(texto_muestra):
        return parsear_guion_broadcast(texto), "guion_broadcast"

    if _es_guion_numerado(texto_muestra):
        return parsear_guion_numerado(texto), "guion_numerado"

    return parsear_libreto(texto), "libreto"


def _normalizar_encabezado(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.upper()).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^A-Z]", "", texto)


def _columnas_de_encabezado(celdas):
    """Índices (tc, personaje, dialogo) según los encabezados; None si no es una tabla de guion."""
    tc = personaje = dialogo = None
    for i, texto in enumerate(celdas):
        h = _normalizar_encabezado(texto)
        if personaje is None and any(k in h for k in ("PERSONAJE", "CHARACTER", "PERSONNAGE", "SPEAKER")):
            personaje = i
        elif dialogo is None and any(k in h for k in ("DIALOG", "TEXTO", "TEXT")):
            dialogo = i
        elif tc is None and (h in ("TC", "TCIN", "IN", "TIEMPO") or h.startswith("TIMECODE") or h == "TIME"):
            tc = i
    if personaje is None or dialogo is None:
        return None
    return tc, personaje, dialogo


def leer_tablas_docx(doc):
    """
    Lee un Word que YA trae el guion en tabla (por ejemplo los ASR de CaptionMax:
    "# | Timecode | Character | Dialogue"). Toma solo TIME CODE, PERSONAJE y
    DIÁLOGO según los encabezados; las demás columnas (el "#" con la numeración
    1, 2, 3…, notas, etc.) se descartan. Devuelve [] si no hay una tabla así.
    """
    filas = []
    for tabla in doc.tables:
        for n_encabezado, fila in enumerate(tabla.rows[:3]):
            columnas = _columnas_de_encabezado([c.text for c in fila.cells])
            if columnas:
                break
        else:
            continue
        tc, personaje, dialogo = columnas
        for fila in tabla.rows[n_encabezado + 1:]:
            celdas = fila.cells
            if max(c for c in columnas if c is not None) >= len(celdas):
                continue
            texto_pj = celdas[personaje].text.strip()
            texto_dlg = re.sub(r"\s+", " ", celdas[dialogo].text).strip()
            if not texto_pj and not texto_dlg:
                continue
            filas.append({
                "timecode": celdas[tc].text.strip() if tc is not None else "",
                "personaje": texto_pj,
                "dialogo": texto_dlg,
                "revisar": not texto_pj,
            })
    return filas


def _tipo_estilo(nombre: str):
    """Clasifica un estilo de párrafo de guion (en inglés, francés o español)."""
    n = unicodedata.normalize("NFKD", (nombre or "").lower()).encode("ascii", "ignore").decode("ascii")
    if any(k in n for k in ("personnage", "character", "personaje")):
        return "cue"
    if any(k in n for k in ("dialogue", "dialogo")):
        return "dialogo"
    if any(k in n for k in ("parenthe", "acotacion")):
        return "acotacion"
    if any(k in n for k in ("scene", "sequence", "slugline", "escena")):
        return "escena"
    if any(k in n for k in ("action", "accion")):
        return "accion"
    return None


# Timecodes de referencia y "(cont'd)" que acompañan al nombre en el cue
PATRON_RESTO_CUE = re.compile(r"\((?:\d{1,2}:){2,3}\d{1,2}\)|\((?:cont'?d|cont’d|suite|cont\.?)\)", re.IGNORECASE)


def leer_guion_con_estilos(doc):
    """
    Guiones de Word hechos con estilos de párrafo (Personnage / Dialogue /
    Parenthèse / Scene Heading…), como los ASREC de Foot 2 Rue. Es la forma más
    confiable de leerlos: no depende de mayúsculas ni de líneas en blanco.
    Los nombres se pasan a MAYÚSCULAS (el estilo de personaje ya los muestra así en Word).
    Devuelve [] si el documento no usa estos estilos.
    """
    parrafos = [p for p in doc.paragraphs if p.text.strip()]
    if sum(1 for p in parrafos if _tipo_estilo(p.style.name) == "cue") < 5:
        return []

    filas = []
    personaje, buffer = None, []

    def cerrar():
        if personaje and buffer:
            filas.append({"timecode": "", "personaje": personaje,
                          "dialogo": re.sub(r"\s+", " ", " ".join(buffer)).strip(), "revisar": False})

    for p in parrafos:
        tipo = _tipo_estilo(p.style.name)
        texto = p.text.strip()
        if tipo == "cue":
            cerrar()
            personaje = re.sub(r"\s+", " ", PATRON_RESTO_CUE.sub("", texto)).strip().upper()
            buffer = []
        elif tipo in ("escena", "accion"):
            cerrar()
            personaje, buffer = None, []
        elif personaje:  # diálogo, acotación, o "Normal" con sangría dentro del bloque
            buffer.append(texto)
    cerrar()
    return filas


def _texto_docx(doc):
    """Texto del Word en orden: párrafos, y las filas de tablas con sus celdas separadas por tabulador."""
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    lineas = []
    for elemento in doc.element.body.iterchildren():
        if elemento.tag.endswith("}p"):
            lineas.append(Paragraph(elemento, doc).text)
        elif elemento.tag.endswith("}tbl"):
            for fila in Table(elemento, doc).rows:
                celdas = []
                for c in fila.cells:  # las celdas combinadas se repiten: se dejan una vez
                    if not celdas or c._tc is not celdas[-1]._tc:
                        celdas.append(c)
                lineas.append("\t".join(c.text.strip() for c in celdas))
    return "\n".join(lineas)


def leer_xlsx(ruta: str):
    """Lee la primera hoja de un Excel con columnas PERSONAJE y DIÁLOGO (y T.C. si la hay)."""
    from openpyxl import load_workbook

    libro = load_workbook(ruta, read_only=True, data_only=True)
    for hoja in libro.worksheets:
        filas_hoja = [["" if c is None else str(c) for c in f] for f in hoja.iter_rows(values_only=True)]
        for n, encabezado in enumerate(filas_hoja[:3]):
            columnas = _columnas_de_encabezado(encabezado)
            if columnas:
                break
        else:
            continue
        tc, personaje, dialogo = columnas
        filas = []
        for f in filas_hoja[n + 1:]:
            f = f + [""] * (max(c for c in columnas if c is not None) + 1 - len(f))
            if not f[personaje].strip() and not f[dialogo].strip():
                continue
            filas.append({"timecode": f[tc].strip() if tc is not None else "", "personaje": f[personaje].strip(),
                          "dialogo": re.sub(r"\s+", " ", f[dialogo]).strip(), "revisar": not f[personaje].strip()})
        return filas
    return []


def leer_archivo(ruta: str):
    """Convierte un .docx, .xlsx, .txt, .srt o .ass en (filas, formato)."""
    if ruta.lower().endswith(".xlsx"):
        return leer_xlsx(ruta), "tabla_excel"
    if ruta.lower().endswith(".docx"):
        doc = Document(ruta)
        filas = leer_tablas_docx(doc)
        if filas:
            return filas, "tabla_word"
        filas = leer_guion_con_estilos(doc)
        if filas:
            return filas, "guion_estilos"
        return detectar_y_parsear(_texto_docx(doc))
    with open(ruta, "r", encoding="utf-8-sig", errors="ignore") as f:
        return detectar_y_parsear(f.read())


def _columnas_salida(columna_original):
    """Encabezados y claves de las columnas: T.C. | PERSONAJE | [ORIGINAL |] DIÁLOGO."""
    if columna_original:
        return ["T.C.", "PERSONAJE", "ORIGINAL", "DIÁLOGO"], ["timecode", "personaje", "original", "dialogo"]
    return ["T.C.", "PERSONAJE", "DIÁLOGO"], ["timecode", "personaje", "dialogo"]


def _valor_tc(fila, formato_tc):
    timecode = fila.get("timecode", "")
    return formatear_mmss(timecode) if formato_tc == "mmss" else timecode


def generar_xlsx_3_columnas(filas, ruta_salida: str, formato_tc: str = "completo", columna_original=False):
    """
    Genera un Excel con las columnas T.C. | PERSONAJE | DIÁLOGO (sin columnas extra).
    columna_original=True agrega ORIGINAL antes de DIÁLOGO (para revisar traducciones).
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    encabezados, claves = _columnas_salida(columna_original)
    libro = Workbook()
    hoja = libro.active
    hoja.title = "Guion"
    hoja.append(encabezados)
    for celda in hoja[1]:
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = PatternFill("solid", fgColor="1F3A5F")

    for fila in filas:
        hoja.append([_valor_tc(fila, formato_tc) if c == "timecode" else fila.get(c, "") for c in claves])

    for celdas in hoja.iter_rows(min_row=2):
        celdas[0].number_format = "@"  # texto: que Excel no convierta "0114" en 114
        for celda in celdas[2:]:
            celda.alignment = Alignment(wrap_text=True, vertical="top")
    anchos = [14, 22] + ([60, 60] if columna_original else [90])
    for letra, ancho in zip("ABCD", anchos):
        hoja.column_dimensions[letra].width = ancho
    hoja.freeze_panes = "A2"
    libro.save(ruta_salida)


def generar_docx_3_columnas(filas, ruta_salida: str, formato_tc: str = "completo", columna_original=False):
    """
    Genera un Word con tabla T.C. | PERSONAJE | DIÁLOGO.

    formato_tc="completo" (default): TIME CODE tal cual viene (HH:MM:SS,mmm si
        es de un .srt/.ass, o vacío si es de un libreto tradicional).
    formato_tc="mmss": convierte el TIME CODE al formato corto de doblaje
        (MMSS, sin separadores ni milisegundos). Si viene vacío, se queda vacío.
    columna_original=True agrega ORIGINAL antes de DIÁLOGO (para revisar traducciones).
    """
    encabezados_texto, claves = _columnas_salida(columna_original)
    doc = Document()
    doc.add_heading("Guion (formato 3 columnas)", level=1)

    tabla = doc.add_table(rows=1, cols=len(claves))
    tabla.style = "Table Grid"
    for celda, texto in zip(tabla.rows[0].cells, encabezados_texto):
        celda.text = texto
        for p in celda.paragraphs:
            for run in p.runs:
                run.bold = True

    anchos = [Cm(3), Cm(3.5)] + ([Cm(6), Cm(6)] if columna_original else [Cm(10)])
    for columna, ancho in zip(tabla.columns, anchos):
        columna.width = ancho

    for fila in filas:
        celdas = tabla.add_row().cells
        for celda, clave in zip(celdas, claves):
            celda.text = _valor_tc(fila, formato_tc) if clave == "timecode" else fila.get(clave, "")

    doc.save(ruta_salida)


def main():
    parser = argparse.ArgumentParser(description="Convierte un libreto/subtítulos a formato de 3 columnas.")
    parser.add_argument("--entrada", required=True, help="Ruta a un .docx, .txt (libreto), .srt o .ass")
    parser.add_argument("--salida", default="guion_3_columnas.docx",
                         help="Ruta de salida: .docx (Word) o .xlsx (Excel)")
    parser.add_argument("--formato_tc", default="completo", choices=["completo", "mmss"],
                         help="Formato del TIME CODE en el Word (solo aplica si viene de .srt/.ass): "
                              "'completo' (HH:MM:SS,mmm, default) o 'mmss' (convención de doblaje: MMSS).")
    args = parser.parse_args()

    filas, formato = leer_archivo(args.entrada)
    revisar = sum(1 for f in filas if f["revisar"])
    print(f"Formato detectado: {formato}. Se detectaron {len(filas)} líneas ({revisar} marcadas para revisar).")
    if formato in ("srt", "ass"):
        print("TIME CODE tomado del archivo de subtítulos. PERSONAJE queda vacío para asignar a mano.")

    if args.salida.lower().endswith(".xlsx"):
        generar_xlsx_3_columnas(filas, args.salida, formato_tc=args.formato_tc)
    else:
        generar_docx_3_columnas(filas, args.salida, formato_tc=args.formato_tc)
    print(f"Documento generado: {args.salida}")


if __name__ == "__main__":
    main()
