"""Generate app.ico and splash.png from the robot head (run before PyInstaller)."""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "app" / "assets"


def make_icon() -> Path:
    head = Image.open(ASSETS / "robot_head.png").convert("RGBA")
    out = ASSETS / "app.ico"
    frames = []
    for size in (256, 128, 64, 48, 32, 16):
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        # dark circular backdrop so the head reads at tiny sizes
        d = ImageDraw.Draw(canvas)
        d.ellipse([0, 0, size - 1, size - 1], fill=(10, 15, 28, 255))
        inner = int(size * 0.82)
        h = head.copy()
        h.thumbnail((inner, inner), Image.LANCZOS)
        canvas.alpha_composite(h, ((size - h.width) // 2, (size - h.height) // 2))
        frames.append(canvas)
    frames[0].save(out, format="ICO", sizes=[(f.width, f.height) for f in frames], append_images=frames[1:])
    return out


def _font(size: int) -> ImageFont.FreeTypeFont:
    for name in ("msyhbd.ttc", "msyh.ttc", "simhei.ttf", "arial.ttf"):
        p = Path(r"C:\Windows\Fonts") / name
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size)
            except Exception:
                continue
    return ImageFont.load_default()


def make_splash() -> Path:
    W, H = 460, 280
    img = Image.new("RGBA", (W, H), (10, 15, 28, 255))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, W - 1, H - 1], radius=14, outline=(47, 62, 92, 255), width=1)
    # soft glow behind the head
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([40, 30, 220, 210], fill=(90, 216, 255, 40))
    from PIL import ImageFilter
    glow = glow.filter(ImageFilter.GaussianBlur(24))
    img.alpha_composite(glow)
    head = Image.open(ASSETS / "robot_head.png").convert("RGBA")
    head.thumbnail((150, 150), Image.LANCZOS)
    img.alpha_composite(head, (56, 50))
    d = ImageDraw.Draw(img)
    d.text((236, 78), "OrbPDF", font=_font(38), fill=(228, 236, 247, 255))
    d.text((238, 128), "全能 PDF 工作台", font=_font(18), fill=(180, 191, 210, 255))
    d.text((238, 160), "正在解压组件，马上就好…", font=_font(13), fill=(127, 140, 165, 255))
    out = ASSETS / "splash.png"
    img.convert("RGB").save(out)
    return out


if __name__ == "__main__":
    print("icon:", make_icon())
    print("splash:", make_splash())
