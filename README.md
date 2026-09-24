# Guion con Time Codes (Whisper para doblaje)

App de escritorio para producción de doblaje, con [Whisper](https://github.com/openai/whisper)
(vía `faster-whisper`):

- **Time codes**: toma el video de un episodio y, según el caso:
  - **Tengo el guion traducido**: genera un Word con **TIME CODE | PERSONAJE | DIÁLOGO**
    sin tocar tu texto ni las asignaciones. Para guiones traducidos a otro idioma que el del audio.
  - **Tengo un ASREC sin time code**: igual, pero el guion está en el **mismo idioma** que el
    audio; alinea comparando el texto, así que es más exacto.
  - **No tengo guion**: genera subtítulos `.srt` directo de lo que escucha Whisper, con opción
    de traducir a inglés.
- **Convertir libreto**: pasa a una tabla de 3 columnas (T.C. | PERSONAJE | DIÁLOGO), editable
  antes de exportar a **Word o Excel**. Basta con arrastrar el archivo a la ventana; se convierte solo:
  - libreto tradicional, guion numerado tipo screenplay o guion *as broadcast* (`PERSONAJE: diálogo`);
  - Word hecho con estilos de guion (`Personnage` / `Dialogue` / `Parenthèse`, como los ASREC de Foot 2 Rue);
  - Word que ya trae una tabla (como los ASR de CaptionMax: `# | Timecode | Character | Dialogue`):
    se toman solo esas tres columnas y se descarta la numeración `#`;
  - subtítulos `.srt` / `.ass` (el T.C. sale del archivo y PERSONAJE queda vacío para asignarlo).
- **Traducir**: traduce el guion con un modelo de lenguaje que corre **en tu equipo, sin internet**,
  siguiendo el **perfil de estilo** de cada traductor (sus reglas en lenguaje natural y su glosario).
  El resultado es un borrador para revisar, con el T.C. intacto y la columna PERSONAJE adaptada.
- **Modelos y equipo**: detecta tu procesador, RAM y tarjeta de video, recomienda el mejor modelo
  de Whisper y de traducción para tu equipo, los descarga y activa la GPU NVIDIA con un clic.

## Descargar

Ve a **[Releases](https://github.com/sunkpoet-lang/guion-timecodes-whisper-/releases/latest)** y baja
el archivo de tu sistema:

| Sistema | Archivo | Cómo se instala |
|---|---|---|
| **Windows 10/11** | `GuionTimecodes-Setup-X.Y.Z.exe` | Doble clic. No pide permisos de administrador. |
| Mac (Apple Silicon) | `GuionTimecodes-X.Y.Z-macOS.zip` | Descomprimir, clic derecho en la app → **Abrir** (la primera vez). |
| Linux | `GuionTimecodes-X.Y.Z-Linux.tar.gz` | Descomprimir y correr `GuionTimecodes/GuionTimecodes`. |

> Windows puede mostrar "Windows protegió su PC" porque el instalador no está firmado:
> **Más información → Ejecutar de todas formas**.

La app avisa en la barra lateral cuando hay una versión nueva.

## Modelos y GPU

La app trae el modelo **Base** incluido. En **Modelos y equipo** puedes descargar los demás
desde sus páginas oficiales en Hugging Face:

| Modelo | Tamaño | Notas |
|---|---|---|
| Tiny | 75 MB | Solo para pruebas. |
| Base | 141 MB | Incluido. |
| Small | 464 MB | Buen equilibrio sin GPU. |
| Medium | 1.4 GB | Preciso. |
| Large v3 Turbo | 1.5 GB | Casi tan preciso como Large v3 y mucho más rápido. No traduce. |
| Large v3 | 2.9 GB | El más preciso. Ideal con GPU. |
| Distil Large v3.5 | 1.4 GB | Solo audio en inglés. |

La recomendación sale de la VRAM de tu GPU, o de los núcleos y la RAM si usas el procesador,
con un tiempo estimado por episodio de 22 minutos. Si ya tenías modelos descargados por la
versión anterior (caché de Hugging Face), la app los encuentra y no los vuelve a bajar.

**GPU NVIDIA:** el driver no trae las librerías que Whisper necesita (cuBLAS y cuDNN). Sin
ellas, Whisper cae al procesador sin avisar. Con **Activar GPU**, la app las descarga una sola
vez (~1.2 GB) desde los paquetes oficiales de NVIDIA en PyPI. Solo aplica a Windows y Linux;
en Mac, Whisper usa el procesador.

Todo lo descargado vive en la carpeta de datos del usuario y se conserva al actualizar:

- Windows: `%LOCALAPPDATA%\GuionTimecodes`
- Mac: `~/Library/Application Support/GuionTimecodes`
- Linux: `~/.local/share/guion-timecodes`

## Traducción sin internet

La traducción corre con [llama.cpp](https://github.com/ggml-org/llama.cpp), que la app descarga la
primera vez (~30 MB). En Windows y Linux usa la versión Vulkan, que acelera con GPUs NVIDIA, AMD e Intel;
en Mac usa Metal. Sin GPU compatible, usa el procesador.

| Modelo | Descarga | Pensado para |
|---|---|---|
| Qwen 3.5 2B | 1.2 GB | Solo CPU o poca RAM |
| Qwen 3.5 4B | 2.6 GB | CPU o GPU modesta |
| Gemma 4 E4B | 4.8 GB | GPU de 6 GB |
| Qwen 3.5 9B | 5.3 GB | GPU de 8 GB |
| Gemma 4 12B | 6.5 GB | GPU de 10–12 GB (un episodio de 460 líneas en ~8 min con una RTX 2060) |
| Gemma 4 26B A4B | 13.4 GB | GPU de 16 GB+, o CPU con 32 GB de RAM |

Todos son Apache 2.0 (se pueden usar en trabajo comercial). La app recomienda el mejor que cabe en
tu GPU, con el tiempo estimado por episodio.

**Perfiles de estilo.** Cada traductor o serie tiene el suyo:
- **Reglas** en lenguaje natural (registro, tú/usted, palabras prohibidas, interjecciones…). Se pueden
  importar de un `estilo.md` o `.txt`.
- **Glosario**: personajes (ORIGINAL · DOBLAJE · VARIANTES · EN_DIALOGO) y términos. Se importa de un
  Excel con las pestañas `PERSONAJES` y `TERMINOS`, o de cualquier hoja con columnas `ORIGINAL` y `DOBLAJE`.
- **Acotaciones**: opcionalmente, todo paréntesis del diálogo se reemplaza por una marca fija, por ejemplo `(REAC)`.
- **MAYÚSCULAS** para entregar en formato de rayado.
- Se exportan como `.perfil.json` para compartirlos con otros traductores.

Cómo traduce: por bloques de 16 líneas con el contexto anterior y siguiente, mandando solo las
entradas del glosario que aparecen en cada bloque. La columna PERSONAJE se adapta con el glosario sin
pasar por el modelo. Al final marca para revisar las líneas donde no se respetó el glosario, y lista
los personajes que faltan en el glosario (con un botón para agregarlos).

## Formato del guion de entrada

- Una **tabla de Word** con columnas `PERSONAJE` (o `CHARACTER`) y `DIÁLOGO` (o `DIALOGUE`).
  Es lo que produce **Convertir libreto**.
- Un Word hecho con **estilos de guion** (`Personnage` / `Dialogue`…), como los ASREC.
- O **párrafos sueltos** con el formato `PERSONAJE: diálogo`.

Opcionalmente, además del Word, genera el mismo resultado en **Excel** y en subtítulos `.srt`.

### Alineación proporcional vs. por texto

- **Proporcional**: no compara texto. Reparte las líneas del guion a lo largo del tiempo de habla
  según la duración de cada una. Para guiones **traducidos**. Es una aproximación: revisa el resultado.
- **Por texto**: compara cada línea con lo que transcribe Whisper. Solo sirve con guion y audio en el
  **mismo idioma**. Las líneas sin coincidencia quedan marcadas `??:??:??,???` (o `????` en MMSS).

### TIME CODE en MMSS

Convención de doblaje: `0114` = 1 min 14 s. Solo cambia la columna del Word; el `.srt` siempre usa
el formato completo.

## Instalar desde el código (desarrollo)

Requiere Python 3.10 o superior.

```bash
git clone https://github.com/sunkpoet-lang/guion-timecodes-whisper-.git
cd guion-timecodes-whisper-
```

- **Windows:** doble clic en `setup.bat` y luego en `iniciar.bat`.
- **Mac/Linux:** `./setup.sh` y luego `./iniciar.sh`. Si no se abre la ventana (en Linux hace falta
  GTK o Qt para pywebview), la app se abre sola en el navegador; también puedes forzarlo con
  `./iniciar.sh --navegador`.

### Compilar el ejecutable

```bash
pip install pyinstaller
python empaquetado/descargar_modelo.py base modelos_incluidos/base
pyinstaller empaquetado/guion_timecodes.spec --noconfirm
```

Queda en `dist/GuionTimecodes/`. El instalador de Windows se arma con
[Inno Setup](https://jrsoftware.org/isinfo.php): `iscc /DVersion=2.0.0 empaquetado\instalador.iss`.

### Publicar una versión

El flujo `.github/workflows/release.yml` compila Windows, Mac y Linux y publica el release:

```bash
git tag v2.0.1
git push origin v2.0.1
```

También se puede correr a mano desde la pestaña **Actions** para probar la compilación sin publicar.

## Línea de comandos

**Con guion** (genera Word):
```bash
python alinear_timecodes.py --video "video.mp4" --guion "guion.docx" --salida "guion_con_tc.docx"
```

**Sin guion** (subtítulos `.srt` directo del video):
```bash
python alinear_timecodes.py --video "video.mp4" --salida "subtitulos.srt"
```

| Parámetro | Descripción | Default |
|---|---|---|
| `--video` | Video o audio (mp4, mov, wav…) | obligatorio |
| `--guion` | `.docx` con el guion. Sin él, genera subtítulos directos | — |
| `--salida` | Archivo de salida (`.docx` con guion, `.srt` sin guion) | `guion_con_timecodes.docx` |
| `--modelo` | `tiny`, `base`, `small`, `medium`, `large-v3`, `large-v3-turbo` o la carpeta de un modelo | `medium` |
| `--idioma_audio` | Idioma del AUDIO (no del guion): `en`, `es`, `ja`… o `auto` | `es` |
| `--modo` | `texto` o `proporcional` (solo con `--guion`) | `texto` |
| `--dispositivo` | `auto` (GPU y si falla CPU), `cuda` o `cpu` | `auto` |
| `--compute_type` | Precisión en GPU: `float16`, `int8` (GTX 10xx) o `float32` | `float16` |
| `--continuar_desde` | `_respaldo_whisper.json` ya generado, para terminar sin transcribir de nuevo | — |
| `--exportar_srt` | Con `--guion`: genera también un `.srt` con los mismos timecodes | desactivado |
| `--exportar_xlsx` | Con `--guion`: genera también un Excel con las mismas 3 columnas | desactivado |
| `--tarea` | `transcribir` o `traducir_a_ingles` (solo traduce A inglés) | `transcribir` |
| `--formato_tc` | `completo` (HH:MM:SS,mmm) o `mmss` | `completo` |
| `--tc_fijo` | TIME CODE fijo por personaje, ej. `'TÍTULO=0:32;TÍTULO EPISÓDICO=0:34'` | — |

Convertir libreto sin la app:
```bash
python convertir_libreto.py --entrada libreto.txt --salida guion_3_columnas.docx
python convertir_libreto.py --entrada subtitulos.srt --salida guion_3_columnas.docx --formato_tc mmss
python convertir_libreto.py --entrada Saltix_23_ASR.docx --salida guion_3_columnas.xlsx
```

## Problema conocido: cierre justo después de transcribir

En algunos equipos con Windows, el proceso de Whisper se cierra solo al terminar de transcribir,
por un problema entre ciertos drivers de GPU y la limpieza de memoria. **No se pierde el trabajo**:
Whisper corre en un proceso aparte que guarda un respaldo mientras avanza, y la app termina
el documento desde ese respaldo automáticamente. Por línea de comandos, agrega
`--continuar_desde "salida_respaldo_whisper.json"`.

## Solución de problemas

| Problema | Solución |
|---|---|
| "La GPU falló y Whisper siguió en el procesador" | Ve a **Modelos y equipo**. Si dice "GPU sin activar", usa **Activar GPU**. Si ya está activa, prueba un modelo más chico (puede faltar VRAM). |
| La ventana no abre y la app aparece en el navegador | En Windows falta el runtime WebView2 (viene con Edge): instálalo desde Microsoft. En Linux falta GTK/Qt. La app funciona igual en el navegador. |
| Muchas líneas `??:??:??,???` (alineación por texto) | El audio tiene mucha música o ruido, o el guion difiere del audio. Prueba la alineación proporcional. |
| El Word muestra una versión vieja | Word no recarga un archivo abierto que cambió en disco. Ciérralo y vuelve a abrirlo. |

## Estructura del proyecto

```
app.py                   # Punto de entrada: ventana de escritorio (pywebview) o navegador
servidor.py              # API local (FastAPI) que usa la interfaz
web/                     # Interfaz: index.html, estilos.css, app.js, traducir.js, iconos.js
alinear_timecodes.py     # Whisper + alineación + Word/SRT (también se usa por línea de comandos)
convertir_libreto.py     # Libreto tradicional / guion numerado / .srt / .ass → 3 columnas
hardware.py              # Detección de CPU, RAM y GPU
modelos.py               # Catálogo, descarga y recomendación de modelos de Whisper
cuda_runtime.py          # Descarga de cuBLAS/cuDNN para la GPU
motor_llm.py             # Motor de traducción: instala y levanta llama.cpp (llama-server)
modelos_traduccion.py    # Catálogo, descarga y recomendación de modelos de traducción
perfiles.py              # Perfiles de estilo y glosarios (importación desde Excel / estilo.md)
traductor.py             # Traducción por bloques con glosario y revisión
rutas.py, version.py     # Carpetas de datos y versión de la app
empaquetado/             # PyInstaller, Inno Setup, ícono y descarga del modelo incluido
.github/workflows/       # Compilación y publicación automática de releases
```
