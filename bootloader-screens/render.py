#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Render all A51 bootloader images from pure geometry + DejaVu fonts.

  python3 render.py OUTDIR
  Writes all 25 JPEGs flat into OUTDIR
  (boot: logo, letter, svb_orange, booting_warning; the rest is download mode).

No third-party artwork is used. Fonts: DejaVu Sans (Bitstream Vera / DejaVu license).
"""
import math, sys
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops

import os
FD = '/usr/share/fonts/truetype/dejavu/'
FONT = FD + 'DejaVuSans-ExtraLight.ttf'
def font(name, size): return ImageFont.truetype(FD + name, size)
BG = (0, 0, 0)
TEAL = [(0, 170, 160), (0, 200, 180), (120, 240, 220)]   # outer, middle, inner
CORE = (200, 255, 245)
GREY = (150, 150, 150)
SS = 4  # supersampling factor for anti-aliasing

def glow(layer, r, strength=1.0):
    g = layer.filter(ImageFilter.GaussianBlur(r))
    if strength != 1.0:
        g = g.point(lambda v: int(v * strength))
    return ImageChops.lighter(g, layer) if strength != 1.0 else ImageChops.add(g, layer)

def save(im, path):
    im = im.convert('RGB')
    im.info.clear()
    im.save(path, 'JPEG', quality=93, optimize=True, progressive=False, subsampling=0)

# ---- shared helpers -----------------------------------------------------------
def swirl(d, cx, cy, s=1.0, cols=TEAL, core=CORE):
    for i, (r, c) in enumerate(zip([210, 160, 110], cols)):
        r *= s; a = i * 40
        d.arc([cx - r, cy - r, cx + r, cy + r], a, a + 300, fill=c, width=max(3, round(14 * s)))
    k = 26 * s; d.ellipse([cx - k, cy - k, cx + k, cy + k], fill=core)

def ctext(d, cx, y, t, f, fill): d.text((cx - d.textlength(t, font=f) / 2, y), t, font=f, fill=fill)

def wrap(d, t, f, maxw):
    out, line = [], ''
    for w in t.split():
        c = (line + ' ' + w).strip()
        if d.textlength(c, font=f) <= maxw: line = c
        else: out.append(line); line = w
    return out + [line]

def para(d, x, y, t, f, fill, maxw, lh, center=None):
    for l in wrap(d, t, f, maxw):
        ctext(d, center, y, l, f, fill) if center else d.text((x, y), l, font=f, fill=fill)
        y += lh
    return y

def keys(d, x, y, rows, fs=42, lh=60):
    f = font('DejaVuSans.ttf', fs)
    for k, v in rows:
        d.text((x, y), k + ' : ', font=f, fill=LBL)
        d.text((x + d.textlength(k + ' : ', font=f), y), v, font=f, fill=WH)
        y += lh
    return y

ACC = (120, 240, 220); WH = (255, 255, 255); WH2 = (235, 235, 235); MUT = (150, 150, 150)
TBG = (33, 199, 197); LBL = (190, 250, 248); TITLE = (215, 253, 252)
LIGHT = [(170, 238, 236), (205, 246, 245), (240, 253, 253)]
M = 52

# ==== up_param (boot) ==========================================================
def logo(path):
    W, H, cx, cy = 1080, 2400, 540, 1100
    L = Image.new('RGB', (W, H), BG); swirl(ImageDraw.Draw(L), cx, cy)
    im = glow(L, 30); d = ImageDraw.Draw(im)
    ctext(d, cx, 1430, 'A51', font('DejaVuSans-ExtraLight.ttf', 64), GREY)
    save(im, path)

def letter(path):
    L = Image.new('RGB', (1080, 2400), BG); swirl(ImageDraw.Draw(L), 540, 1100)
    save(glow(L, 30), path)

def svb_orange(path):
    W, H = 936, 1800
    L = Image.new('RGB', (W, H), BG); swirl(ImageDraw.Draw(L), 468, 640, 0.32)
    im = glow(L, 10); d = ImageDraw.Draw(im)
    ctext(d, 468, 760, 'Bootloader unlocked', font('DejaVuSans.ttf', 52), ACC)
    for i, l in enumerate(['This software is not made', 'or supported by Samsung.']):
        ctext(d, 468, 860 + i * 58, l, font('DejaVuSans-ExtraLight.ttf', 38), WH2)
    fp = font('DejaVuSans.ttf', 34); t = 'Press power to continue'
    x0 = 468 - (d.textlength(t, font=fp) + 66) / 2; y = 1700
    d.ellipse([x0, y, x0 + 44, y + 44], outline=MUT, width=3)
    d.rectangle([x0 + 16, y - 10, x0 + 28, y + 12], fill=BG)
    d.line([x0 + 22, y - 8, x0 + 22, y + 20], fill=MUT, width=3)
    d.text((x0 + 66, y + 2), t, font=fp, fill=MUT)
    save(im, path)

def booting_warning(path):
    W, H = 936, 438
    L = Image.new('RGB', (W, H), BG); swirl(ImageDraw.Draw(L), 468, 95, 0.36)
    im = glow(L, 10); d = ImageDraw.Draw(im)
    ctext(d, 468, 225, 'Custom software', font('DejaVuSans.ttf', 44), ACC)
    ctext(d, 468, 300, 'This system is not signed by Samsung.', font('DejaVuSans-ExtraLight.ttf', 32), WH2)
    ctext(d, 468, 348, 'Samsung updates are not available.', font('DejaVuSans-ExtraLight.ttf', 32), WH2)
    save(im, path)

# ==== up_param_next (download mode) ===========================================
B = None; T = None
def _fonts():
    global B, T
    B = font('DejaVuSans.ttf', 42); T = font('DejaVuSans-ExtraLight.ttf', 72)

def teal(w, h): im = Image.new('RGB', (w, h), TBG); return im, ImageDraw.Draw(im)

def warning(path, h, rows):
    im, d = teal(1080, h); swirl(d, 540, 150, 0.45, LIGHT, WH)
    ctext(d, 540, 270, 'Custom OS', T, TITLE)
    y = para(d, M, 410, "You're about to install software that is not made or supported by Samsung. "
             "It may cause problems with the phone or apps.", B, WH, 1080 - 2 * M, 62)
    d.line([M, y + 30, 1080 - M, y + 30], fill=LBL, width=2)
    keys(d, M, y + 70, rows, 42, 68); save(im, path)

def sud(path, n):
    im, d = teal(303, 57); f = font('DejaVuSans.ttf', 36); t = f'USB Port #{n:02d}'
    d.text(((303 - d.textlength(t, font=f)) / 2, 6), t, font=f, fill=WH); save(im, path)

def secure_error(path):
    im, d = teal(930, 1014); swirl(d, 465, 140, 0.45, LIGHT, WH)
    ctext(d, 465, 265, 'Security error', T, TITLE)
    y = para(d, 0, 420, 'This phone is locked because unauthorized software was flashed.', B, WH, 800, 62, center=465)
    para(d, 0, y + 40, 'Contact your mobile operator or a service center for help. Repair may cost extra.',
         font('DejaVuSans.ttf', 38), WH, 800, 58, center=465)
    save(im, path)

def download_error(path):
    im, d = teal(729, 771); swirl(d, 364, 140, 0.45, LIGHT, WH)
    ctext(d, 364, 280, 'Update failed', font('DejaVuSans-ExtraLight.ttf', 64), TITLE)
    para(d, 0, 420, 'An error occurred while updating the device software.', B, WH, 640, 62, center=364)
    save(im, path)

def download(path):
    im, d = teal(1080, 1020); cx, cy = 540, 170
    d.ellipse([cx - 150, cy - 150, cx + 150, cy + 150], fill=(20, 150, 150)); swirl(d, cx, cy, 0.6, LIGHT, WH)
    ctext(d, 540, 360, 'Downloading…', T, TITLE)
    y = para(d, 0, 490, 'Keep the phone on and the USB cable connected until the update is finished.', B, WH, 880, 62, center=540)
    f = font('DejaVuSans.ttf', 38)
    ctext(d, 540, y + 60, 'Hold Volume down + Side key for 7 s', f, LBL)
    ctext(d, 540, y + 112, 'to cancel (restart phone)', f, WH)
    save(im, path)

def device_unlock(path):
    im, d = teal(1080, 1878); swirl(d, 540, 150, 0.45, LIGHT, WH)
    ctext(d, 540, 270, 'Unlock bootloader?', T, TITLE); W = 1080 - 2 * M
    y = para(d, M, 420, 'Unlocking lets you install a custom OS. Custom software is not tested by Samsung '
             'and may cause problems with the phone or apps.', B, WH, W, 62)
    y = para(d, M, y + 30, 'All personal data on this phone will be erased (factory data reset).',
             font('DejaVuSans-Bold.ttf', 42), WH, W, 62)
    d.line([M, y + 30, 1080 - M, y + 30], fill=LBL, width=2)
    y = keys(d, M, y + 70, [('Volume up', 'Yes')])
    y = para(d, M, y, 'Unlock bootloader and erase all data (may void warranty)', B, WH, W, 60) + 30
    y = keys(d, M, y, [('Volume down', 'No')])
    para(d, M, y, 'Keep bootloader locked and restart phone', B, WH, W, 60); save(im, path)

def device_lock(path):
    im, d = teal(1080, 1236); swirl(d, 540, 150, 0.45, LIGHT, WH)
    ctext(d, 540, 270, 'Lock bootloader?', T, TITLE); W = 1080 - 2 * M
    y = para(d, M, 420, 'Locking erases all photos, data and apps that are not backed up (factory data reset).',
             font('DejaVuSans-Bold.ttf', 42), WH, W, 62)
    y = para(d, M, y + 20, 'Only official Samsung software boots on a locked bootloader. Flash stock firmware first.', B, WH, W, 62)
    d.line([M, y + 30, 1080 - M, y + 30], fill=LBL, width=2)
    y = keys(d, M, y + 70, [('Volume up', 'Yes')])
    y = para(d, M, y, 'Lock bootloader and factory reset phone', B, WH, W, 60) + 30
    y = keys(d, M, y, [('Volume down', 'No')])
    para(d, M, y, 'Keep bootloader unlocked and restart phone', B, WH, W, 60); save(im, path)

def android_logo(path):
    """Original replacement icon: the set's swirl mark (no Android robot)."""
    N = 390; S = N * SS
    L = Image.new('RGB', (S, S), BG); swirl(ImageDraw.Draw(L), S / 2, S / 2, 0.62 * SS)
    L = L.resize((N, N), Image.LANCZOS); save(glow(L, 10, 0.45), path)

