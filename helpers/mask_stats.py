"""Measure how much of the Photo-face digit area each person mask covers (cover-cropped to 1451x1088)."""
import json, sys
from pathlib import Path
from PIL import Image
W, H = 1451, 1088
masks = Path(sys.argv[1]); out = {}
for p in sorted(masks.glob('*.mask.png')):
    im = Image.open(p).convert('L'); w, h = im.size
    k = max(W / w, H / h); im = im.resize((round(w * k), round(h * k)))
    x0 = (im.width - W) // 2; y0 = (im.height - H) // 2
    im = im.crop((x0, y0, x0 + W, y0 + H))
    region = im.crop((200, 58, 1250, 1028)).resize((210, 194))   # digit band
    px = list(region.getdata()); out[p.name[:-9]] = round(sum(1 for v in px if v > 128) / len(px), 3)
(masks / 'coverage.json').write_text(json.dumps(out, indent=1))
print(len(out), 'masks;', sum(1 for v in out.values() if v < 0.30), 'under 30% coverage')
