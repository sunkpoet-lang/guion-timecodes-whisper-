"""
Alinea un guion existente (Word, con columnas o líneas PERSONAJE / DIÁLOGO)
con los timecodes que genera Whisper al transcribir el video/audio original.

No vuelve a transcribir "desde cero": usa lo que Whisper detecta solo para
ubicar EN QUÉ MOMENTO se dice cada línea que tú ya tienes escrita, y así
conserva tus diálogos y asignaciones de personaje tal cual están.

------------------------------------------------------------------
REQUISITOS (instalar una sola vez):

    pip install faster-whisper python-docx tqdm

    También necesitas ffmpeg instalado y accesible desde la terminal:
      - Windows: https://ffmpeg.org/download.html (o "choco install ffmpeg")
      - Mac:     brew install ffmpeg
      - Linux:   sudo apt install ffmpeg

    Para usar GPU (recomendado si tienes NVIDIA, como una RTX 2060):
      El script intenta usar CUDA automáticamente y si falla cae a CPU solo.
      Si te da error de cuDNN/CUDA al cargar el modelo, instala:
          pip install nvidia-cudnn-cu12 nvidia-cublas-cu12
      Con 6GB de VRAM, el modelo "medium" corre cómodo; "large-v3" puede
      quedarse justo de memoria — si da error, baja a "medium".

------------------------------------------------------------------
USO:

    python alinear_timecodes.py --video "mi_video.mp4" --guion "mi_guion.docx" --salida "guion_con_tc.docx"

Parámetros opcionales:
    --modelo         tiny | base | small | medium | large-v3   (default: medium)
                      Modelos más grandes = más precisos pero más lentos.
                      Si no tienes GPU y el video es largo, prueba "small" primero.

    --idioma_audio    Idioma real que se habla en el video (default: es).
                      Debe coincidir con el idioma del AUDIO, no con el del guion.
                      Ejemplo: si la caricatura tiene el audio en inglés (aunque tu
                      guion esté traducido al español), usa --idioma_audio en

    --modo            texto | proporcional   (default: texto)
                      "texto": compara el texto del guion contra lo que transcribe
                          Whisper. Úsalo SOLO cuando el guion está en el MISMO idioma
                          que el audio del video.
                      "proporcional": no compara texto, reparte las líneas del guion
                          a lo largo del tiempo de habla detectado por Whisper, según
                          la duración de cada línea. Úsalo cuando el guion está
                          TRADUCIDO a un idioma distinto al del audio (por ejemplo,
                          audio en inglés y guion en español) — en ese caso comparar
                          texto no sirve porque están en idiomas distintos.
                          Es menos exacto que "texto": revisa el resultado con más
                          cuidado, sobre todo en escenas con pausas largas o silencios.

    --exportar_srt     Si se indica, además del .docx genera un archivo .srt (subtítulos)
                       con el mismo nombre que --salida. Reutiliza los timecodes ya
                       calculados: cada línea dura hasta que empieza la siguiente (con un
                       pequeño margen), con una duración mínima y máxima razonable. Las
                       líneas sin timecode confiable (??:??:??,???) se omiten del .srt.

    --tarea            transcribir | traducir_a_ingles   (default: transcribir)
                       "transcribir": Whisper escribe lo que escucha, en el idioma del
                           audio (--idioma_audio).
                       "traducir_a_ingles": Whisper traduce directo al inglés mientras
                           transcribe. Solo traduce A INGLÉS (limitación del modelo, no
                           hay opción de traducir a español ni a otro idioma). Útil sobre
                           todo en el modo SIN guion (ver --guion), para generar
                           subtítulos en inglés a partir de audio en japonés u otro
                           idioma, sin necesitar una traducción humana previa.

------------------------------------------------------------------
FORMATO ESPERADO DEL GUION DE ENTRADA (--guion):

Opción A - Tabla de Word con columnas con encabezado que contenga
           "PERSONAJE" (o "CHARACTER") y "DIALOGO"/"DIÁLOGO" (o "DIALOGUE").

Opción B - Párrafos sueltos con formato:
           PERSONAJE: Aquí va el diálogo de esa línea.

El script prueba primero la Opción A (tablas); si no encuentra ninguna
tabla con esas columnas, intenta la Opción B.
"""

