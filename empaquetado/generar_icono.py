# -*- coding: utf-8 -*-
"""
Dibuja el ícono de la app (cuadro redondeado con degradado y una onda de audio)
y lo guarda como web/icono.png y empaquetado/icono.ico.

    python empaquetado/generar_icono.py

Solo hace falta correrlo si se cambia el diseño; los archivos generados ya
están en el repositorio.
"""

import os

from PIL import Image, ImageDraw

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)

LADO = 1024  # se dibuja grande y se reduce, para bordes suaves
COLOR_A = (123, 140, 255)
COLOR_B = (176, 123, 255)
BARRAS = [0.22, 0.46, 0.78, 0.40, 0.62, 0.24]  # altura relativa de cada barra de la onda


def dibujar():
    degradado = Image.new("RGBA", (LADO, LADO))
    px = degradado.load()
    for y in range(LADO):
        for x in range(LADO):
            t = (x + y) / (2 * LADO - 2)
            px[x, y] = tuple(round(a + (b - a) * t) for a, b in zip(COLOR_A, COLOR_B)) + (255,)

    mascara = Image.new("L", (LADO, LADO), 0)
    margen = 56
    ImageDraw.Draw(mascara).rounded_rectangle((margen, margen, LADO - margen, LADO - margen), radius=220, fill=255)

    icono = Image.new("RGBA", (LADO, LADO), (0, 0, 0, 0))
    icono.paste(degradado, (0, 0), mascara)

    d = ImageDraw.Draw(icono)
    ancho_barra, separacion = 70, 50
    total = len(BARRAS) * ancho_barra + (len(BARRAS) - 1) * separacion
    x = (LADO - total) / 2
    for h in BARRAS:
        alto = h * (LADO - 2 * margen)
        y0 = (LADO - alto) / 2
        d.rounded_rectangle((x, y0, x + ancho_barra, y0 + alto), radius=ancho_barra / 2, fill=(255, 255, 255, 255))
        x += ancho_barra + separacion
    return icono


if __name__ == "__main__":
    icono = dibujar()
    icono.resize((256, 256), Image.LANCZOS).save(os.path.join(RAIZ, "web", "icono.png"))
    icono.resize((512, 512), Image.LANCZOS).save(os.path.join(AQUI, "icono.png"))
    icono.save(os.path.join(AQUI, "icono.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("Íconos generados.")
