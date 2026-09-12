import os
os.makedirs("build/debug", exist_ok=True)
"""Cut the Defect head out of scripts/形象.png (remove blue background/body, keep the golden head plate + eyes)."""
import numpy as np
from PIL import Image, ImageFilter, ImageDraw

SRC = "scripts/形象.png"
OUT = "app/assets/robot_head.png"
DBG = "build/debug/head_debug.png"

im = Image.open(SRC).convert("RGB")
hsv = np.array(im.convert("HSV")).astype(int)
H, S, V = hsv[..., 0], hsv[..., 1], hsv[..., 2]
# golden plate: hue ~ 25-55deg (PIL 0-255 scale => ~18-40), decent saturation & brightness
gold = (H >= 14) & (H <= 42) & (S >= 55) & (V >= 80)
gold_img = Image.fromarray((gold * 255).astype(np.uint8))
# close small gaps (outline strokes, cracks)
closed = gold_img.filter(ImageFilter.MaxFilter(7)).filter(ImageFilter.MinFilter(7))
# keep only the largest connected blob: flood from the biggest gold region
arr = np.array(closed) > 0
# label components by flood fill (simple BFS with scipy-free approach)
from collections import deque
lab = np.zeros(arr.shape, dtype=np.int32); cur = 0; sizes = {}
hh, ww = arr.shape
for y in range(hh):
    for x in range(ww):
        if arr[y, x] and lab[y, x] == 0:
            cur += 1; q = deque([(y, x)]); lab[y, x] = cur; n = 0
            while q:
                cy, cx = q.popleft(); n += 1
                for ny, nx in ((cy-1,cx),(cy+1,cx),(cy,cx-1),(cy,cx+1)):
                    if 0 <= ny < hh and 0 <= nx < ww and arr[ny, nx] and lab[ny, nx] == 0:
                        lab[ny, nx] = cur; q.append((ny, nx))
            sizes[cur] = n
big = max(sizes, key=sizes.get)
plate = (lab == big)
# fill holes (eyes, crack) : flood the complement from the image border
comp = ~plate
outside = np.zeros_like(comp); q = deque()
for y in range(hh):
    for x in (0, ww-1):
        if comp[y, x] and not outside[y, x]: outside[y, x] = True; q.append((y, x))
for x in range(ww):
    for y in (0, hh-1):
        if comp[y, x] and not outside[y, x]: outside[y, x] = True; q.append((y, x))
while q:
    cy, cx = q.popleft()
    for ny, nx in ((cy-1,cx),(cy+1,cx),(cy,cx-1),(cy,cx+1)):
        if 0 <= ny < hh and 0 <= nx < ww and comp[ny, nx] and not outside[ny, nx]:
            outside[ny, nx] = True; q.append((ny, nx))
head = ~outside
# include the dark outline ring: dilate by 4px but only accept dark-ish pixels (the ink outline), not bright blue bg
head_img = Image.fromarray((head * 255).astype(np.uint8))
dil = np.array(head_img.filter(ImageFilter.MaxFilter(9))) > 0
ring = dil & ~head
dark = (V < 110)
head2 = head | (ring & dark)
# smooth alpha
alpha = Image.fromarray((head2 * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.8))
rgba = im.convert("RGBA"); rgba.putalpha(alpha)
bbox = alpha.getbbox()
pad = 6
box = (max(0, bbox[0]-pad), max(0, bbox[1]-pad), min(ww, bbox[2]+pad), min(hh, bbox[3]+pad))
out = rgba.crop(box)
out.save(OUT)
# debug sheet: original | gold mask | result on checker
chk = Image.new("RGBA", out.size, (200, 200, 200, 255))
d = ImageDraw.Draw(chk)
for y in range(0, out.height, 16):
    for x in range(0, out.width, 16):
        if (x//16 + y//16) % 2 == 0: d.rectangle([x, y, x+15, y+15], fill=(120, 120, 120, 255))
chk.alpha_composite(out)
sheet = Image.new("RGB", (im.width + gold_img.width + chk.width + 40, max(im.height, chk.height) + 20), (30, 30, 30))
sheet.paste(im, (10, 10)); sheet.paste(gold_img.convert("RGB"), (im.width + 20, 10)); sheet.paste(chk.convert("RGB"), (im.width + gold_img.width + 30, 10))
sheet.save(DBG)
print("head size", out.size, "bbox", box)
