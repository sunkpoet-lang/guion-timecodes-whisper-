@echo off
setlocal

echo ============================================
echo   Configuracion automatica del proyecto
echo ============================================
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
echo [1/4] Python encontrado.
echo.

if not exist venv (
    echo [2/4] Creando entorno virtual...
    python -m venv venv
) else (
    echo [2/4] El entorno virtual ya existe, se omite este paso.
)
echo.

echo [3/4] Instalando dependencias (puede tardar varios minutos la primera vez)...
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

where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo [4/4] ffmpeg no encontrado. Intentando instalar con winget...
    winget install ffmpeg --accept-source-agreements --accept-package-agreements
    echo.
    echo Si la instalacion de winget fallo, instala ffmpeg manualmente desde:
    echo https://ffmpeg.org/download.html
) else (
    echo [4/4] ffmpeg ya esta instalado.
)

echo.
echo ============================================
echo   Listo! Para usar el proyecto:
echo.
echo   1. Doble clic en iniciar_time_codes.bat
echo      (genera Time Codes con Whisper a partir de un video)
echo.
echo   2. Doble clic en iniciar_convertir_libreto.bat
echo      (convierte un libreto tradicional a 3 columnas)
echo.
echo   Puedes tener ambas ventanas abiertas al mismo tiempo.
echo ============================================
pause
