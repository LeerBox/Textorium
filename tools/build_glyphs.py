"""Build src/leerbox/data/glyph_masks.json — measured glyph coverage masks for the image engine.

Every glyph is rasterized from DejaVu Sans Mono (the font both editions use for graphical output) at
4× supersampling into a 32×64 cell and box-averaged to an 8×16 coverage mask (0–255). Block elements,
sextants (U+1FB00–1FB3B) and Braille patterns (U+2800–28FF) are computed geometrically because their
shapes are defined exactly by Unicode. Glyphs missing from the font are skipped (detected by comparing
against the .notdef rendering). Both editions load this file, so glyph densities and shape matching are
identical in Python and JavaScript.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
FONT = ROOT / "third_party" / "mono_font" / "DejaVuSansMono.ttf"
OUT = ROOT / "src" / "leerbox" / "data" / "glyph_masks.json"
W, H, SS = 8, 16, 4

CP437 = ("☺☻♥♦♣♠•◘○◙♂♀♪♫☼►◄↕‼¶§▬↨↑↓→←∟↔▲▼⌂ÇüéâäàåçêëèïîìÄÅÉæÆôöòûùÿÖÜ¢£¥₧ƒáíóúñÑªº¿⌐¬½¼¡«»"
         "αßΓπΣσµτΦΘΩδ∞φε∩≡±≥≤⌠⌡÷≈°∙·√ⁿ²■")
RANGES = [(0x20, 0x7F), (0xA1, 0x100), (0x391, 0x3CA), (0x2190, 0x2200), (0x2200, 0x2300),
          (0x2500, 0x2580), (0x25A0, 0x2600)]
EXTRA = "★☆✦✧✶✷✸✹⋆♩♬☀☁☂☃☄✓✗✔✘❖❤"


def geometric(cp: int) -> list[float] | None:
    """Exact coverage for block elements, sextants and Braille on the W×H grid (None if not geometric)."""
    def rect(x0, y0, x1, y1):  # fractional rectangle in cell units 0..1
        m = []
        for y in range(H):
            for x in range(W):
                ox = max(0.0, min(x + 1, x1 * W) - max(x, x0 * W))
                oy = max(0.0, min(y + 1, y1 * H) - max(y, y0 * H))
                m.append(ox * oy)
        return m

    def union(*ms):
        return [min(1.0, sum(v)) for v in zip(*ms)]
    if cp == 0x2580: return rect(0, 0, 1, .5)
    if 0x2581 <= cp <= 0x2588: return rect(0, 1 - (cp - 0x2580) / 8, 1, 1)
    if 0x2589 <= cp <= 0x258F: return rect(0, 0, (0x2590 - cp) / 8, 1)
    if cp == 0x2590: return rect(.5, 0, 1, 1)
    if cp in (0x2591, 0x2592, 0x2593): return [(cp - 0x2590) / 4] * (W * H)
    if cp == 0x2594: return rect(0, 0, 1, 1 / 8)
    if cp == 0x2595: return rect(7 / 8, 0, 1, 1)
    quads = {0x2596: "3", 0x2597: "4", 0x2598: "1", 0x2599: "134", 0x259A: "14", 0x259B: "123",
             0x259C: "124", 0x259D: "2", 0x259E: "23", 0x259F: "234"}
    if cp in quads:
        q = {"1": (0, 0, .5, .5), "2": (.5, 0, 1, .5), "3": (0, .5, .5, 1), "4": (.5, .5, 1, 1)}
        return union(*[rect(*q[k]) for k in quads[cp]])
    if 0x1FB00 <= cp <= 0x1FB3B:
        n = cp - 0x1FB00 + 1
        # Unicode skips the patterns equal to existing characters (left half 21, right half 42)
        if n >= 21: n += 1
        if n >= 42: n += 1
        parts = []
        for bit in range(6):
            if n >> bit & 1:
                cx, cy = bit % 2, bit // 2
                parts.append(rect(cx / 2, cy / 3, (cx + 1) / 2, (cy + 1) / 3))
        return union(*parts)
    if 0x2800 <= cp <= 0x28FF:
        bits = cp - 0x2800
        pos = [(0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2), (0, 3), (1, 3)]
        m = [0.0] * (W * H)
        for b, (dx, dy) in enumerate(pos):
            if bits >> b & 1:
                cx, cy = (dx + .5) * W / 2, (dy + .5) * H / 4
                for y in range(H):
                    for x in range(W):
                        # supersampled disc of radius 1.4 px
                        acc = 0
                        for sy in range(4):
                            for sx in range(4):
                                px, py = x + (sx + .5) / 4, y + (sy + .5) / 4
                                acc += (px - cx) ** 2 + (py - cy) ** 2 <= 1.4 ** 2
                        m[y * W + x] = min(1.0, m[y * W + x] + acc / 16)
        return m
    return None


def main() -> None:
    font = ImageFont.truetype(str(FONT), 53)
    adv = font.getlength("M")
    ascent, descent = font.getmetrics()
    base = round((H * SS - (ascent + descent)) / 2 + ascent)
    notdef = font.getmask("\U0010FFFD")
    chars = []
    for a, b in RANGES:
        chars += [chr(c) for c in range(a, b)]
    chars += list(CP437 + EXTRA)
    chars += [chr(c) for c in range(0x2580, 0x25A0)] + [chr(c) for c in range(0x1FB00, 0x1FB3C)]
    chars += [chr(c) for c in range(0x2800, 0x2900)]
    chars = sorted(dict.fromkeys(chars), key=ord)
    out_chars, blob = [], bytearray()
    for ch in chars:
        cp = ord(ch)
        geo = geometric(cp)
        if geo is not None:
            vals = [int(v * 255 + 0.5) for v in geo]
        else:
            m = font.getmask(ch)
            if ch != " " and m.size == notdef.size and bytes(m) == bytes(notdef):
                continue
            if font.getlength(ch) > adv * 1.05:
                continue  # not a single-cell glyph in this font
            im = Image.new("L", (W * SS, H * SS), 0)
            ImageDraw.Draw(im).text((0, base), ch, font=font, fill=255, anchor="ls")
            small = im.reduce(SS)
            vals = list(small.tobytes())
        out_chars.append(ch)
        blob += bytes(vals)
    data = {"w": W, "h": H, "font": "DejaVu Sans Mono", "chars": "".join(out_chars),
            "masks": base64.b64encode(bytes(blob)).decode("ascii")}
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"glyph masks: {len(out_chars)} glyphs, {len(blob):,} bytes raw -> {OUT.stat().st_size:,} B json")


if __name__ == "__main__":
    main()
