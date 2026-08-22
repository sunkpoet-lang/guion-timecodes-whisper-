# Guion con time codes (Whisper + Word/SRT)

Dos herramientas web locales para producción de doblaje, usando
[Whisper](https://github.com/openai/whisper) (vía `faster-whisper`):

- **Convertir libreto** — toma un libreto tradicional (números de escena, PERSONAJE/DIÁLOGO
  en dos columnas), o subtítulos `.srt`/`.ass` ya existentes, y los pasa a una tabla Word de
  3 columnas (TIME CODE, PERSONAJE, DIÁLOGO) — detecta el formato de entrada automáticamente.
- **Guion con time codes — Whisper** — toma un video y, según el caso:
  - **Ya tengo transcripción/traducción**: genera un Word con **TIME CODE | PERSONAJE |
    DIÁLOGO**, calculando los tiempos reales a partir del video, sin modificar tu texto ni
    las asignaciones. Pensado para guiones **traducidos** a otro idioma distinto al del audio.
  - **Ya tengo un ASREC sin TIME CODE**: igual que arriba, pero para transcripciones en el
    **mismo idioma** que el audio (as-recorded), sin traducción de por medio.
  - **No tengo transcripción**: genera subtítulos `.srt` directo de lo que transcribe
    Whisper, con los tiempos reales de inicio y fin — con opción de traducir a inglés
    (útil para audio en japonés u otro idioma, sin traducción humana previa).

Ambas corren como páginas web locales (Gradio) — no se necesita usar la línea de comandos
para el uso diario. Detectan automáticamente tu GPU/CPU/RAM y sugieren el modelo de Whisper
más adecuado para tu equipo.

## Requisitos

- Python 3.9 o superior — el único paso que sí hay que instalar a mano (no se puede
  automatizar desde un script que necesita ese mismo Python para correr).
- Todo lo demás (entorno virtual, librerías, ffmpeg cuando es posible) lo instala el
  script de configuración automática de abajo.
- Opcional: GPU NVIDIA con CUDA para acelerar la transcripción (si no hay GPU compatible,
  el script usa el procesador automáticamente).

## Instalación automática (recomendada)

1. Instala Python desde [python.org/downloads](https://python.org/downloads) si no lo
   tienes. **Windows:** marca la casilla "Add Python to PATH" durante la instalación.

2. Clona o descarga este repositorio, y abre una terminal en esa carpeta.

3. Corre el script de configuración según tu sistema:

   **Windows:** doble clic en `setup.bat` (o `setup.bat` desde una terminal).

   **Mac/Linux:**
   ```bash
   chmod +x *.sh
   ./setup.sh
   ```

   Esto crea el entorno virtual, instala todas las dependencias de `requirements.txt`, y
   verifica (e intenta instalar) ffmpeg automáticamente.

4. Para usar el proyecto de ahí en adelante, solo hace falta doble clic (Windows) o correr
   el script (Mac/Linux) — no hay que volver a activar entornos ni instalar nada más:

   | Herramienta | Windows | Mac/Linux |
   |---|---|---|
   | Convertir libreto | `iniciar_convertir_libreto.bat` | `./iniciar_convertir_libreto.sh` |
   | Guion con time codes | `iniciar_time_codes.bat` | `./iniciar_time_codes.sh` |

   Para tener **las dos páginas abiertas al mismo tiempo**, necesitas dos ventanas/terminales
   separadas (una por herramienta) — Gradio les asigna puertos distintos automáticamente
   (normalmente `http://127.0.0.1:7860` y `http://127.0.0.1:7861`; usa la dirección exacta
   que muestre cada terminal). Si corres los dos comandos en la misma terminal uno tras otro,
   el segundo va a fallar o a tomar el puerto que dejó libre el primero al cerrarse.

## Instalación manual (alternativa)

Si prefieres hacerlo paso a paso en vez de usar `setup.bat`/`setup.sh`:

1. Clona o descarga este repositorio.

2. Crea y activa un entorno virtual:

   ```bash
   python -m venv venv
   ```

   Windows (PowerShell):
   ```powershell
   .\venv\Scripts\Activate.ps1
   ```
   Windows (CMD):
   ```
   venv\Scripts\activate.bat
   ```
   Mac/Linux:
   ```bash
   source venv/bin/activate
   ```

3. Instala las dependencias:

   ```bash
   pip install -r requirements.txt
   ```

4. Verifica que ffmpeg esté instalado:

   ```bash
   ffmpeg -version
   ```

   Si no lo tienes: `winget install ffmpeg` (Windows), `brew install ffmpeg` (Mac),
   `sudo apt install ffmpeg` (Linux).

## Uso por línea de comandos

**Con guion existente** (genera Word):
```bash
python alinear_timecodes.py --video "video.mp4" --guion "guion.docx" --salida "guion_con_tc.docx"
```

**Sin guion** (genera subtítulos `.srt` directo del video, con tiempos reales de Whisper):
```bash
python alinear_timecodes.py --video "video.mp4" --salida "subtitulos.srt"
```
Si se omite `--guion`, el script entra automáticamente a este modo. Si `--salida` termina
en `.docx` sin haber indicado `--guion`, el script avisa y cambia la extensión a `.srt` solo.

### Parámetros

| Parámetro | Descripción | Default |
|---|---|---|
| `--video` | Ruta al video o audio (mp4, mov, wav, etc.) | — (obligatorio) |
| `--guion` | Ruta al `.docx` con el guion existente. Si se omite, genera subtítulos directos (ver arriba) | — (opcional) |
| `--salida` | Ruta del archivo de salida (`.docx` con guion, `.srt` sin guion) | `guion_con_timecodes.docx` |
| `--modelo` | Modelo de Whisper: `tiny`, `base`, `small`, `medium`, `large-v3` | `medium` |
| `--idioma_audio` | Idioma real del AUDIO del video (no el del guion). Ej: `en`, `es`, `ja` | `es` |
| `--modo` | `texto` o `proporcional` (ver más abajo). Solo aplica con `--guion` | `texto` |
| `--continuar_desde` | Ruta a un `_respaldo_whisper.json` ya generado, para completar sin repetir la transcripción | — |
| `--exportar_srt` | Con `--guion`: además del `.docx`, genera un `.srt` reutilizando esos timecodes | desactivado |
| `--tarea` | `transcribir` o `traducir_a_ingles` (ver más abajo) | `transcribir` |
| `--formato_tc` | `completo` (HH:MM:SS,mmm) o `mmss` (convención de doblaje: MMSS, ver más abajo) | `completo` |

### Traducir a inglés (`--tarea traducir_a_ingles`)

Whisper puede traducir directo al inglés mientras transcribe — útil para generar subtítulos
en inglés a partir de audio en japonés u otro idioma, sin necesitar una traducción humana
previa. **Limitación del modelo: solo traduce A INGLÉS**, no hay opción de traducir directo
a español ni a ningún otro idioma. Para llegar a español desde japonés sin traducción
humana, el camino sería japonés → inglés (con esta opción) → español (con un traductor
aparte) — normalmente da mejor resultado que intentar japonés → español directo. Aplica
sobre todo al modo sin guion (subtítulos directos); revisión humana recomendada después,
especialmente para juegos de palabras, honoríficos o referencias culturales.

### Formato del TIME CODE (`--formato_tc`)

- **`completo`** (default): `HH:MM:SS,mmm`, con precisión de milisegundos.
- **`mmss`**: convención de doblaje, `MMSS` sin separadores ni milisegundos (ej. `0114` =
  1 min 14 s). Solo cambia cómo se ve la columna del Word — el `.srt` generado con
  `--exportar_srt` siempre usa el formato completo, ya que lo necesita para funcionar en
  reproductores de video. Las líneas sin timecode confiable se marcan `????` en este modo.

### Modo `texto` vs `proporcional`

- **`texto`**: compara el texto del guion contra lo que transcribe Whisper. Úsalo cuando
  el guion está en el **mismo idioma** que el audio del video.
- **`proporcional`**: no compara texto, reparte las líneas del guion a lo largo del tiempo
  de habla detectado por Whisper, según la duración de cada línea. Úsalo cuando el guion
  está **traducido a un idioma distinto** al del audio (por ejemplo, audio en inglés y
  guion en español) — comparar texto no funciona entre idiomas distintos. Es una
  aproximación: revisa el resultado con más cuidado que en modo `texto`.

### Formato del guion de entrada

El script detecta automáticamente:
- Una **tabla de Word** con columnas cuyo encabezado contenga `PERSONAJE` (o `CHARACTER`)
  y `DIALOGO`/`DIÁLOGO` (o `DIALOGUE`).
- **Párrafos sueltos** con el formato `PERSONAJE: diálogo`.

### Subtítulos (.srt)

Hay dos formas de obtener un `.srt`, con distinta precisión:

- **Sin guion** (modo directo): usa los tiempos reales de inicio y fin que detecta
  Whisper para cada frase. Más preciso, pero el texto es literal (sin traducir, sin
  personaje asignado).
- **Con guion + `--exportar_srt`**: reutiliza los timecodes ya calculados al alinear tu
  guion. Cada línea dura hasta que empieza la siguiente línea con timecode confiable (con
  un pequeño margen), acotado entre 1.2 y 6 segundos. Las líneas sin timecode confiable
  (`??:??:??,???`) se omiten. Es una aproximación razonable para revisar sincronía, no un
  subtitulado frame-perfect para entrega final.

## Convertir libreto (formato tradicional / .srt / .ass → 3 columnas)

```bash
python convertir_libreto_app.py
```

Detecta automáticamente el formato de lo que pegues o subas:

- **Libreto tradicional**: bloques de escena numerados (`1 (10:00:02:00)`) seguidos de
  líneas `PERSONAJE` + `DIÁLOGO` alineadas en dos columnas (por tabulador o por espacios).
  Ignora el encabezado (título, número de episodio) y las marcas de escena automáticamente.
  TIME CODE queda **vacío** — se calcula después con "Guion con time codes".
- **Subtítulos `.srt` o `.ass` ya existentes**: TIME CODE se llena con el tiempo **real**
  del archivo, PERSONAJE queda **vacío** para asignarlo a mano viendo el video — evita
  copiar bloques de texto y recalcular timecodes, ahorrando tiempo y evitando errores de
  continuidad. Limpia automáticamente etiquetas de formato (`<i>`, `{\...}`, saltos `\N`).

En los tres casos, el resultado se muestra en una **tabla editable** antes de exportar —
las líneas que no se pudieron separar (solo en libreto tradicional) quedan marcadas con
`?` en PERSONAJE. Exporta un `.docx` de 3 columnas, listo para usarse como `--guion` (o
subido en "Guion con time codes") en el siguiente paso. Incluye la misma opción de formato
MM:SS para el TIME CODE que la otra herramienta (solo tiene efecto si viene de `.srt`/`.ass`).

También se puede usar por línea de comandos:
```bash
python convertir_libreto.py --entrada libreto.txt --salida guion_3_columnas.docx
python convertir_libreto.py --entrada subtitulos.srt --salida guion_3_columnas.docx --formato_tc mmss
python convertir_libreto.py --entrada fansub.ass --salida guion_3_columnas.docx
```

## Uso con la interfaz web (Gradio) — Guion con time codes — Whisper

```bash
python gradio_app.py
```

Se abre automáticamente en el navegador (normalmente `http://127.0.0.1:7860`).

Al abrirla, incluye un panel de "Cómo usar esta página" y otro con el formato exacto de
guion que necesitas subir. Debajo, un selector con 3 opciones:

- **"Ya tengo transcripción/traducción"** → para guiones **traducidos** a un idioma
  distinto al del audio. Preselecciona el modo de alineación "Proporcional".
- **"Ya tengo un ASREC sin TIME CODE"** → para transcripciones en el **mismo idioma** que
  el audio (as-recorded, sin traducir). Preselecciona el modo de alineación "Texto".
  Ambas opciones muestran los mismos campos (video + guion en Word), solo cambia el modo
  de alineación preseleccionado — sigue siendo editable en cualquiera de los dos casos.
- **"No tengo transcripción"** → solo sube el video, genera subtítulos `.srt` directo (los
  campos de guion y modo de alineación se ocultan solos, ya que no aplican). Incluye la
  opción de tarea "Traducir a inglés" para audio en idiomas distintos al inglés.

La página detecta automáticamente tu **GPU (NVIDIA vía `nvidia-smi`), CPU y RAM** (con
comandos nativos del sistema operativo, sin necesitar instalar nada extra) y sugiere el
modelo de Whisper más adecuado para tu equipo — si detecta una GPU de otra marca (AMD/Intel)
te avisa que Whisper solo acelera con NVIDIA y por qué va a usar CPU en ese caso.

El nombre del archivo de salida se autocompleta con el nombre del video en cuanto lo subes
(por ejemplo, `SFOOT_101.mov` sugiere `SFOOT_101.docx` o `SFOOT_101.srt` según el modo) —
sigue siendo editable si quieres cambiarlo. Los resultados se identifican con insignias de
color (📄 WORD / 💬 SUBS) para no confundirlos a simple vista. Al final de la página hay un
ejemplo ilustrativo de cómo se ve el Word resultante.

Para compartirla con otras personas en tu misma red, cambia al final de `gradio_app.py`:
```python
demo.launch(share=True)
```
Esto genera un link temporal accesible desde fuera de tu red — solo actívalo cuando lo
necesites, ya que expone tu equipo mientras el link esté activo.

> **Nota:** por ahora está pensado para un solo usuario a la vez por instancia (usa la GPU
> o CPU de la máquina donde corre). Si varias personas lo usan al mismo tiempo desde la
> misma máquina, competirán por los mismos recursos.

## Notas sobre GPU

El script intenta usar GPU (CUDA) automáticamente y cae a CPU si no está disponible. Si
tienes GPU NVIDIA pero ves errores de `cublas`/`cudnn` al transcribir, instala:

```bash
pip install nvidia-cublas-cu12 nvidia-cudnn-cu12
```

### Problema conocido: cierre inesperado justo después de transcribir

En algunos equipos con Windows, el proceso puede cerrarse solo justo al terminar de
transcribir (antes de guardar el Word), por un problema de compatibilidad entre ciertos
drivers de GPU y la limpieza de memoria. **No se pierde el trabajo hecho**: el script
guarda un respaldo (`*_respaldo_whisper.json`) con los timecodes conforme los va
detectando. Si esto pasa, corre de nuevo el mismo comando agregando:

```bash
--continuar_desde "nombre_de_salida_respaldo_whisper.json"
```

Esto genera el resultado usando el respaldo, sin volver a usar la GPU. La interfaz de
Gradio ya maneja esto automáticamente. Compatible también con respaldos generados por
versiones anteriores del script (antes de que se guardara también el tiempo de fin de
cada línea) — a esos les calcula un fin aproximado.

## Solución de problemas

| Problema | Solución |
|---|---|
| `python no se reconoce como un comando` | Python no quedó en el PATH. Reinstala marcando "Add Python to PATH". |
| `ModuleNotFoundError` | El entorno virtual no está activado, o falta instalar. Verifica el prompt y corre `pip install -r requirements.txt` de nuevo. |
| `RuntimeError: Library cublas64_12.dll is not found` | Instala `nvidia-cublas-cu12 nvidia-cudnn-cu12` (ver arriba). |
| El programa se cierra solo tras "Transcribiendo: 100%" | Ver "Problema conocido" arriba — usa `--continuar_desde`. |
| Muchas líneas quedan marcadas con `??:??:??,???` (modo texto) | El audio tiene mucho ruido/música, o el guion difiere bastante del audio real. |
| El Word muestra una versión vieja al abrirlo | Word no se actualiza solo si el archivo cambia en disco mientras está abierto. Ciérralo sin guardar y vuelve a abrirlo. |
| `ValueError: The truth value of a DataFrame is ambiguous` en Convertir libreto | Ya corregido en la versión actual — usa `len(tabla) == 0` en vez de `not tabla`, ya que Gradio a veces entrega la tabla como DataFrame de pandas incluso con `type="array"`. |
| Los paneles de texto (pasos, requisitos, detección de hardware) se ven en blanco/invisibles | El tema oscuro de Gradio aplica `color` con `!important` a elementos como `<span>`/`<b>`, ganándole a estilos heredados del contenedor padre. La solución es poner `color:...!important` en **cada elemento de texto individualmente**, no solo en el `<div>` contenedor — ya corregido en la versión actual. |
| Dos páginas no abren juntas / una no carga | Necesitan **dos terminales separadas**, una por herramienta. Correr ambos comandos en la misma terminal hace que el segundo falle o tome el puerto que dejó libre el primero. |

## Estructura del proyecto

```
alinear_timecodes.py          # Lógica principal (Whisper + alineación + generación de Word/SRT)
gradio_app.py                  # Interfaz web de "Guion con time codes — Whisper"
convertir_libreto.py           # Lógica de conversión (libreto tradicional / .srt / .ass → 3 columnas)
convertir_libreto_app.py       # Interfaz web de "Convertir libreto"
requirements.txt               # Dependencias
.gitignore                     # Excluye videos, guiones, resultados y respaldos personales
setup.bat / setup.sh           # Instalación automática (entorno + dependencias + ffmpeg)
iniciar_time_codes.bat/.sh     # Lanzador de "Guion con time codes — Whisper"
iniciar_convertir_libreto.bat/.sh  # Lanzador de "Convertir libreto"
```
