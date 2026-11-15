"""Erzeugt die PNG-Icons fuer Handy-Startbildschirme aus denselben Massen wie web/symbol.svg (Entwurf A, Kalenderblatt).

    python deploy/icon_png.py      -> web/symbol-180.png (Apple, ohne runde Ecken: iOS rundet selbst), web/symbol-192.png

Braucht Pillow (nur beim Entwickeln; die fertigen PNGs liegen im Repo).
"""
import os

from PIL import Image, ImageDraw

BLAU, GELB, WEISS = (0, 99, 156), (248, 180, 66), (255, 255, 255)
WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")


def zeichnen(groesse, ecke=7.0):
    f = 16                               # in 16-facher Groesse zeichnen, dann verkleinern (glatte Kanten)
    s = groesse * f / 32.0
    bild = Image.new("RGBA", (groesse * f, groesse * f), (0, 0, 0, 0))
    d = ImageDraw.Draw(bild)
    k = lambda *w: [round(x * s) for x in w]   # noqa: E731
    d.rounded_rectangle(k(0, 0, 32, 32), radius=round(ecke * s), fill=BLAU)
    d.rounded_rectangle(k(5.5, 7.5, 26.5, 26.5), radius=round(3 * s), fill=WEISS)
    d.rounded_rectangle(k(5.5, 7.5, 26.5, 12.5), radius=round(3 * s), fill=GELB)
    d.rectangle(k(5.5, 10, 26.5, 12.5), fill=GELB)
    for x in (9.5, 19.9):   # Ringe: blauer Rand 1.2 um weisse Pille
        d.rounded_rectangle(k(x - 0.6, 3.9, x + 3.2, 11.1), radius=round(1.9 * s), fill=BLAU)
        d.rounded_rectangle(k(x, 4.5, x + 2.6, 10.5), radius=round(1.3 * s), fill=WEISS)
    d.polygon([tuple(k(10, 24)), tuple(k(23.5, 15)), tuple(k(23.5, 24))], fill=BLAU)
    return bild.resize((groesse, groesse), Image.LANCZOS)


if __name__ == "__main__":
    zeichnen(180, ecke=0).convert("RGB").save(os.path.join(WEB, "symbol-180.png"), optimize=True)
    zeichnen(192).save(os.path.join(WEB, "symbol-192.png"), optimize=True)
    print("web/symbol-180.png und web/symbol-192.png geschrieben")
