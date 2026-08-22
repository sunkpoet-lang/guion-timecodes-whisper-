#!/bin/bash
set -e

echo "============================================"
echo "  Configuracion automatica del proyecto"
echo "============================================"
echo

if ! command -v python3 &> /dev/null; then
    echo "[ERROR] No se encontro Python 3 instalado."
    echo
    echo "Mac: instala desde https://python.org/downloads"
    echo "Linux: sudo apt install python3 python3-venv (o el gestor de tu distro)"
    exit 1
fi
echo "[1/4] Python encontrado."
echo

if [ ! -d "venv" ]; then
    echo "[2/4] Creando entorno virtual..."
    python3 -m venv venv
else
    echo "[2/4] El entorno virtual ya existe, se omite este paso."
fi
echo

echo "[3/4] Instalando dependencias (puede tardar varios minutos la primera vez)..."
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt
echo

if ! command -v ffmpeg &> /dev/null; then
    echo "[4/4] ffmpeg no encontrado."
    if command -v brew &> /dev/null; then
        echo "Instalando con Homebrew..."
        brew install ffmpeg
    elif command -v apt &> /dev/null; then
        echo "Instalando con apt (puede pedir tu contraseña)..."
        sudo apt install -y ffmpeg
    else
        echo "Instala ffmpeg manualmente: https://ffmpeg.org/download.html"
    fi
else
    echo "[4/4] ffmpeg ya esta instalado."
fi

echo
echo "============================================"
echo "  Listo! Para usar el proyecto:"
echo
echo "  1. ./iniciar_time_codes.sh"
echo "     (genera Time Codes con Whisper a partir de un video)"
echo
echo "  2. ./iniciar_convertir_libreto.sh"
echo "     (convierte un libreto tradicional a 3 columnas)"
echo
echo "  Puedes correr ambos al mismo tiempo, cada uno en su propia terminal."
echo "============================================"