# 2) Settings gear: 7 flat-topped teeth with rounded corners --------------------
def setting_logo(path):
    N = 390; S = N * SS; c = S / 2
    M = Image.new('L', (S, S), 0); d = ImageDraw.Draw(M)
    teeth, r_body, r_tip = 7, 120 * SS, 160 * SS
    d.ellipse([c - r_body, c - r_body, c + r_body, c + r_body], fill=255)
    for k in range(teeth):
        a = 2 * math.pi * k / teeth - math.pi / 2
        hb, ht = math.radians(13), math.radians(8.5)   # half-width at base / at tip
        pts = [(c + (r_body - 10 * SS) * math.cos(a - hb), c + (r_body - 10 * SS) * math.sin(a - hb)),
               (c + r_tip * math.cos(a - ht), c + r_tip * math.sin(a - ht)),
               (c + r_tip * math.cos(a + ht), c + r_tip * math.sin(a + ht)),
               (c + (r_body - 10 * SS) * math.cos(a + hb), c + (r_body - 10 * SS) * math.sin(a + hb))]
        d.polygon(pts, fill=255)
    r_hole = 56 * SS
    d.ellipse([c - r_hole, c - r_hole, c + r_hole, c + r_hole], fill=0)
    # round every corner: blur the silhouette, then re-threshold
    M = M.filter(ImageFilter.GaussianBlur(9 * SS)).point(lambda v: 255 if v > 127 else 0)
    L = Image.new('RGB', (S, S), BG)
    L.paste(Image.new('RGB', (S, S), TEAL[1]), mask=M)
    d = ImageDraw.Draw(L); r_dot = 16 * SS
    d.ellipse([c - r_dot, c - r_dot, c + r_dot, c + r_dot], fill=CORE)
    L = L.resize((N, N), Image.LANCZOS)
    save(glow(L, 10, 0.45), path)

