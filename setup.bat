@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo   Guion con Time Codes - instalacion desde el codigo
echo ============================================
echo.
echo Si solo quieres usar la app, es mas facil descargar el instalador:
echo https://github.com/sunkpoet-lang/guion-timecodes-whisper-/releases
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] No se encontro Python instalado.
    echo.
    echo Descargalo desde https://python.org/downloads e instalalo.
    echo IMPORTANTE: marca la casilla "Add Python to PATH" durante la instalacion.
    echo Luego vuelve a correr este archivo.
    pause
    exit /b 1
)
echo [1/3] Python encontrado.
echo.

if not exist venv (
    echo [2/3] Creando entorno virtual...
    python -m venv venv
) else (
    echo [2/3] El entorno virtual ya existe, se omite este paso.
)
echo.

echo [3/3] Instalando dependencias (puede tardar varios minutos la primera vez)...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip >nul
pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [ERROR] Fallo la instalacion de dependencias. Revisa el mensaje de arriba.
    pause
    exit /b 1
)
echo.
echo Descargando el modelo "base" de Whisper...
python empaquetado\descargar_modelo.py base modelos_incluidos\base

echo.
echo ============================================
echo   Listo! Para abrir la app: doble clic en iniciar.bat
echo.
echo   La GPU (NVIDIA) y los modelos mas precisos se
echo   activan desde la app, en "Modelos y equipo".
echo ============================================
pause
