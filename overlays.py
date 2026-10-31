"""HomeView pop-ups drawn on the Mac with the real San Francisco fonts and real frosted Liquid Glass.

Every pop-up is a small opaque sprite: the exact patch of the current screen behind it, blurred, tinted and lit like
Apple's glass, plus a soft shadow, a bright rim and the content. The iMac only places the sprite, so the G4 never has
to blur anything or own Apple's fonts. Sizes are in 1024x768 screen pixels.
"""
import math, re
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont
from homeview_config import CONFIG

ASSISTANT = CONFIG['assistant']['name']

W, H = 1024, 768
SS = 4                       # supersampling for smooth shapes
FONT = '/System/Library/Fonts/SFNS.ttf'
FONT_R = '/System/Library/Fonts/SFNSRounded.ttf'
ORANGE = (255, 159, 10)
_fonts = {}


def font(size, weight=400, rounded=False):
    key = (size, weight, rounded)
    if key not in _fonts:
        f = ImageFont.truetype(FONT_R if rounded else FONT, size)
        try:
            axes = f.get_variation_axes()
            vals = []
            for a in axes:
                n = a['name'] if isinstance(a['name'], str) else a['name'].decode()
                vals.append(weight if n == 'Weight' else min(a['maximum'], max(a['minimum'], size)) if n == 'Optical Size' else a['default'])
            f.set_variation_by_axes(vals)
        except Exception:
            pass
        _fonts[key] = f
    return _fonts[key]


def text_w(t, f):
    return f.getlength(t)


def wrap(t, f, max_w, max_lines):
    words, lines, cur = t.split(), [], ''
    for w in words:
        trial = (cur + ' ' + w).strip()
        if text_w(trial, f) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur); cur = w
        if len(lines) == max_lines:
            break
    if len(lines) < max_lines and cur:
        lines.append(cur)
    used = ' '.join(lines).split()
    if len(used) < len(words) and lines:
        last = lines[-1]
        while text_w(last + '…', f) > max_w and ' ' in last:
            last = last.rsplit(' ', 1)[0]
        lines[-1] = last.rstrip(',.;:') + '…'
    return lines


def rr_mask(size, radius):
    """Anti-aliased rounded-rectangle mask (continuous-corner look via supersampling)."""
    w, h = size
    m = Image.new('L', (w * SS, h * SS), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w * SS - 1, h * SS - 1), radius=radius * SS, fill=255)
    return m.resize((w, h), Image.LANCZOS)


def rim(size, radius, top=150, rest=46, width=1.4):
    """The bright edge of Liquid Glass: strong along the top, faint elsewhere."""
    w, h = size
    layer = Image.new('L', (w * SS, h * SS), 0)
    ImageDraw.Draw(layer).rounded_rectangle((0, 0, w * SS - 1, h * SS - 1), radius=radius * SS, outline=255, width=int(width * SS))
    layer = layer.resize((w, h), Image.LANCZOS)
    grad = Image.linear_gradient('L').resize((w, h)).point(lambda v: int(top - (top - rest) * min(1, v / 255 * 2.2)))
    return Image.composite(grad, Image.new('L', (w, h), 0), layer).point(lambda v: v)