# 3) Off-mode charging: thin ring + angular bolt -------------------------------
def lpm(path):
    N = 528; S = N * SS; c = S / 2
    L = Image.new('RGB', (S, S), BG); d = ImageDraw.Draw(L)
    r = 210 * SS; w = 10 * SS
    d.ellipse([c - r, c - r, c + r, c + r], outline=(0, 70, 66), width=w)          # dim track
    d.arc([c - r, c - r, c + r, c + r], -90, 150, fill=TEAL[1], width=w)            # accent arc
    for ang in (-90, 150):                                                         # round caps
        a = math.radians(ang); rr = r - w / 2
        x, y = c + rr * math.cos(a), c + rr * math.sin(a)
        d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=TEAL[1])
    u = SS  # bolt drawn on a 1px grid around the centre
    bolt = [(18, -92), (-46, 10), (-4, 10), (-20, 92), (46, -14), (4, -14), (18, -92)]
    d.polygon([(c + x * u, c + y * u) for x, y in bolt], fill=TEAL[2])
    L = L.resize((N, N), Image.LANCZOS)
    save(glow(L, 12, 0.45), path)


if __name__ == '__main__':
    out = sys.argv[1] if len(sys.argv) > 1 else 'out'
    up = nx = out
    os.makedirs(out, exist_ok=True); _fonts()
    for fn in (logo, letter, svb_orange, booting_warning): fn(os.path.join(up, fn.__name__ + '.jpg'))
    p = lambda n: os.path.join(nx, n)
    warning(p('warning_svb.jpg'), 1893, [('Volume up', 'Continue'), ('Volume up long press', 'Device unlock mode'),
                                         ('Volume down', 'Cancel (restart phone)')])
    warning(p('warning.jpg'), 1890, [('Volume up', 'Continue'), ('Volume down', 'Cancel (restart phone)'),
                                     ('Side key', 'Show barcode')])
    for n in range(11): sud(p(f'SUD_{n}.jpg'), n)
    for fn in (setting_logo, secure_error, lpm, download_error, download, device_unlock, device_lock, android_logo):
        fn(p(fn.__name__ + '.jpg'))
    print('done:', out)
