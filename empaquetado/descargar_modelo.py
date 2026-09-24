# -*- coding: utf-8 -*-
"""
Descarga un modelo del catálogo a una carpeta, sin abrir la app.

    python empaquetado/descargar_modelo.py base modelos_incluidos/base

Lo usan setup.bat / setup.sh (para que la instalación desde el código ya
tenga el modelo "base") y el flujo de GitHub Actions (para meterlo dentro
del instalador).
"""

import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modelos import ARCHIVOS_MODELO, POR_ID  # noqa: E402


def descargar(id_modelo, destino):
    repo = POR_ID[id_modelo]["repo"]
    if os.path.isfile(os.path.join(destino, "model.bin")):
        print(f"El modelo '{id_modelo}' ya está en {destino}.")
        return
    os.makedirs(destino, exist_ok=True)
    for nombre in ARCHIVOS_MODELO:
        url = f"https://huggingface.co/{repo}/resolve/main/{nombre}"
        try:
            with urllib.request.urlopen(url, timeout=60) as r, open(os.path.join(destino, nombre), "wb") as f:
                while True:
                    bloque = r.read(1024 * 1024)
                    if not bloque:
                        break
                    f.write(bloque)
            print(f"  {nombre}")
        except urllib.error.HTTPError as e:
            if e.code != 404:  # cada repo trae solo algunos de los archivos posibles
                raise
    print(f"Modelo '{id_modelo}' descargado en {destino}.")


if __name__ == "__main__":
    descargar(sys.argv[1], sys.argv[2])
