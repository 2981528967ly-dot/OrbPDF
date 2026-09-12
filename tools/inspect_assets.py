"""Inspect the provided sprites: upscale contact sheet + colour sampling."""
import os
os.makedirs("build/debug", exist_ok=True)
from PIL import Image

SRC = "scripts"
OUT = "build/debug"
names = ["晶蓝", "珍珠白", "紫黑", "金黄", "青绿"]
tiles = []
for n in names:
    im = Image.open(os.path.join(SRC, n + ".png")).convert("RGB")
    big = im.resize((im.width * 6, im.height * 6), Image.NEAREST)
    tiles.append(big)
W = sum(t.width for t in tiles) + 20 * (len(tiles) + 1)
H = max(t.height for t in tiles) + 40
sheet = Image.new("RGB", (W, H), (40, 40, 40))
x = 20
for t in tiles:
    sheet.paste(t, (x, 20)); x += t.width + 20
sheet.save(os.path.join(OUT, "orbs_sheet.png"))

# colour sampling: coloured pixels only (exclude greys/whites of the digits and near-black bg)
for n in names:
    im = Image.open(os.path.join(SRC, n + ".png")).convert("RGB")
    hsv = im.convert("HSV")
    px = im.load(); ph = hsv.load()
    cols = []
    for y in range(im.height):
        for x in range(im.width):
            h, s, v = ph[x, y]
            if v > 70 and s > 60:
                cols.append((h, s, v, px[x, y]))
    cols.sort(key=lambda c: c[2])
    if not cols:
        print(n, "no coloured px"); continue
    hs = sorted(c[0] for c in cols)
    med_h = hs[len(hs) // 2]
    q = lambda f: cols[int(f * (len(cols) - 1))][3]
    print(f"{n}: n={len(cols)} medianH={med_h*360//255}deg  shadow={q(0.15)} mid={q(0.5)} light={q(0.9)} top={q(0.99)}")
try:
    import numpy; print("numpy", numpy.__version__)
except Exception as e:
    print("no numpy:", e)
