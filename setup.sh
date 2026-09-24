#!/bin/bash
set -e
cd "$(dirname "$0")"

echo "============================================"
echo "  Guion con Time Codes - instalacion desde el codigo"
echo "============================================"
echo

if ! command -v python3 &> /dev/null; then
    echo "[ERROR] No se encontro Python 3 instalado."
    echo
    echo "Mac: instala desde https://python.org/downloads"
    echo "Linux: sudo apt install python3 python3-venv (o el gestor de tu distro)"
    exit 1
fi
echo "[1/3] Python encontrado."
echo

if [ ! -d "venv" ]; then
    echo "[2/3] Creando entorno virtual..."
    python3 -m venv venv
else
    echo "[2/3] El entorno virtual ya existe, se omite este paso."
fi
echo

echo "[3/3] Instalando dependencias (puede tardar varios minutos la primera vez)..."
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt
echo
echo "Descargando el modelo \"base\" de Whisper..."
python empaquetado/descargar_modelo.py base modelos_incluidos/base

echo
echo "============================================"
echo "  Listo! Para abrir la app: ./iniciar.sh"
echo
echo "  En Linux, si no se abre la ventana (faltan GTK o Qt),"
echo "  la app se abre sola en el navegador."
echo "============================================"
