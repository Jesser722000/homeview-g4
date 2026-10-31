"""Draw the demo mode's placeholder pictures into static/demo/ (simple shapes and gradients, no photos).

Run again any time:  python3 tools/make_demo_images.py
Replace them with your own pictures if you like; demo mode shows static/demo/sample-*.jpg in the Photo slots.
"""
import math, random
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent.parent / 'static' / 'demo'


def gradient(w, h, top, bottom):
    img = Image.new('RGB', (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(1, h - 1)
        d.line([(0, y), (w, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)))
    return img


def ridge(d, w, h, base, amp, seed, color, step=8):
    rnd = random.Random(seed)
    phases = [rnd.uniform(0, 6.28) for _ in range(4)]
    pts = [(0, h)]
    for x in range(0, w + step, step):
        y = base + sum(amp / (k + 1) * math.sin(x / (w / (2 + 3 * k)) + phases[k]) for k in range(4))
        pts.append((x, y))
    pts.append((w, h))
    d.polygon(pts, fill=color)


def save(img, name):
    img.save(OUT / name, 'JPEG', quality=86, optimize=True)   # Pillow writes no EXIF unless asked
    print('wrote', OUT / name)


def mountains(name, sky, layers, sun=None, seed=1, w=1600, h=1200):
    img = gradient(w, h, *sky)
    d = ImageDraw.Draw(img)
    if sun:
        x, y, r, c = sun
        glow = Image.new('L', (w, h), 0)
        ImageDraw.Draw(glow).ellipse((x - r * 3, y - r * 3, x + r * 3, y + r * 3), fill=90)
        img.paste(Image.new('RGB', (w, h), c), (0, 0), glow.filter(ImageFilter.GaussianBlur(r)))
        d = ImageDraw.Draw(img)
        d.ellipse((x - r, y - r, x + r, y + r), fill=c)
    for i, (base, amp, color) in enumerate(layers):
        ridge(d, w, h, base * h, amp * h, seed * 10 + i, color)
    save(img, name)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    mountains('sample-1.jpg', ((255, 170, 120), (120, 90, 170)), [(.55, .08, (96, 70, 130)), (.66, .06, (70, 50, 105)), (.78, .05, (44, 32, 72))],
              sun=(1120, 520, 70, (255, 226, 170)), seed=1)
    mountains('sample-2.jpg', ((130, 190, 235), (215, 235, 245)), [(.50, .10, (150, 170, 190)), (.62, .07, (90, 130, 110)), (.76, .05, (50, 95, 70))],
              seed=2)
    mountains('sample-3.jpg', ((20, 30, 70), (70, 60, 120)), [(.60, .06, (40, 40, 80)), (.72, .05, (28, 28, 60)), (.84, .03, (16, 16, 40))],
              sun=(420, 300, 46, (240, 240, 230)), seed=3)
    mountains('sample-4.jpg', ((255, 214, 150), (240, 150, 100)), [(.62, .05, (205, 120, 80)), (.72, .04, (170, 90, 60)), (.84, .03, (130, 65, 45))],
              sun=(800, 600, 90, (255, 245, 210)), seed=4)

    # album cover: a sunset over stripes
    w = 640; img = gradient(w, w, (255, 122, 69), (91, 91, 255)); d = ImageDraw.Draw(img)
    d.ellipse((190, 150, 450, 410), fill=(255, 214, 120))
    for i in range(6):
        y = 330 + i * 34
        d.rectangle((0, y, w, y + 14 + i * 2), fill=(74, 42, 138))
    save(img, 'art.jpg')

    # recipe card: a loaf on a warm counter
    img = gradient(1600, 1200, (250, 222, 180), (196, 140, 90)); d = ImageDraw.Draw(img)
    d.rounded_rectangle((420, 520, 1180, 900), 120, fill=(150, 88, 40))
    d.rounded_rectangle((460, 470, 1140, 760), 140, fill=(184, 116, 58))
    for x in range(560, 1080, 130):
        d.arc((x, 520, x + 110, 640), 200, 340, fill=(120, 66, 28), width=10)
    save(img, 'bread.jpg')

    # fact page: an orange suspension bridge in fog
    img = gradient(1600, 1200, (200, 215, 225), (240, 236, 230)); d = ImageDraw.Draw(img)
    d.rectangle((0, 860, 1600, 1200), fill=(110, 140, 160))
    orange = (192, 54, 44)
    for tx in (420, 1180):
        d.rectangle((tx - 22, 260, tx + 22, 900), fill=orange)
        d.rectangle((tx - 40, 380, tx + 40, 400), fill=orange); d.rectangle((tx - 40, 560, tx + 40, 580), fill=orange)
    d.rectangle((0, 700, 1600, 728), fill=orange)
    for x0, x1 in ((-380, 420), (420, 1180), (1180, 1980)):
        pts = [(x, 270 + 400 * ((x - (x0 + x1) / 2) / ((x1 - x0) / 2)) ** 2 * -1 + 400) for x in range(x0, x1 + 1, 10)]
        pts = [(x, min(700, max(262, 700 - (700 - 262) * ((x - (x0 + x1) / 2) / ((x1 - x0) / 2)) ** 2))) for x, _ in pts]
        d.line(pts, fill=orange, width=7)
        for x, y in pts[::4]:
            d.line([(x, y), (x, 700)], fill=orange, width=2)
    img = img.filter(ImageFilter.GaussianBlur(1.2))
    save(img, 'bridge.jpg')

    # doorbell card: a front door
    img = gradient(900, 700, (180, 200, 215), (120, 130, 120)); d = ImageDraw.Draw(img)
    d.rectangle((0, 560, 900, 700), fill=(150, 140, 125))
    d.rectangle((300, 120, 600, 580), fill=(235, 230, 220))
    d.rectangle((330, 150, 570, 580), fill=(40, 70, 90))
    for y in (190, 380):
        d.rectangle((360, y, 540, y + 150), outline=(30, 55, 72), width=8)
    d.ellipse((520, 360, 544, 384), fill=(220, 190, 90))
    d.rectangle((640, 300, 700, 340), fill=(255, 225, 150))
    save(img, 'door.jpg')


if __name__ == '__main__':
    main()