def glass(base, rect, radius, tint=(22, 22, 26), tint_a=0.42, blur=20, margin=30):
    """Return (sprite, sprite_rect, inner_offset): the glass panel over its real background, shadow included."""
    x, y, w, h = rect
    sx0, sy0 = max(0, x - margin), max(0, y - margin)
    sx1, sy1 = min(W, x + w + margin), min(H, y + h + margin)
    sprite = base.crop((sx0, sy0, sx1, sy1)).convert('RGB')
    ox, oy = x - sx0, y - sy0
    # soft shadow under the panel
    sh = Image.new('L', sprite.size, 0)
    ImageDraw.Draw(sh).rounded_rectangle((ox, oy + 8, ox + w, oy + h + 8), radius=radius, fill=95)
    sh = sh.filter(ImageFilter.GaussianBlur(14))
    sprite = Image.composite(Image.new('RGB', sprite.size, (0, 0, 0)), sprite, sh)
    # frosted panel: blur what is behind it, deepen colour, darken a little, tint, then light it from the top
    pad = blur * 2
    region = base.crop((max(0, x - pad), max(0, y - pad), min(W, x + w + pad), min(H, y + h + pad))).convert('RGB')
    region = region.filter(ImageFilter.GaussianBlur(blur))
    region = ImageEnhance.Color(region).enhance(1.35)
    region = ImageEnhance.Brightness(region).enhance(0.9)
    px, py = x - max(0, x - pad), y - max(0, y - pad)
    panel = region.crop((px, py, px + w, py + h))
    panel = Image.blend(panel, Image.new('RGB', (w, h), tint), tint_a)
    sheen = Image.linear_gradient('L').resize((w, h)).point(lambda v: int(max(0, 34 - v * 0.22)))
    panel = Image.composite(Image.new('RGB', (w, h), (255, 255, 255)), panel, sheen)
    mask = rr_mask((w, h), radius)
    sprite.paste(panel, (ox, oy), mask)
    edge = rim((w, h), radius)
    sprite.paste(Image.new('RGB', (w, h), (255, 255, 255)), (ox, oy), edge)
    return sprite.convert('RGBA'), (sx0, sy0, sx1 - sx0, sy1 - sy0), (ox, oy)


