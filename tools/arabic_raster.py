"""Build-time rasterizer for Arabic bitmap fonts and shaping tables.

Requires Pillow (build time only). For each OFL Arabic typeface it renders:
  * every Arabic presentation form (isolated/initial/medial/final) incl. Persian/Urdu letters
  * lam-alef ligatures, Arabic punctuation, Arabic-Indic and Persian digits
  * basic Latin (for mixed Arabic/English text)
  * harakat (diacritics) as separately positioned mark bitmaps

Glyphs keep their typographic advance and ink offset so that joining strokes of
consecutive presentation forms connect when composed by the runtime renderer.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

FONTS = [
    ("Amiri", "Amiri-Regular.ttf", None, "OFL_amiri.txt", "Naskh"),
    ("Amiri Bold", "Amiri-Bold.ttf", None, "OFL_amiri.txt", "Naskh"),
    ("Noto Naskh Arabic Bold", "NotoNaskhArabic[wght].ttf", b"Bold", "OFL_notonaskharabic.txt", "Naskh"),
    ("Noto Kufi Arabic Bold", "NotoKufiArabic[wght].ttf", b"Bold", "OFL_notokufiarabic.txt", "Kufi"),
    ("Noto Sans Arabic Bold", "NotoSansArabic[wdth,wght].ttf", b"Bold", "OFL_notosansarabic.txt", "Sans"),
    ("Vazirmatn Bold", "Vazirmatn[wght].ttf", b"Bold", "OFL_vazirmatn.txt", "Persian Sans"),
]
MARKS = "ًٌٍَُِّْٰٕٓٔ"
EXTRA = "،؛؟٪٫٬۔ـء" + "".join(chr(c) for c in range(0x660, 0x66A)) + "".join(chr(c) for c in range(0x6F0, 0x6FA))
TARGET_HEIGHT = 26


def write_tables() -> dict:
    from leerbox.arabic import build_tables
    t = build_tables()
    out = ROOT / "src" / "leerbox" / "data" / "arabic_tables.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(t, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return t


def _bits_hex(row: list[int]) -> str:
    v = 0
    for i, b in enumerate(row):
        if b:
            v |= 1 << i
    return format(v, "x") if v else ""


def rasterize_arabic_fonts(font_dir: Path) -> list[dict]:
    from PIL import Image, ImageDraw, ImageFont
    t = write_tables()
    chars = set(EXTRA)
    for f in t["forms"].values():
        chars.update(x for x in f if x)
    for f in t["lig"].values():
        chars.update(x for x in f if x)
    chars.update(chr(c) for c in range(32, 127))
    entries = []
    for name, file, variation, lic_file, style in FONTS:
        path = font_dir / file
        if not path.exists():
            print("missing Arabic font", path, file=sys.stderr)
            continue

        def load(size: int):
            f = ImageFont.truetype(str(path), size)
            if variation:
                f.set_variation_by_name(variation)
            return f

        notdef = None

        def render(f, ch: str, size: int):
            W, H = size * 5, size * 3
            x0, yb = size * 2, size * 2
            im = Image.new("L", (W, H), 0)
            ImageDraw.Draw(im).text((x0, yb), ch, font=f, fill=255, anchor="ls")
            px = im.load()
            rows = [[1 if px[x, y] >= 128 else 0 for x in range(W)] for y in range(H)]
            return rows, x0, yb

        # choose a size so the union ink height of letters is ~TARGET_HEIGHT
        size = 30
        for _ in range(3):
            f = load(size)
            top, bot = 10 ** 9, -1
            for ch in "ﺍﻟﻣﻪﺟﻲAhgjyلع":
                rows, _, _ = render(f, ch, size)
                for y, r in enumerate(rows):
                    if any(r):
                        top, bot = min(top, y), max(bot, y)
            h = bot - top + 1
            size = max(10, round(size * TARGET_HEIGHT / max(1, h)))
        f = load(size)
        notdef_rows, _, _ = render(f, "", size)
        glyphs = {}
        top, bot = 10 ** 9, -1
        raw = {}
        for ch in sorted(chars):
            rows, x0, yb = render(f, ch, size)
            if ch != " " and rows == notdef_rows:
                continue
            adv = round(f.getlength(ch))
            cols = [x for x in range(len(rows[0])) if any(r[x] for r in rows)]
            if not cols:
                raw[ch] = (adv, 0, None)
                continue
            l, r = cols[0], cols[-1]
            for y, row in enumerate(rows):
                if any(row[l:r + 1]):
                    top, bot = min(top, y), max(bot, y)
            raw[ch] = (adv, l - x0, [row[l:r + 1] for row in rows])
        marks = {}
        for m in MARKS:
            rows, x0, yb = render(f, m, size)
            if rows == notdef_rows:
                continue
            cols = [x for x in range(len(rows[0])) if any(r[x] for r in rows)]
            if not cols:
                continue
            l, r = cols[0], cols[-1]
            marks[m] = (l - x0, [row[l:r + 1] for row in rows])
        pad = 6  # headroom so stacked marks never clip
        top = max(0, top - pad)
        bot = bot + pad
        for ch, (adv, xoff, rows) in raw.items():
            if rows is None:
                glyphs[ch] = [adv, 0]
            else:
                glyphs[ch] = [adv, xoff] + [_bits_hex(r) for r in rows[top:bot + 1]]
        mk = {m: [0, xoff] + [_bits_hex(r) for r in rows[top:bot + 1]] for m, (xoff, rows) in marks.items()}
        height = bot - top + 1
        lic_text = (font_dir / lic_file).read_text(encoding="utf-8").splitlines()[0] if (font_dir / lic_file).exists() else ""
        entries.append({
            "name": name, "file": file, "format": "RASTER", "type": "raster",
            "source": "arabic-ofl", "repo": "https://github.com/google/fonts (ofl/)",
            "licenseTier": "clear", "license": "OFL-1.1 — " + lic_text,
            "author": lic_text.replace("Copyright", "").strip(" .") or None,
            "height": height, "baseline": yb - top, "layout": 0, "direction": 1,
            "hardblank": "", "sampleWidth": 0,
            "maxGlyphWidth": max((g[0] for g in glyphs.values()), default=0),
            "category": "Arabic", "tags": ["Arabic", "Raster", style, "Persian" if "ﭗ" in glyphs else "Arabic"],
            "coverage": {"glyphs": len(glyphs), "marks": len(mk),
                         "persian": sum(1 for c in "ﭖﭺﮊﮎﮒﯼ" if c in glyphs)},
            "sha256": None, "pixelSize": size,
            "_raster": {"h": height, "base": yb - top, "script": "arabic", "g": glyphs, "m": mk},
        })
        print(f"  {name}: size {size}px, height {height}, glyphs {len(glyphs)}, marks {len(mk)}")
    import hashlib
    for e in entries:
        e["sha256"] = hashlib.sha256(json.dumps(e["_raster"], sort_keys=True).encode()).hexdigest()
    return entries


if __name__ == "__main__":
    rasterize_arabic_fonts(ROOT / "third_party" / "arabic_fonts")