import argparse
import os
import re
import difflib
import sys
import unicodedata

from docx import Document
from docx.shared import Cm
from tqdm import tqdm


def formatear_timecode(segundos: float) -> str:
    """Convierte segundos a formato HH:MM:SS,mmm (estilo subtítulo/doblaje)."""
    horas = int(segundos // 3600)
    minutos = int((segundos % 3600) // 60)
    segs = int(segundos % 60)
    ms = int((segundos - int(segundos)) * 1000)
    return f"{horas:02d}:{minutos:02d}:{segs:02d},{ms:03d}"


def normalizar_personaje(personaje: str) -> str:
    """
    Normaliza un nombre de PERSONAJE para comparar sin importar acentos,
    mayúsculas o espacios extra. "TÍTULO", "Título", "titulo " -> "titulo".
    """
    texto = personaje.strip().lower()
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def parsear_tiempo_simple(texto: str) -> float:
    """Convierte 'MM:SS', 'HH:MM:SS' o segundos sueltos ('32', '32.5') a segundos (float)."""
    texto = texto.strip()
    if ":" in texto:
        partes = texto.split(":")
        partes = [float(p) for p in partes]
        if len(partes) == 2:
            return partes[0] * 60 + partes[1]
        if len(partes) == 3:
            return partes[0] * 3600 + partes[1] * 60 + partes[2]
        raise ValueError(f"Formato de tiempo no reconocido: {texto}")
    return float(texto)


def parsear_tc_fijo(cadena: str):
    """
    Convierte una cadena como 'TÍTULO=0:32;TÍTULO EPISÓDICO=0:34' en un diccionario
    {personaje_normalizado: segundos}. Ignora entradas mal formadas en vez de fallar.
    """
    resultado = {}
    if not cadena:
        return resultado
    for parte in cadena.split(";"):
        parte = parte.strip()
        if not parte or "=" not in parte:
            continue
        personaje, tiempo = parte.split("=", 1)
        try:
            segundos = parsear_tiempo_simple(tiempo)
        except ValueError:
            print(f"Aviso: no se pudo interpretar el tiempo en --tc_fijo '{parte}', se ignora.")
            continue
        resultado[normalizar_personaje(personaje)] = segundos
    return resultado


def aplicar_tc_fijo(filas, tc_fijo: dict):
    """
    Reemplaza el TIME CODE de las filas cuyo PERSONAJE coincide con alguna
    clave de tc_fijo (por ejemplo, tarjetas de título sin diálogo hablado,
    que Whisper no puede ubicar porque no hay audio ahí). No toca las demás filas.
    """
    if not tc_fijo:
        return filas
    resultado = []
    for timecode, personaje, dialogo in filas:
        clave = normalizar_personaje(personaje)
        if clave in tc_fijo:
            timecode = formatear_timecode(tc_fijo[clave])
        resultado.append((timecode, personaje, dialogo))
    return resultado


def normalizar(texto: str) -> str:
    """Normaliza texto para poder comparar: minúsculas, sin puntuación, sin espacios extra."""
    texto = texto.lower()
    texto = re.sub(r"[^\w\sáéíóúñü]", "", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def leer_guion(ruta_docx: str):
    """Devuelve una lista de tuplas (personaje, dialogo) leídas del Word existente."""
    doc = Document(ruta_docx)
    filas = []

    # --- Opción A: tablas con columnas PERSONAJE / DIÁLOGO ---
    for tabla in doc.tables:
        if not tabla.rows:
            continue
        encabezados = [c.text.strip().upper() for c in tabla.rows[0].cells]
        idx_personaje = None
        idx_dialogo = None
        for i, h in enumerate(encabezados):
            if "PERSONAJE" in h or "CHARACTER" in h:
                idx_personaje = i
            if "DIALOGO" in h or "DIÁLOGO" in h or "DIALOGUE" in h:
                idx_dialogo = i
        if idx_personaje is not None and idx_dialogo is not None:
            for fila in tabla.rows[1:]:
                personaje = fila.cells[idx_personaje].text.strip()
                dialogo = fila.cells[idx_dialogo].text.strip()
                if dialogo:
                    filas.append((personaje, dialogo))

    if filas:
        return filas

    # --- Opción B: párrafos "PERSONAJE: diálogo" ---
    patron = re.compile(r"^([A-ZÁÉÍÓÚÑÜ0-9 ,._-]{1,30}):\s*(.+)$")
    for p in doc.paragraphs:
        texto = p.text.strip()
        if not texto:
            continue
        match = patron.match(texto)
        if match:
            personaje, dialogo = match.groups()
            filas.append((personaje.strip(), dialogo.strip()))

    return filas


def cargar_modelo_whisper(modelo: str, dispositivo: str = "auto", compute_type: str = "float16"):
    """
    Intenta cargar el modelo en GPU (CUDA) primero, ya que es mucho más rápido.
    Si no hay GPU disponible o falta CUDA/cuDNN, cae automáticamente a CPU.
    dispositivo="cpu" salta directo a CPU (por ejemplo, en Mac o sin GPU NVIDIA).
    """
    from faster_whisper import WhisperModel

    if dispositivo != "cpu":
        try:
            print(f"Cargando modelo Whisper en GPU (CUDA, {compute_type})...")
            model = WhisperModel(modelo, device="cuda", compute_type=compute_type)
            print("GPU detectada correctamente. Usando aceleración CUDA.")
            return model
        except Exception as e:
            print(f"No se pudo usar la GPU ({e}).")
            print("AVISO_CPU: Cambiando a CPU (será más lento, prueba un modelo más chico si tarda mucho).")

    print("Cargando modelo Whisper en CPU...")
    return WhisperModel(modelo, device="cpu", compute_type="int8")


def _transcribir_con_barra(model, ruta_media: str, idioma_audio: str, archivo_respaldo: str = None, tarea: str = "transcribe"):
    """
    Corre la transcripción mostrando una barra de progreso basada en la duración del video.
    Si se indica archivo_respaldo, guarda el avance en disco DURANTE la transcripción
    (no solo al final), para que un cierre inesperado del programa (por ejemplo, un
    problema conocido de ciertos drivers de GPU en Windows al liberar memoria justo
    al terminar) no haga perder el trabajo ya hecho.

    tarea="translate" hace que Whisper traduzca directo al inglés en vez de
    transcribir literalmente (limitación del modelo: solo traduce a inglés).
    """
    import json

    idioma = None if idioma_audio == "auto" else idioma_audio  # None = Whisper lo detecta solo
    segments, info = model.transcribe(ruta_media, language=idioma, task=tarea)
    if idioma is None:
        print(f"Idioma detectado: {info.language} ({info.language_probability:.0%})")
    duracion_total = round(info.duration, 1) if info.duration else None

    resultado = []
    tiempo_previo = 0.0
    with tqdm(total=duracion_total, unit="s", desc="Transcribiendo", ncols=80,
              disable=duracion_total is None, file=sys.stdout) as barra:
        for seg in segments:
            resultado.append((seg.start, seg.end, seg.text.strip()))
            if duracion_total is not None:
                barra.update(round(seg.end - tiempo_previo, 1))
                tiempo_previo = seg.end
            if archivo_respaldo:
                with open(archivo_respaldo, "w", encoding="utf-8") as f:
                    json.dump(resultado, f, ensure_ascii=False, indent=2)

    if archivo_respaldo:
        print(f"Respaldo completo de la transcripción guardado en: {archivo_respaldo}")

    return resultado


def transcribir_con_whisper(ruta_media: str, modelo: str, idioma_audio: str, archivo_respaldo: str = None,
                            tarea: str = "transcribe", dispositivo: str = "auto", compute_type: str = "float16"):
    """
    Transcribe (o traduce a inglés, si tarea="translate") el video/audio con Whisper
    y devuelve [(inicio_segundos, fin_segundos, texto), ...].
    Muestra una barra de progreso según la duración del video.
    Si la GPU falla DURANTE la transcripción (no solo al cargar el modelo, por
    ejemplo por falta de cublas64_12.dll), reintenta automáticamente en CPU
    en vez de detenerse con un error.
    """
    from faster_whisper import WhisperModel

    if os.path.isdir(modelo):
        print("Cargando modelo Whisper...")
    else:
        print(f"Cargando modelo Whisper '{modelo}' (la primera vez lo descarga, puede tardar)...")
    model = cargar_modelo_whisper(modelo, dispositivo, compute_type)

    accion = "Traduciendo a inglés" if tarea == "translate" else "Transcribiendo"
    print(f"{accion} (idioma de audio: {idioma_audio})...")
    try:
        return _transcribir_con_barra(model, ruta_media, idioma_audio, archivo_respaldo, tarea)
    except RuntimeError as e:
        print(f"\nLa GPU falló durante la transcripción ({e}).")
        print("AVISO_CPU: Reintentando en CPU (será más lento, pero no se pierde el progreso)...")
        model_cpu = WhisperModel(modelo, device="cpu", compute_type="int8")
        return _transcribir_con_barra(model_cpu, ruta_media, idioma_audio, archivo_respaldo, tarea)


def alinear(guion, segmentos_whisper):
    """
    Para cada línea del guion busca el segmento de Whisper más parecido
    (por similitud de texto), respetando el orden cronológico.
    Devuelve lista de (timecode_str, personaje, dialogo).
    """
    textos_normalizados = [normalizar(t) for _, _, t in segmentos_whisper]
    resultado = []
    ultimo_indice_usado = 0

    for personaje, dialogo in tqdm(guion, desc="Emparejando líneas", unit="línea", ncols=80, file=sys.stdout):
        objetivo = normalizar(dialogo)
        mejor_score = -1
        mejor_indice = ultimo_indice_usado

        for i in range(ultimo_indice_usado, len(segmentos_whisper)):
            score = difflib.SequenceMatcher(None, objetivo, textos_normalizados[i]).ratio()
            if score > mejor_score:
                mejor_score = score
                mejor_indice = i

        if mejor_score < 0.3:
            timecode = "??:??:??,???"  # sin buena coincidencia: revisar a mano
        else:
            timecode = formatear_timecode(segmentos_whisper[mejor_indice][0])
            ultimo_indice_usado = mejor_indice

        resultado.append((timecode, personaje, dialogo))

    return resultado


def alinear_proporcional(guion, segmentos_whisper):
    """
    Modo alterno para cuando el guion está en un idioma DISTINTO al audio
    (por ejemplo audio en inglés, guion traducido al español), donde comparar
    texto no funciona porque no hay match posible entre idiomas.

    En vez de comparar contenido, reparte las líneas del guion a lo largo del
    tiempo de habla que detectó Whisper, proporcionalmente a la longitud de
    cada línea (líneas más largas ocupan más tiempo). Es una aproximación:
    respeta el orden y la duración total, pero no garantiza el segundo exacto
    de cada línea — conviene revisar el resultado con más cuidado que en el
    modo "texto".
    """
    if not segmentos_whisper:
        return [("??:??:??,???", p, d) for p, d in guion]

    tiempos = [inicio for inicio, _, _ in segmentos_whisper]
    n_segmentos = len(tiempos)

    total_caracteres = sum(len(dialogo) for _, dialogo in guion) or 1
    acumulado = 0
    resultado = []

    for personaje, dialogo in tqdm(guion, desc="Repartiendo líneas", unit="línea", ncols=80, file=sys.stdout):
        fraccion = acumulado / total_caracteres  # 0.0 a 1.0
        posicion = fraccion * (n_segmentos - 1)
        idx_bajo = int(posicion)
        idx_alto = min(idx_bajo + 1, n_segmentos - 1)
        peso = posicion - idx_bajo

        tiempo = tiempos[idx_bajo] * (1 - peso) + tiempos[idx_alto] * peso
        resultado.append((formatear_timecode(tiempo), personaje, dialogo))

        acumulado += len(dialogo)

    return resultado


def parsear_timecode(tc: str):
    """Convierte 'HH:MM:SS,mmm' a segundos (float). Devuelve None si el timecode no es confiable."""
    if "?" in tc:
        return None
    horas_min_seg, ms = tc.split(",")
    horas, minutos, segundos = horas_min_seg.split(":")
    return int(horas) * 3600 + int(minutos) * 60 + int(segundos) + int(ms) / 1000


def formatear_mmss(tc: str):
    """
    Convierte un timecode completo 'HH:MM:SS,mmm' al formato corto usado en
    doblaje: 'MMSS' (minutos y segundos, 2 dígitos cada uno, sin separadores
    ni milisegundos). Ej: '00:01:14,300' -> '0114'. Si el timecode no es
    confiable (??:??:??,???), devuelve '????' en vez de inventar un número.
    """
    segundos_totales = parsear_timecode(tc)
    if segundos_totales is None:
        return "????"
    minutos = int(segundos_totales // 60)
    segundos = int(segundos_totales % 60)
    return f"{minutos:02d}{segundos:02d}"


def generar_srt(filas, ruta_srt: str, duracion_minima=1.2, duracion_maxima=6.0, huelgo=0.1):
    """
    Genera un archivo .srt reutilizando los timecodes ya calculados en `filas`
    (los mismos que van al Word). Cada línea "dura" hasta que empieza la
    siguiente línea con timecode confiable (menos un pequeño margen), acotado
    a una duración mínima y máxima razonable para lectura.
    Las líneas marcadas como ??:??:??,??? se omiten (no hay dónde ubicarlas).
    Devuelve (cantidad_incluida, cantidad_omitida).
    """
    tiempos = [parsear_timecode(tc) for tc, _, _ in filas]
    n = len(filas)
    entradas = []

    for i, (tc, personaje, dialogo) in enumerate(filas):
        inicio = tiempos[i]
        if inicio is None:
            continue

        fin = None
        for j in range(i + 1, n):
            if tiempos[j] is not None:
                fin = tiempos[j] - huelgo
                break

        duracion = (fin - inicio) if fin else None
        if duracion is None or duracion < duracion_minima:
            fin = inicio + duracion_minima
        elif duracion > duracion_maxima:
            fin = inicio + duracion_maxima

        entradas.append((inicio, fin, personaje, dialogo))

    with open(ruta_srt, "w", encoding="utf-8") as f:
        for idx, (inicio, fin, personaje, dialogo) in enumerate(entradas, start=1):
            f.write(f"{idx}\n")
            f.write(f"{formatear_timecode(inicio)} --> {formatear_timecode(fin)}\n")
            f.write(f"{personaje}: {dialogo}\n\n")

    return len(entradas), n - len(entradas)


def generar_srt_directo(segmentos_whisper, ruta_srt: str):
    """
    Genera un .srt directamente de lo que transcribió Whisper, SIN necesitar
    un guion previo. A diferencia de generar_srt(), aquí se usan los tiempos
    de inicio Y FIN reales que detecta Whisper para cada segmento (más
    precisos que la aproximación por orden de líneas), pero el texto es
    exactamente lo que Whisper transcribió — sin personaje asignado ni
    traducción a otro idioma.
    """
    with open(ruta_srt, "w", encoding="utf-8") as f:
        for idx, (inicio, fin, texto) in enumerate(segmentos_whisper, start=1):
            f.write(f"{idx}\n")
            f.write(f"{formatear_timecode(inicio)} --> {formatear_timecode(fin)}\n")
            f.write(f"{texto}\n\n")
    return len(segmentos_whisper)


def generar_docx(filas, ruta_salida: str, formato_tc: str = "completo"):
    """
    Genera el Word final con columnas TIME CODE | PERSONAJE | DIÁLOGO.

    formato_tc="completo" (default): escribe el timecode tal cual (HH:MM:SS,mmm).
    formato_tc="mmss": escribe el formato corto de doblaje (MMSS, sin separadores
        ni milisegundos). Esto NO afecta el .srt generado con --exportar_srt,
        que sigue usando la lista original con el timecode completo — la
        conversión a MM:SS solo pasa al momento de escribir esta tabla.
    """
    doc = Document()
    doc.add_heading("Guion con Time Codes", level=1)

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

    revisar = 0
    for timecode, personaje, dialogo in filas:
        fila = tabla.add_row().cells
        fila[0].text = formatear_mmss(timecode) if formato_tc == "mmss" else timecode
        fila[1].text = personaje
        fila[2].text = dialogo
        if "?" in timecode:
            revisar += 1

    doc.save(ruta_salida)
    marcador_sin_tc = "????" if formato_tc == "mmss" else "??:??:??,???"
    print(f"\nDocumento generado: {ruta_salida}")
    if revisar:
        print(f"Atención: {revisar} línea(s) quedaron sin timecode confiable (marcadas con {marcador_sin_tc}). Revísalas a mano.")


def _cargar_respaldo(ruta_json: str):
    """
    Carga un archivo _respaldo_whisper.json ya generado, sin volver a usar la GPU.
    Compatible con respaldos antiguos (solo inicio + texto, de episodios procesados
    antes de que el script guardara también el tiempo de fin) y con los nuevos
    (inicio + fin + texto): a los antiguos les calcula un fin aproximado usando el
    inicio del siguiente segmento.
    """
    import json

    print(f"Cargando transcripción ya hecha desde: {ruta_json} (no se usa la GPU en este modo).")
    with open(ruta_json, "r", encoding="utf-8") as f:
        datos = json.load(f)

    if datos and len(datos[0]) == 3:
        return [tuple(s) for s in datos]

    # Respaldo antiguo (solo inicio, texto): se aproxima el fin con el inicio del siguiente
    segmentos = []
    for i, (inicio, texto) in enumerate(datos):
        fin = datos[i + 1][0] if i + 1 < len(datos) else inicio + 2.0
        segmentos.append((inicio, fin, texto))
    return segmentos


def main():
    parser = argparse.ArgumentParser(description="Alinea un guion existente con timecodes de Whisper.")
    parser.add_argument("--video", required=True, help="Ruta al video o audio (mp4, mov, wav, mp3, etc.)")
    parser.add_argument("--guion", default=None,
                         help="Ruta al .docx con el guion existente (PERSONAJE/DIÁLOGO). "
                              "Si se omite, genera subtítulos directos de lo que transcribe Whisper "
                              "(sin personaje ni traducción), usando --salida terminado en .srt")
    parser.add_argument("--salida", default="guion_con_timecodes.docx", help="Ruta del .docx de salida")
    parser.add_argument("--modelo", default="medium",
                         help="Modelo Whisper: tiny, base, small, medium, large-v3, large-v3-turbo, "
                              "o la ruta a una carpeta con un modelo ya descargado")
    parser.add_argument("--dispositivo", default="auto", choices=["auto", "cuda", "cpu"],
                         help="'auto' intenta GPU y cae a CPU si falla; 'cpu' no intenta la GPU")
    parser.add_argument("--compute_type", default="float16",
                         help="Precisión en GPU: float16 (default), int8 (GPUs GTX 10xx) o float32")
    parser.add_argument("--idioma_audio", default="es", help="Idioma real del AUDIO del video (no del guion). Ej: en, es, fr")
    parser.add_argument("--modo", default="texto", choices=["texto", "proporcional"],
                         help="'texto' si guion y audio están en el mismo idioma; 'proporcional' si el guion está traducido a otro idioma")
    parser.add_argument("--continuar_desde", default=None,
                         help="Ruta a un archivo _respaldo_whisper.json ya generado. Si se indica, NO vuelve a "
                              "transcribir con Whisper (ahorra tiempo/GPU): usa esos timecodes directamente.")
    parser.add_argument("--exportar_srt", action="store_true",
                         help="Además del .docx, genera un archivo .srt (subtítulos) con el mismo nombre.")
    parser.add_argument("--formato_tc", default="completo", choices=["completo", "mmss"],
                         help="Formato del TIME CODE en el Word: 'completo' (HH:MM:SS,mmm, default) o "
                              "'mmss' (convención de doblaje: MMSS, sin separadores ni milisegundos). "
                              "No afecta el .srt generado con --exportar_srt, que siempre usa el formato completo.")
    parser.add_argument("--tarea", default="transcribir", choices=["transcribir", "traducir_a_ingles"],
                         help="'transcribir': texto en el idioma del audio. 'traducir_a_ingles': Whisper traduce "
                              "directo a inglés (solo a inglés, es una limitación del modelo). Útil para generar "
                              "subtítulos en inglés desde audio en japonés u otro idioma, en el modo sin guion.")
    parser.add_argument("--tc_fijo", default=None,
                         help="Fuerza un TIME CODE fijo para filas con un PERSONAJE específico (útil para "
                              "tarjetas de título sin diálogo hablado, que Whisper no puede ubicar). Formato: "
                              "'PERSONAJE=MM:SS;OTRO_PERSONAJE=MM:SS'. Ej: 'TÍTULO=0:32;TÍTULO EPISÓDICO=0:34'. "
                              "Solo aplica en el modo con --guion.")
    args = parser.parse_args()

    tarea_whisper = "translate" if args.tarea == "traducir_a_ingles" else "transcribe"

    # --- Modo directo: sin guion previo, subtítulos de lo que transcribe Whisper ---
    if not args.guion:
        ruta_srt = args.salida
        if ruta_srt.lower().endswith(".docx"):
            ruta_srt = ruta_srt.rsplit(".", 1)[0] + ".srt"
            print(f"No se indicó --guion: se generarán subtítulos directos en '{ruta_srt}' "
                  f"(usa --salida terminando en .srt para elegir el nombre).")
        elif not ruta_srt.lower().endswith(".srt"):
            ruta_srt += ".srt"

        respaldo = ruta_srt.rsplit(".", 1)[0] + "_respaldo_whisper.json"

        if args.continuar_desde:
            segmentos = _cargar_respaldo(args.continuar_desde)
        else:
            segmentos = transcribir_con_whisper(
                args.video, modelo=args.modelo, idioma_audio=args.idioma_audio,
                archivo_respaldo=respaldo, tarea=tarea_whisper,
                dispositivo=args.dispositivo, compute_type=args.compute_type,
            )

        cantidad = generar_srt_directo(segmentos, ruta_srt)
        print(f"\nSubtítulos generados: {ruta_srt} ({cantidad} líneas, tiempos reales de Whisper)")
        return

    # --- Modo con guion: alinea el guion existente con los timecodes ---
    guion = leer_guion(args.guion)
    if not guion:
        print("No se pudo leer ninguna línea PERSONAJE/DIÁLOGO del documento. Revisa el formato (ver comentarios arriba).")
        return
    print(f"Se leyeron {len(guion)} líneas del guion.")

    respaldo = args.salida.rsplit(".", 1)[0] + "_respaldo_whisper.json"

    if args.continuar_desde:
        segmentos = _cargar_respaldo(args.continuar_desde)
    else:
        segmentos = transcribir_con_whisper(
            args.video, modelo=args.modelo, idioma_audio=args.idioma_audio,
            archivo_respaldo=respaldo, tarea=tarea_whisper,
            dispositivo=args.dispositivo, compute_type=args.compute_type,
        )

    print(f"Whisper generó {len(segmentos)} segmentos con timecode.")

    if args.modo == "proporcional":
        print("Modo 'proporcional': repartiendo líneas según duración de habla (guion en idioma distinto al audio).")
        filas_finales = alinear_proporcional(guion, segmentos)
    else:
        filas_finales = alinear(guion, segmentos)

    if args.tc_fijo:
        tc_fijo_dict = parsear_tc_fijo(args.tc_fijo)
        if tc_fijo_dict:
            filas_finales = aplicar_tc_fijo(filas_finales, tc_fijo_dict)
            print(f"TC fijo aplicado a: {', '.join(tc_fijo_dict.keys())}")

    generar_docx(filas_finales, args.salida, formato_tc=args.formato_tc)

    if args.exportar_srt:
        ruta_srt = args.salida.rsplit(".", 1)[0] + ".srt"
        incluidas, omitidas = generar_srt(filas_finales, ruta_srt)
        print(f"Subtítulos generados: {ruta_srt} ({incluidas} líneas incluidas, {omitidas} omitidas por falta de timecode confiable)")


if __name__ == "__main__":
    main()