# ---------------- icons ----------------
def squircle_icon(size, top, bottom, glyph):
    S = size * SS
    g = Image.new('RGB', (S, S))
    for yy in range(S):
        t = yy / (S - 1)
        ImageDraw.Draw(g).line([(0, yy), (S, yy)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    m = Image.new('L', (S, S), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, S - 1, S - 1), radius=int(S * 0.235), fill=255)
    d = ImageDraw.Draw(g)
    glyph(d, S)
    icon = Image.new('RGBA', (S, S)); icon.paste(g, (0, 0), m)
    return icon.resize((size, size), Image.LANCZOS)


def g_sparkle(d, S):
    c = S / 2
    def star(cx, cy, r, k=0.18):
        pts = []
        for i in range(8):
            a = math.pi / 4 * i - math.pi / 2
            rr = r if i % 2 == 0 else r * k
            pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
        d.polygon(pts, fill='white')
    star(c * 0.92, c * 1.05, S * 0.30); star(c * 1.42, c * 0.62, S * 0.12)


def g_house(d, S):
    w = S * 0.07
    d.line([(S * .2, S * .52), (S * .5, S * .26), (S * .8, S * .52)], fill='white', width=int(w), joint='curve')
    d.rounded_rectangle((S * .29, S * .48, S * .71, S * .76), radius=S * .04, outline='white', width=int(w))


def g_box(d, S):
    w = int(S * 0.06)
    top = [(S * .5, S * .22), (S * .78, S * .36), (S * .5, S * .5), (S * .22, S * .36)]
    d.polygon(top, outline='white', width=w)
    d.line([(S * .22, S * .36), (S * .22, S * .66), (S * .5, S * .8), (S * .78, S * .66), (S * .78, S * .36)], fill='white', width=w, joint='curve')
    d.line([(S * .5, S * .5), (S * .5, S * .8)], fill='white', width=w)


def g_car(d, S):
    d.rounded_rectangle((S * .17, S * .45, S * .83, S * .68), radius=S * .07, fill='white')
    d.polygon([(S * .29, S * .46), (S * .36, S * .3), (S * .64, S * .3), (S * .71, S * .46)], fill='white')
    for cx in (S * .31, S * .69):
        d.ellipse((cx - S * .07, S * .62, cx + S * .07, S * .76), fill='white')


def g_timer(d, S):
    w = int(S * 0.075)
    d.ellipse((S * .24, S * .27, S * .76, S * .79), outline='white', width=w)
    d.line([(S * .5, S * .53), (S * .5, S * .38)], fill='white', width=w)
    d.line([(S * .41, S * .17), (S * .59, S * .17)], fill='white', width=w)
    d.line([(S * .5, S * .17), (S * .5, S * .27)], fill='white', width=w)


def g_bell(d, S):
    c = S / 2
    d.chord((S * .27, S * .2, S * .73, S * .66), 180, 360, fill='white')          # dome
    d.polygon([(S * .27, S * .43), (S * .73, S * .43), (S * .79, S * .66), (S * .21, S * .66)], fill='white')
    d.rounded_rectangle((S * .17, S * .63, S * .83, S * .7), radius=S * .035, fill='white')   # lip
    d.ellipse((c - S * .075, S * .71, c + S * .075, S * .82), fill='white')       # clapper
    d.ellipse((c - S * .04, S * .14, c + S * .04, S * .22), fill='white')         # top knob


GLYPHS = __import__('pathlib').Path(__file__).resolve().parent / 'static' / 'icons' / 'png'   # tools/icons.py (Framework7 Icons, MIT)
ICONS = {
    'door': ((255, 190, 60), (255, 132, 0), 'bell'),
    'muse': ((172, 124, 255), (255, 102, 196), 'sparkles'),
    'home': ((255, 196, 64), (255, 122, 0), 'house'),
    'package': ((214, 160, 96), (150, 96, 46), 'box'),
    'car': ((255, 76, 76), (204, 20, 32), 'car'),
    'timer': ((255, 178, 46), (255, 128, 0), 'timer'),
    'camera': ((90, 200, 250), (0, 122, 255), 'camera'),
    'intercom': ((255, 190, 60), (255, 132, 0), 'intercom'),
    'cook': ((255, 120, 80), (230, 60, 40), 'cook'),
}
_icons = {}


def icon(kind, size):
    key = (kind, size)
    if key not in _icons:
        top, bottom, glyph = ICONS.get(kind, ICONS['muse'])
        base = squircle_icon(size, top, bottom, lambda d, S: None)
        g = Image.open(GLYPHS / (glyph + '.png')).convert('RGBA')
        gs = int(size * 0.62); g = g.resize((gs, gs), Image.LANCZOS)
        base.alpha_composite(g, ((size - gs) // 2, (size - gs) // 2))
        _icons[key] = base
    return _icons[key].copy()


def orb(size):
    """A Siri-like orb: soft coloured light inside a glass bead."""
    S = size * SS
    o = Image.new('RGB', (S, S), (18, 12, 40))
    for col, cx, cy, r in (((255, 92, 170), .34, .38, .42), ((255, 170, 80), .66, .34, .34), ((90, 150, 255), .62, .68, .44), ((170, 96, 255), .32, .7, .36)):
        blob = Image.new('L', (S, S), 0)
        ImageDraw.Draw(blob).ellipse((S * (cx - r), S * (cy - r), S * (cx + r), S * (cy + r)), fill=235)
        blob = blob.filter(ImageFilter.GaussianBlur(S * 0.12))
        o = Image.composite(Image.new('RGB', (S, S), col), o, blob)
    hl = Image.new('L', (S, S), 0)
    ImageDraw.Draw(hl).ellipse((S * .22, S * .12, S * .62, S * .42), fill=120)
    o = Image.composite(Image.new('RGB', (S, S), (255, 255, 255)), o, hl.filter(ImageFilter.GaussianBlur(S * 0.05)))
    m = Image.new('L', (S, S), 0); ImageDraw.Draw(m).ellipse((0, 0, S - 1, S - 1), fill=255)
    out = Image.new('RGBA', (S, S)); out.paste(o, (0, 0), m)
    return out.resize((size, size), Image.LANCZOS)


def ring(d, cx, cy, r, frac, width, color, track):
    box = (cx - r, cy - r, cx + r, cy + r)
    d.ellipse(box, outline=track, width=width)
    if frac > 0:
        d.arc(box, -90, -90 + 360 * frac, fill=color, width=width)


def mono_digits(d, x_right, y, s, f, fill):
    """Draw a time like 4:59 with fixed-width digits (tabular figures), right-aligned at x_right."""
    cell = max(text_w(c, f) for c in '0123456789'); colon = text_w(':', f)
    widths = [colon if c == ':' else cell for c in s]
    x = x_right - sum(widths)
    for c, cw in zip(s, widths):
        d.text((x + (cw - text_w(c, f)) / 2, y), c, font=f, fill=fill)
        x += cw


def _put(layer, im, xy):
    x, y = int(round(xy[0])), int(round(xy[1]))
    layer.alpha_composite(im, (x, y))


# ---------------- pop-ups ----------------
def banner(base, app, title, body, kind, y=14):
    w = 580; pad = 16; isz = 44
    fb, ft, fs = font(19, 590), font(19, 400), font(15, 500)
    lines = wrap(body, ft, w - pad * 3 - isz, 2)
    h = pad + 24 + 2 + 24 * len(lines) + pad - 2
    rect = ((W - w) // 2, y, w, h)
    base_sprite, srect, (ox, oy) = glass(base, rect, 26)
    sprite = Image.new('RGBA', base_sprite.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(sprite)
    ic = icon(kind, isz); _put(sprite, ic, (ox + pad, oy + (h - isz) // 2))
    tx = ox + pad * 2 + isz
    d.text((tx, oy + pad - 2), title, font=fb, fill=(255, 255, 255))
    d.text((ox + w - pad - text_w('now', fs), oy + pad + 1), 'now', font=fs, fill=(235, 235, 245, 150))
    for i, ln in enumerate(lines):
        d.text((tx, oy + pad + 24 + i * 24), ln, font=ft, fill=(242, 242, 247))
    return Image.alpha_composite(base_sprite, sprite).convert('RGB'), srect


def timer_capsule(base, label, remaining, total, y=14, x=None):
    w, h = 330, 62
    rect = ((W - w) // 2 if x is None else x, y, w, h)
    base_sprite, srect, (ox, oy) = glass(base, rect, h // 2, tint=(14, 14, 16), tint_a=0.55)
    sprite = Image.new('RGBA', base_sprite.size, (0, 0, 0, 0))
    big = Image.new('RGBA', (w * SS, h * SS), (0, 0, 0, 0)); bd = ImageDraw.Draw(big)
    frac = max(0.0, min(1.0, remaining / total)) if total else 0
    ring(bd, 34 * SS, h * SS // 2, 17 * SS, frac, int(4.5 * SS), ORANGE + (255,), (255, 159, 10, 64))
    big = big.resize((w, h), Image.LANCZOS)
    _put(sprite, big, (ox, oy))
    d = ImageDraw.Draw(sprite)
    name = (label or 'Timer').replace(' timer', '')
    name = name[:1].upper() + name[1:]
    fl, fsub = font(18, 590), font(14, 500)
    d.text((ox + 64, oy + 11), name if text_w(name, fl) < 120 else wrap(name, fl, 120, 1)[0], font=fl, fill=(255, 255, 255))
    d.text((ox + 64, oy + 34), 'Timer', font=fsub, fill=(235, 235, 245, 140))
    s = int(math.ceil(max(0, remaining))); hh, rem = divmod(s, 3600); mm, ss = divmod(rem, 60)
    txt = f'{hh}:{mm:02d}:{ss:02d}' if hh else f'{mm}:{ss:02d}'
    mono_digits(d, ox + w - 22, oy + 9, txt, font(36, 600), ORANGE)
    return Image.alpha_composite(base_sprite, sprite).convert('RGB'), srect


def alarm_card(base, label, pulse=0.0):
    w, h = 480, 318
    rect = ((W - w) // 2, (H - h) // 2 - 10, w, h)
    base_sprite, srect, (ox, oy) = glass(base, rect, 44, tint=(14, 14, 16), tint_a=0.6, blur=24)
    sprite = Image.new('RGBA', base_sprite.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(sprite)
    ic = icon('timer', 64); _put(sprite, ic, (ox + (w - 64) // 2, oy + 30))
    name = (label or 'Timer').replace(' timer', '')
    title = name[:1].upper() + name[1:] + ' Timer'
    ft, fsub, fbtn, fhint = font(30, 650), font(19, 400), font(22, 620), font(15, 500)
    d.text((ox + (w - text_w(title, ft)) / 2, oy + 108), title, font=ft, fill=(255, 255, 255))
    sub = "Time's up"
    d.text((ox + (w - text_w(sub, fsub)) / 2, oy + 150), sub, font=fsub, fill=(235, 235, 245, 165))
    bw, bh = 300, 58; bx, by = ox + (w - bw) // 2, oy + 196
    btn = Image.new('RGBA', (bw * SS, bh * SS), (0, 0, 0, 0))
    ImageDraw.Draw(btn).rounded_rectangle((0, 0, bw * SS - 1, bh * SS - 1), radius=bh * SS // 2, fill=(255, 149 + int(14 * pulse), 0, 255))
    btn = btn.resize((bw, bh), Image.LANCZOS); _put(sprite, btn, (bx, by))
    d.text((bx + (bw - text_w('Stop', fbtn)) / 2, by + 14), 'Stop', font=fbtn, fill=(255, 255, 255))
    hint = 'Say “stop”'
    d.text((ox + (w - text_w(hint, fhint)) / 2, by + bh + 14), hint, font=fhint, fill=(235, 235, 245, 120))
    return Image.alpha_composite(base_sprite, sprite).convert('RGB'), srect


def door_card(base, title, sub, snap_path, stamp=None):
    """Doorbell: Home-app style glass card, top centre, with the camera snapshot (or a placeholder)."""
    w, pad, isz = 620, 18, 46
    iw = w - pad * 2
    snap = None
    try:
        if snap_path:
            snap = Image.open(snap_path).convert('RGB')
    except Exception:
        snap = None
    ih = min(380, int(iw * snap.height / snap.width)) if snap else 300
    h = pad + isz + 14 + ih + pad
    rect = ((W - w) // 2, 22, w, h)
    base_sprite, srect, (ox, oy) = glass(base, rect, 32, tint=(14, 14, 18), tint_a=0.55, blur=24)
    sprite = Image.new('RGBA', base_sprite.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(sprite)
    _put(sprite, icon('door', isz), (ox + pad, oy + pad))
    fb, fs, fn = font(21, 620), font(17, 400), font(15, 500)
    d.text((ox + pad * 2 + isz - 4, oy + pad - 1), title, font=fb, fill=(255, 255, 255))
    d.text((ox + pad * 2 + isz - 4, oy + pad + 25), wrap(sub, fs, w - pad * 4 - isz - 60, 1)[0], font=fs, fill=(235, 235, 245, 170))
    d.text((ox + w - pad - text_w('now', fn), oy + pad + 2), 'now', font=fn, fill=(235, 235, 245, 150))
    ix, iy = ox + pad, oy + pad + isz + 14
    if snap:
        ratio = max(iw / snap.width, ih / snap.height)
        pic = snap.resize((max(iw, int(snap.width * ratio + 0.5)), max(ih, int(snap.height * ratio + 0.5))), Image.LANCZOS)
        l, t = (pic.width - iw) // 2, (pic.height - ih) // 2
        pic = pic.crop((l, t, l + iw, t + ih)).convert('RGBA')
    else:
        pic = Image.new('RGBA', (iw, ih), (38, 38, 44, 255)); pd = ImageDraw.Draw(pic)
        cx, cy = iw // 2, ih // 2 - 14
        pd.rounded_rectangle((cx - 34, cy - 22, cx + 20, cy + 22), radius=8, outline=(150, 150, 160), width=4)
        pd.polygon([(cx + 22, cy - 6), (cx + 40, cy - 18), (cx + 40, cy + 18), (cx + 22, cy + 6)], fill=(150, 150, 160))
        msg = 'Camera picture not available yet'
        pd.text(((iw - text_w(msg, fs)) / 2, cy + 40), msg, font=fs, fill=(170, 170, 180))
    pic.putalpha(rr_mask((iw, ih), 18))
    _put(sprite, pic, (ix, iy))
    return Image.alpha_composite(base_sprite, sprite).convert('RGB'), srect


def np_bar(base, title, artist, art_path, color, y=14):
    """Now Playing shrunk to a Dynamic-Island-style black capsule at the top while you look at other screens."""
    w, h = 400, 58
    x = (W - w) // 2
    big = Image.new('RGBA', (w * SS, h * SS), (0, 0, 0, 0))
    ImageDraw.Draw(big).rounded_rectangle((0, 0, w * SS - 1, h * SS - 1), radius=h * SS // 2, fill=(0, 0, 0, 255))
    cap = big.resize((w, h), Image.LANCZOS)
    img = base.crop((x, y, x + w, y + h)).convert('RGBA'); img.alpha_composite(cap)
    try:
        art = Image.open(art_path).convert('RGB').resize((42, 42), Image.LANCZOS).convert('RGBA')
        art.putalpha(rr_mask((42, 42), 10)); img.alpha_composite(art, (8, 8))
    except Exception:
        pass
    d = ImageDraw.Draw(img)
    ft, fa = font(16, 620), font(14, 500)
    tx, maxw = 62, w - 62 - 64
    d.text((tx, 9), wrap(title, ft, maxw, 1)[0] if title else '', font=ft, fill=(255, 255, 255))
    d.text((tx, 31), wrap(artist, fa, maxw, 1)[0] if artist else '', font=fa, fill=(235, 235, 245, 150))
    col = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5)) if color and len(color) == 7 else (255, 255, 255)
    col = tuple(min(255, int(c * 0.6 + 255 * 0.4)) for c in col)      # brightened cover colour, like the Island's waveform
    for i, bh in enumerate((12, 22, 30, 18, 26, 10)):
        bx = w - 54 + i * 7
        d.rounded_rectangle((bx, h / 2 - bh / 2, bx + 4, h / 2 + bh / 2), radius=2, fill=col)
    return img.convert('RGB'), (x, y, w, h)


# ---------------- StandBy-style full-screen timer (first minute after you start one) ----------------
TICKS = 60
_tick_geo = None


def _ticks():
    """60 tick marks evenly spaced around a rounded rectangle, each pointing at the middle, clockwise from top centre."""
    global _tick_geo
    if _tick_geo:
        return _tick_geo
    x0, y0, x1, y1, r = 46.0, 40.0, W - 46.0, H - 40.0, 150.0
    segs = []      # (length, point(t), normal(t))
    def line(ax, ay, bx, by, nx, ny):
        L = math.hypot(bx - ax, by - ay)
        segs.append((L, lambda t: (ax + (bx - ax) * t, ay + (by - ay) * t), lambda t: (nx, ny)))
    def arc(cx, cy, a0, a1):
        L = r * abs(a1 - a0)
        segs.append((L, lambda t: (cx + r * math.cos(a0 + (a1 - a0) * t), cy + r * math.sin(a0 + (a1 - a0) * t)),
                     lambda t: (math.cos(a0 + (a1 - a0) * t), math.sin(a0 + (a1 - a0) * t))))
    mid = (x0 + x1) / 2
    line(mid, y0, x1 - r, y0, 0, -1); arc(x1 - r, y0 + r, -math.pi / 2, 0)
    line(x1, y0 + r, x1, y1 - r, 1, 0); arc(x1 - r, y1 - r, 0, math.pi / 2)
    line(x1 - r, y1, x0 + r, y1, 0, 1); arc(x0 + r, y1 - r, math.pi / 2, math.pi)
    line(x0, y1 - r, x0, y0 + r, -1, 0); arc(x0 + r, y0 + r, math.pi, 1.5 * math.pi)
    line(x0 + r, y0, mid, y0, 0, -1)
    total = sum(sg[0] for sg in segs); out = []
    for i in range(TICKS):
        d = total * i / TICKS
        for L, pt, nm in segs:
            if d <= L:
                t = d / L if L else 0
                out.append((pt(t), nm(t))); break
            d -= L
    _tick_geo = out
    return out


def timer_full(base, lit):
    """Black screen with the orange tick ring; `lit` ticks still bright (the rest have elapsed)."""
    S = 2
    im = Image.new('RGB', (W * S, H * S), (0, 0, 0)); d = ImageDraw.Draw(im)
    for i, ((px, py), (nx, ny)) in enumerate(_ticks()):
        col = (255, 149, 0) if i < lit else (70, 38, 6)
        ax, ay = (px - nx * 6) * S, (py - ny * 6) * S
        bx, by = (px - nx * 38) * S, (py - ny * 38) * S
        w = 7 * S
        d.line([(ax, ay), (bx, by)], fill=col, width=w)
        for cx, cy in ((ax, ay), (bx, by)):
            d.ellipse((cx - w / 2, cy - w / 2, cx + w / 2, cy + w / 2), fill=col)
    return im.resize((W, H), Image.LANCZOS), (0, 0, W, H)


def timer_digits(base, txt, label):
    """The big remaining time and the orange label, drawn over the black timer screen (redrawn every second)."""
    w, h = 640, 250; x, y = (W - w) // 2, (H - h) // 2 - 6
    img = base.crop((x, y, x + w, y + h)).convert('RGBA')
    d = ImageDraw.Draw(img)
    f = font(172, 560); fl = font(30, 620)
    cell = max(text_w(c, f) for c in '0123456789'); colon = text_w(':', f)
    tw = sum(colon if c == ':' else cell for c in txt)
    mono_digits(d, (w + tw) / 2, 4, txt, f, (255, 255, 255))
    d.text(((w - text_w(label, fl)) / 2, 200), label, font=fl, fill=(255, 159, 10))
    return img.convert('RGB'), (x, y, w, h)


def solid(base, rgb):
    """Full-screen flat colour (camera calibration)."""
    return Image.new('RGB', (W, H), rgb), (0, 0, W, H)


def cal_dots(base, dots):
    """Black screen, optionally with big white calibration dots."""
    im = Image.new('RGB', (W, H), (0, 0, 0)); d = ImageDraw.Draw(im)
    for (x, y) in dots:
        d.ellipse((x - 30, y - 30, x + 30, y + 30), fill=(255, 255, 255))
    return im, (0, 0, W, H)


def cal_target(base, pt, prog, n, total, phase):
    """Finger calibration: one target at a time; the ring fills while you hold, then turns green."""
    im = Image.new('RGB', (W, H), (12, 12, 16)).convert('RGBA'); d = ImageDraw.Draw(im)
    ft, fs = font(30, 650), font(20, 500)
    if phase == 'done' or phase == 'failed':
        msg = 'Touch is calibrated' if phase == 'done' else 'Calibration timed out. Say “calibrate the touch screen” to try again'
        d.text(((W - text_w(msg, ft if phase == 'done' else fs)) / 2, H / 2 - 20), msg, font=ft if phase == 'done' else fs, fill=(255, 255, 255))
        return im.convert('RGB'), (0, 0, W, H)
    msg = 'Touch the dot the way you normally would, and hold'
    d.text(((W - text_w(msg, ft)) / 2, H / 2 - 60 if pt[1] > H / 2 else H / 2 + 20), msg, font=ft, fill=(255, 255, 255))
    sub = '%d of %d' % (n + 1, total)
    d.text(((W - text_w(sub, fs)) / 2, (H / 2 - 18 if pt[1] > H / 2 else H / 2 + 62)), sub, font=fs, fill=(200, 200, 210))
    x, y = pt; big = Image.new('RGBA', (160 * SS, 160 * SS), (0, 0, 0, 0)); g = ImageDraw.Draw(big); c = 80 * SS
    green = prog >= 1.0
    g.ellipse((c - 46 * SS, c - 46 * SS, c + 46 * SS, c + 46 * SS), outline=(255, 255, 255, 120), width=4 * SS)
    if prog > 0:
        g.arc((c - 46 * SS, c - 46 * SS, c + 46 * SS, c + 46 * SS), -90, -90 + 360 * min(1.0, prog), fill=(52, 199, 89, 255) if green else (255, 255, 255, 255), width=8 * SS)
    g.ellipse((c - 12 * SS, c - 12 * SS, c + 12 * SS, c + 12 * SS), fill=(52, 199, 89, 255) if green else (255, 159, 10, 255))
    im.alpha_composite(big.resize((160, 160), Image.LANCZOS), (x - 80, y - 80))
    return im.convert('RGB'), (0, 0, W, H)


def touch_cursor(base, x, y, prog, ripple):
    """Where your fingertip points: a small glass ring that fills as a tap is about to happen."""
    r = 30 if not ripple else 40; size = r * 2 + 12
    x0, y0 = max(0, min(W - size, x - size // 2)), max(0, min(H - size, y - size // 2))
    img = base.crop((x0, y0, x0 + size, y0 + size)).convert('RGBA')
    big = Image.new('RGBA', (size * SS, size * SS), (0, 0, 0, 0)); d = ImageDraw.Draw(big)
    c = size * SS / 2; R = r * SS
    d.ellipse((c - R, c - R, c + R, c + R), fill=(255, 255, 255, 120 if ripple else 46), outline=(255, 255, 255, 235), width=int(3 * SS))
    if prog > 0 and not ripple:
        d.arc((c - R + 6 * SS, c - R + 6 * SS, c + R - 6 * SS, c + R - 6 * SS), -90, -90 + 360 * prog, fill=(255, 255, 255, 255), width=int(6 * SS))
    d.ellipse((c - 5 * SS, c - 5 * SS, c + 5 * SS, c + 5 * SS), fill=(255, 255, 255, 255))
    img.alpha_composite(big.resize((size, size), Image.LANCZOS))
    return img.convert('RGB'), (x0, y0, size, size)


def siri_card(base, text, phase):
    """Muse's spoken answer (phase 'speaking') or what you said (phase 'thinking'), bottom centre."""
    pad, osz = 20, 46
    f = font(22, 400) if phase == 'speaking' else font(21, 500)
    shown = text if phase == 'speaking' else '“' + text + '”'
    max_w = 700
    lines = wrap(shown, f, max_w, 3)
    tw = max(text_w(l, f) for l in lines) if lines else 100
    w = int(min(max_w, tw) + pad * 3 + osz); lh = 29
    h = max(osz + pad * 2, pad * 2 + lh * len(lines))
    rect = ((W - w) // 2, H - 26 - h, w, h)
    base_sprite, srect, (ox, oy) = glass(base, rect, 30 if len(lines) > 1 else h // 2, tint=(14, 14, 18), tint_a=0.52)
    sprite = Image.new('RGBA', base_sprite.size, (0, 0, 0, 0))
    o = orb(osz); _put(sprite, o, (ox + pad - 2, oy + (h - osz) // 2))
    d = ImageDraw.Draw(sprite)
    col = (255, 255, 255) if phase == 'speaking' else (235, 235, 245)
    ty = oy + (h - lh * len(lines)) / 2 + 2
    for i, ln in enumerate(lines):
        d.text((ox + pad * 2 + osz - 4, ty + i * lh), ln, font=f, fill=col)
    return Image.alpha_composite(base_sprite, sprite).convert('RGB'), srect


def split_banner(text):
    """'Package · New headphones: Out for delivery' -> ('Package', 'New headphones: Out for delivery', 'package')."""
    t = text.strip()
    if t.lower().startswith('package'):
        body = re.sub(r'^package\s*[·:\-]\s*', '', t, flags=re.I)
        return 'Package', body, 'package'
    m = re.match(r'^(Car)\b\s*·?\s*(.+)$', t)
    if m:
        return m.group(1), m.group(2).replace(' · ', ', '), 'car'
    if t.lower().startswith('packages:'):
        return 'Packages', t.partition(':')[2].strip(), 'package'
    if t.lower().startswith('intercom'):
        return 'Intercom', re.sub(r'^intercom\s*[·:\-]\s*', '', t, flags=re.I), 'intercom'
    return ASSISTANT, t, 'muse'
