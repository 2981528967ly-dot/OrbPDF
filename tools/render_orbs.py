import os
os.makedirs("build/debug", exist_ok=True)
"""Re-draw the five Defect orbs as clean, number-free, high-resolution sprites.
Colours are sampled from the sprites in scripts/, geometry is procedural (sphere shading + rim + glow)."""
import os, math
import numpy as np
from PIL import Image

OUT = "app/assets/orbs"
SHEET = "build/debug/orbs_render.png"
SS = 2          # supersampling
SIZE = 256      # final size
R = 0.72        # sphere radius relative to half-size (leaves room for glow)

def smooth_noise(shape, scale, seed):
    rng = np.random.default_rng(seed)
    small = rng.random((shape[0] // scale + 2, shape[1] // scale + 2))
    img = Image.fromarray((small * 255).astype(np.uint8)).resize((shape[1], shape[0]), Image.BICUBIC)
    return np.asarray(img).astype(float) / 255.0

def render(key, base, light, shadow, rim, glow, style):
    n = SIZE * SS
    ys, xs = np.mgrid[0:n, 0:n]
    cx = cy = (n - 1) / 2
    x = (xs - cx) / (n / 2); y = (ys - cy) / (n / 2)
    d = np.sqrt(x * x + y * y) / R
    theta = np.arctan2(y, x)
    inside = d <= 1.0
    dd = np.clip(d, 0, 1)
    nz = np.sqrt(np.clip(1 - dd * dd, 0, 1))
    nx = np.where(inside, x / R, 0); ny = np.where(inside, y / R, 0)
    L = np.array([-0.45, -0.55, 0.70]); L /= np.linalg.norm(L)
    lam = np.clip(nx * L[0] + ny * L[1] + nz * L[2], 0, 1)
    # specular
    Hv = L + np.array([0, 0, 1.0]); Hv /= np.linalg.norm(Hv)
    spec = np.clip(nx * Hv[0] + ny * Hv[1] + nz * Hv[2], 0, 1) ** 40
    fres = (1 - nz) ** 2.2
    base = np.array(base, float); light = np.array(light, float); shadow = np.array(shadow, float); rim = np.array(rim, float); glow = np.array(glow, float)
    col = shadow[None, None, :] * (1 - lam[..., None]) + base[None, None, :] * lam[..., None]
    # texture styles
    if style == "crystal":
        facet = 0.5 + 0.5 * np.sin(theta * 5 + dd * 4.0)
        col = col * (0.88 + 0.22 * facet[..., None])
    elif style == "crackle":
        nse = smooth_noise((n, n), 10 * SS, 7)
        veins = np.clip((nse - 0.52) * 9, 0, 1)
        col = col * (1 - 0.35 * veins[..., None]) + light[None, None, :] * (0.45 * veins[..., None])
    elif style == "swirl":
        sw = 0.5 + 0.5 * np.sin(theta * 3 + dd * 7.0)
        col = col * (0.82 + 0.28 * sw[..., None])
    elif style == "pearl":
        # iridescent tints: pink lower-right, yellow top, blue-ish left
        pink = np.array([252, 205, 215.0]); yel = np.array([250, 245, 190.0]); blu = np.array([190, 225, 245.0])
        w1 = np.clip((x + y) * 0.9 + 0.3, 0, 1); w2 = np.clip(-y * 1.2, 0, 1); w3 = np.clip(-x * 1.1, 0, 1)
        tint = (pink * w1[..., None] + yel * w2[..., None] + blu * w3[..., None]) / np.clip(w1 + w2 + w3, 1e-3, None)[..., None]
        col = col * 0.55 + tint * 0.45 * lam[..., None] + col * 0.45 * (1 - lam[..., None])
    elif style == "ring":
        # dark body with luminous purple ring near the rim and a soft inner glow
        ringw = np.exp(-((dd - 0.86) ** 2) / (2 * 0.045 ** 2))
        inner = np.exp(-(dd ** 2) / (2 * 0.35 ** 2)) * 0.55
        col = col + rim[None, None, :] * ringw[..., None] * 0.95 + light[None, None, :] * inner[..., None]
    col = col + rim[None, None, :] * (fres[..., None] * 0.55) + light[None, None, :] * (spec[..., None] * 0.85)
    # secondary highlight spot (glassy)
    hx, hy = -0.32, -0.38
    spot = np.exp(-(((x / R) - hx) ** 2 + ((y / R) - hy) ** 2) / (2 * 0.12 ** 2))
    col = col + np.array([255, 255, 255.0])[None, None, :] * spot[..., None] * 0.55
    col = np.clip(col, 0, 255)
    # alpha: sphere + glow halo
    edge = np.clip((1.0 - d) * (SIZE * SS * R) * 0.5 + 0.5, 0, 1)
    halo = np.exp(-np.clip(d - 1.0, 0, None) * 7.0) * 0.55
    rgb = col * edge[..., None] + glow[None, None, :] * (1 - edge[..., None])
    alpha = np.clip(edge + (1 - edge) * halo, 0, 1)
    rgba = np.dstack([rgb, alpha * 255]).astype(np.uint8)
    im = Image.fromarray(rgba, "RGBA").resize((SIZE, SIZE), Image.LANCZOS)
    im.save(os.path.join(OUT, f"orb_{key}.png"))
    return im

ORBS = [
    # key      base            light            shadow          rim              glow            style
    ("blue",   (52, 201, 223), (190, 242, 255), (30, 90, 120),  (200, 245, 255), (90, 220, 255), "crystal"),
    ("white",  (236, 236, 232),(255, 255, 255), (150, 165, 185),(230, 240, 250), (220, 235, 255),"pearl"),
    ("purple", (34, 26, 58),   (110, 80, 170),  (14, 10, 28),   (168, 96, 220),  (150, 80, 220), "ring"),
    ("gold",   (222, 224, 140),(252, 252, 200), (120, 122, 60), (245, 240, 170), (240, 235, 120),"crackle"),
    ("green",  (60, 225, 205), (150, 255, 240), (25, 110, 100), (235, 195, 110), (90, 240, 220), "swirl"),
]
ims = [render(*o) for o in ORBS]
sheet = Image.new("RGBA", (SIZE * len(ims) + 20 * (len(ims) + 1), SIZE + 40), (14, 20, 36, 255))
x = 20
for im in ims:
    sheet.alpha_composite(im, (x, 20)); x += SIZE + 20
# also a light-background strip to check legibility
strip = Image.new("RGBA", sheet.size, (238, 242, 248, 255)); x = 20
for im in ims:
    strip.alpha_composite(im.resize((SIZE // 2, SIZE // 2), Image.LANCZOS), (x, 20)); x += SIZE + 20
full = Image.new("RGBA", (sheet.width, sheet.height * 2)); full.paste(sheet, (0, 0)); full.paste(strip, (0, sheet.height))
full.save(SHEET)
print("rendered", [o[0] for o in ORBS])
