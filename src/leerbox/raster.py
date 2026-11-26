"""Bitmap ("raster typography") fonts and their text-art renderer.

Raster fonts store 1-bit glyph bitmaps with a typographic advance and an ink
x-offset, so glyphs may overlap like real type (needed for connected Arabic
script). Bitmaps are converted to text with several cell mappings:

  * one character per pixel (█ # $ ▓ • 1 or any custom character)
  * half blocks   (▀ ▄ █)        – 1×2 pixels per cell, square aspect in terminals
  * quarter blocks (▖ ▗ ▘ ▝ …)   – 2×2 pixels per cell
  * Braille       (U+2800…)     – 2×4 pixels per cell, the densest mapping
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

from .arabic import contains_arabic, convert_digits, shape, strip_diacritics, visual_clusters, tables
from .art import Art

MARK_STYLES = {"block": "█", "ascii": "#", "money": "$", "shade": "▓", "dots": "•", "binary": "1", "at": "@", "star": "*"}
QUAD = " ▘▝▀▖▌▞▛▗▚▐▜▄▙▟█"  # index bits: 1=TL 2=TR 4=BL 8=BR
MAX_BITMAP_PIXELS = 4_000_000


@dataclass
class Glyph:
    adv: int
    xoff: int
    width: int
    rows: list[int]  # bit i = column i (LSB = leftmost)


@dataclass
class RasterFont:
    name: str
    height: int
    baseline: int
    script: str
    glyphs: dict[str, Glyph]
    marks: dict[str, Glyph] = field(default_factory=dict)

    def has(self, ch: str) -> bool:
        return ch in self.glyphs


def _decode_glyph(data: list) -> Glyph:
    adv, xoff = int(data[0]), int(data[1])
    rows = [int(h, 16) if h else 0 for h in data[2:]]
    width = max((r.bit_length() for r in rows), default=0)
    return Glyph(adv, xoff, width, rows)


def parse_raster(obj: dict, name: str) -> RasterFont:
    h = int(obj["h"])
    if not 1 <= h <= 400:
        raise ValueError("invalid raster font height")
    glyphs = {}
    for ch, data in obj["g"].items():
        g = _decode_glyph(data)
        if len(g.rows) < h:
            g.rows += [0] * (h - len(g.rows))
        glyphs[ch] = g
    marks = {}
    for ch, data in (obj.get("m") or {}).items():
        g = _decode_glyph(data)
        g.rows += [0] * max(0, h - len(g.rows))
        marks[ch] = g
    return RasterFont(name, h, int(obj.get("base", h)), obj.get("script", "latin"), glyphs, marks)


@dataclass
class RasterOptions:
    mode: str = "block"          # block|ascii|money|shade|dots|binary|at|star|custom|half|quarter|braille
    char: str = "@"              # used by mode == custom
    scale: int = 1               # integer pixel upscaling
    aspect: int = 1              # horizontal repeat per pixel (2 = terminal aspect correction)
    letter_spacing: int = 0      # extra pixels between glyphs (never inside joined Arabic words)
    line_spacing: int = 2        # pixels between text lines
    align: str = "auto"          # auto|left|center|right
    direction: str = "auto"
    arabic_shaping: bool = True
    ligatures: bool = True
    diacritics: bool = True
    digits: str = "keep"
    invert: bool = False
    max_input: int = 2000


def _find_glyph(font: RasterFont, ch: str) -> Glyph | None:
    if ch in font.glyphs:
        return font.glyphs[ch]
    d = unicodedata.normalize("NFKD", ch)
    base = "".join(c for c in d if unicodedata.category(c)[0] != "M")
    for alt in (base, ch.upper(), ch.lower(), base.upper() if base else "", base.lower() if base else ""):
        if alt and alt in font.glyphs:
            return font.glyphs[alt]
    return font.glyphs.get("?")


def _joins_left_set() -> set[str]:
    t = tables()
    s = set()
    for f in t["forms"].values():
        if f[2]:
            s.add(f[2])
        if f[3]:
            s.add(f[3])
    s.add("ـ")
    return s


_JOINS_LEFT: set[str] | None = None


def _render_line_bitmap(font: RasterFont, line: str, o: RasterOptions) -> tuple[list[bytearray], int, bool]:
    """Compose one text line into a bitmap. Returns (rows, width, is_rtl)."""
    global _JOINS_LEFT
    is_ar = contains_arabic(line)
    if o.digits != "keep":
        line = convert_digits(line, o.digits)
    if not o.diacritics:
        line = strip_diacritics(line)
    if is_ar and o.arabic_shaping:
        line = shape(line, o.ligatures)
    clusters = visual_clusters(line, o.direction)
    from .arabic import paragraph_level
    rtl = paragraph_level(line, o.direction) == 1
    if _JOINS_LEFT is None:
        _JOINS_LEFT = _joins_left_set()
    placed: list[tuple[int, Glyph]] = []
    marks: list[tuple[str, int, Glyph]] = []
    pen = 0
    for i, cl in enumerate(clusters):
        base = cl[0]
        if base in ("‌", "‍", "‎", "‏"):
            continue
        g = _find_glyph(font, base) if base != " " else font.glyphs.get(" ")
        if base == " " and g is None:
            pen += max(2, font.height // 4)
            continue
        if g is None:
            continue
        placed.append((pen, g))
        for m in cl[1:]:
            if m in font.marks:
                marks.append((m, len(placed) - 1, font.marks[m]))
        pen += g.adv
        nxt = clusters[i + 1][0] if i + 1 < len(clusters) else ""
        if o.letter_spacing and not (nxt in _JOINS_LEFT):
            pen += o.letter_spacing
    minx = min([0] + [x + g.xoff for x, g in placed])
    shift = -minx
    width = max([pen + shift] + [x + g.xoff + g.width + shift for x, g in placed]) if placed else 0
    h = font.height
    rows = [bytearray(width) for _ in range(h)]
    for x, g in placed:
        ox = x + g.xoff + shift
        for y in range(h):
            r = g.rows[y]
            while r:
                low = r & -r
                bx = low.bit_length() - 1
                rows[y][ox + bx] = 1
                r ^= low
    # diacritics: centre over the base glyph ink, then push away from collisions
    for m, idx, mg in marks:
        bx, bg = placed[idx]
        bcenter = bx + bg.xoff + shift + bg.width / 2
        mx = int(bcenter - mg.width / 2 + 0.5)
        ys = [y for y in range(h) if mg.rows[y]]
        if not ys:
            continue
        above = (ys[0] + ys[-1]) / 2 < font.baseline - font.height * 0.15
        # base glyph ink rows over the mark's columns
        def collides(dy: int) -> bool:
            for y in ys:
                ty = y + dy
                if not 0 <= ty < h:
                    return True
                r = mg.rows[y]
                for k in range(mg.width):
                    if r >> k & 1:
                        tx = mx + k
                        if 0 <= tx < width and rows[ty][tx]:
                            return True
                        # keep one pixel gap
                        if 0 <= tx < width and ((ty + 1 < h and rows[ty + 1][tx]) if above else (ty - 1 >= 0 and rows[ty - 1][tx])):
                            return True
            return False
        dy = 0
        step = -1 if above else 1
        for _ in range(16):
            if not collides(dy):
                break
            dy += step
        for y in ys:
            ty = y + dy
            if 0 <= ty < h:
                r = mg.rows[y]
                for k in range(mg.width):
                    if r >> k & 1 and 0 <= mx + k < width:
                        rows[ty][mx + k] = 1
    return rows, width, rtl


def render_raster_bitmap(font: RasterFont, text: str, o: RasterOptions) -> list[bytearray]:
    text = text[: o.max_input]
    lines = text.replace("\r\n", "\n").split("\n")
    blocks = [_render_line_bitmap(font, ln, o) for ln in lines]
    width = max((w for _, w, _ in blocks), default=0)
    out: list[bytearray] = []
    for i, (rows, w, rtl) in enumerate(blocks):
        align = o.align
        if align == "auto":
            align = "right" if rtl else "left"
        pad = 0 if align == "left" else (width - w) if align == "right" else (width - w) // 2
        if i and o.line_spacing > 0:
            out.extend(bytearray(width) for _ in range(o.line_spacing))
        for r in rows:
            nr = bytearray(width)
            nr[pad:pad + w] = r
            out.append(nr)
    # trim blank rows at top/bottom
    while len(out) > 1 and not any(out[0]):
        out.pop(0)
    while len(out) > 1 and not any(out[-1]):
        out.pop()
    # trim fully blank columns on the right
    if out:
        last = 0
        for r in out:
            for x in range(len(r) - 1, -1, -1):
                if r[x]:
                    last = max(last, x + 1)
                    break
        out = [r[:last] for r in out]
    s = max(1, min(8, int(o.scale)))
    a = max(1, min(4, int(o.aspect)))
    if s * s * a * sum(len(r) for r in out) > MAX_BITMAP_PIXELS:
        raise ValueError("raster output too large; reduce text or scale")
    if s > 1 or a > 1:
        scaled = []
        for r in out:
            nr = bytearray()
            for b in r:
                nr.extend(bytes([b]) * (s * a))
            for _ in range(s):
                scaled.append(bytearray(nr))
        out = scaled
    if o.invert:
        out = [bytearray(1 - b for b in r) for r in out]
    return out


def bitmap_to_art(bits: list[bytearray], mode: str = "block", char: str = "@") -> Art:
    h = len(bits)
    w = max((len(r) for r in bits), default=0)
    def px(x: int, y: int) -> int:
        return 1 if 0 <= y < h and 0 <= x < len(bits[y]) and bits[y][x] else 0
    rows: list[list[str]] = []
    if mode == "half":
        for y in range(0, h, 2):
            rows.append([" ▀▄█"[px(x, y) | px(x, y + 1) << 1] for x in range(w)])
    elif mode == "quarter":
        for y in range(0, h, 2):
            rows.append([QUAD[px(x, y) | px(x + 1, y) << 1 | px(x, y + 1) << 2 | px(x + 1, y + 1) << 3]
                         for x in range(0, w, 2)])
    elif mode == "braille":
        for y in range(0, h, 4):
            row = []
            for x in range(0, w, 2):
                v = (px(x, y) | px(x, y + 1) << 1 | px(x, y + 2) << 2 | px(x + 1, y) << 3 | px(x + 1, y + 1) << 4
                     | px(x + 1, y + 2) << 5 | px(x, y + 3) << 6 | px(x + 1, y + 3) << 7)
                row.append(chr(0x2800 + v) if v else " ")
            rows.append(row)
    else:
        mark = char[:1] if mode == "custom" and char else MARK_STYLES.get(mode, "█")
        if mode == "custom" and char:
            from .figlet import graphemes
            g = graphemes(char)
            mark = g[0] if g else "@"
        for y in range(h):
            rows.append([mark if px(x, y) else " " for x in range(w)])
    if not rows:
        rows = [[]]
    art = Art(rows)
    art.trim_right()
    return art


def render_raster(font: RasterFont, text: str, o: RasterOptions | None = None) -> Art:
    o = o or RasterOptions()
    bits = render_raster_bitmap(font, text, o)
    return bitmap_to_art(bits, o.mode, o.char)
