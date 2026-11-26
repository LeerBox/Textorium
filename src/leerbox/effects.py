"""Non-destructive, ordered effects pipeline.

A pipeline is a list of dictionaries ``{"type": str, "enabled": bool, **params}``
applied in order to a copy of the rendered :class:`Art`. The same pipeline JSON
is understood by the JavaScript edition (web/src/engine/effects.js); both use
the same seeded PRNG (mulberry32) so random effects are reproducible and
identical across editions.

Every effect declares where it can be represented:
  * ``text``    – survives plain-text export (TXT, Markdown, code literals)
  * ``color``   – needs a colour-capable target (ANSI, HTML, SVG, raster)
  * ``graphic`` – needs a graphical target (HTML, SVG, PNG/JPEG/WebP/BMP)
"""
from __future__ import annotations

import colorsys
import math

from .art import Art, hex_to_rgb, join_rgb, split_rgb

MAX_EFFECT_CELLS = 2_000_000


class Rng:
    """mulberry32 — tiny deterministic PRNG shared with the JS edition."""

    def __init__(self, seed: int):
        self.a = seed & 0xFFFFFFFF

    def next(self) -> float:
        self.a = (self.a + 0x6D2B79F5) & 0xFFFFFFFF
        t = self.a
        t = ((t ^ (t >> 15)) * (t | 1)) & 0xFFFFFFFF
        t ^= (t + (((t ^ (t >> 7)) * (t | 61)) & 0xFFFFFFFF)) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296

    def int(self, n: int) -> int:
        return int(self.next() * n)


MIRROR_H = dict(zip("/\\()[]{}<>⌐¬└┘┌┐├┤╔╗╚╝╠╣▌▐◀▶«»‹›╭╮╰╯◤◥◣◢▖▗▘▝",
                    "\\/)(][}{><¬⌐┘└┐┌┤├╗╔╝╚╣╠▐▌▶◀»«›‹╮╭╯╰◥◤◢◣▗▖▝▘"))
FLIP_V = dict(zip("/\\^v'.,`_‾┌┐└┘╔╗╚╝┬┴╦╩▀▄╭╮╰╯◤◥◣◢▖▗▘▝MWmw",
                  "\\/v^.''.‾_└┘┌┐╚╝╔╗┴┬╩╦▄▀╰╯╭╮◣◢◤◥▘▝▖▗WMwm"))
ROT_90 = dict(zip("|-/\\─│═║┌┐┘└╔╗╝╚┬┤┴├▀▐▄▌<>^v()⌒⌣",
                  "-|\\/│─║═┐┘└┌╗╝╚╔┤┴├┬▐▄▌▀^v><⌒⌣)("))  # every mapping is a 2- or 4-cycle
INVERT_MAP = dict(zip("█▓▒░▀▄▌▐", " ░▒▓▄▀▐▌"))

FRAMES = {
    "single":   "┌─┐│└┘│─",
    "double":   "╔═╗║╚╝║═",
    "rounded":  "╭─╮│╰╯│─",
    "heavy":    "┏━┓┃┗┛┃━",
    "ascii":    "+-+|++|-",
    "dashed":   "┌╌┐╎└┘╎╌",
    "stars":    "*********",
    "block":    "█▀█████▄",
    "shade":    "▓▓▓▓▓▓▓▓",
    "dots":     "·······  ",
    "terminal": "┌─┐│└┘│─",
}

EFFECT_INFO = {
    "color": ("color", "Solid colours"),
    "gradient": ("color", "Gradient"),
    "rainbow": ("color", "Rainbow"),
    "shadow": ("text", "Shadow"),
    "double_shadow": ("text", "Double shadow"),
    "outline": ("text", "Outline"),
    "extrude": ("text", "3D extrusion"),
    "mirror": ("text", "Mirror (horizontal flip)"),
    "flip_v": ("text", "Vertical flip"),
    "rotate": ("text", "Rotate"),
    "invert": ("text", "Invert"),
    "fill": ("text", "Fill character"),
    "background": ("text", "Background character"),
    "noise": ("text", "Noise"),
    "glitch": ("text", "Glitch"),
    "matrix": ("color", "Matrix"),
    "zalgo": ("text", "Zalgo"),
    "frame": ("text", "Frame / box"),
    "padding": ("text", "Padding"),
    "glow": ("graphic", "Glow"),
}

DEFAULTS: dict[str, dict] = {
    "color": {"fg": "#7aa2ff", "bg": ""},
    "gradient": {"mode": "horizontal", "stops": ["#7aa2ff", "#b18cff"], "target": "fg"},
    "rainbow": {"mode": "horizontal", "saturation": 0.75, "lightness": 0.62, "offset": 0.0, "cycles": 1.0},
    "shadow": {"dx": 1, "dy": 1, "char": "░", "color": "#3b4252"},
    "double_shadow": {"dx": 1, "dy": 1, "char1": "▒", "char2": "░", "color1": "#4c566a", "color2": "#2e3440"},
    "outline": {"char": "·", "diagonal": True, "color": ""},
    "extrude": {"depth": 3, "direction": "se", "char": "▒", "color": "#4c566a"},
    "mirror": {},
    "flip_v": {},
    "rotate": {"angle": 90},
    "invert": {"char": "█", "margin": 1},
    "fill": {"char": "█"},
    "background": {"char": "·", "color": ""},
    "noise": {"amount": 0.05, "chars": "░▒▓·:", "seed": 7},
    "glitch": {"amount": 0.25, "shift": 3, "seed": 13},
    "matrix": {"density": 0.5, "seed": 21, "color": "#33ff66"},
    "zalgo": {"intensity": 2, "seed": 3},
    "frame": {"style": "rounded", "padding": 1, "title": "", "color": ""},
    "padding": {"top": 1, "right": 2, "bottom": 1, "left": 2},
    "glow": {"color": "#7aa2ff", "radius": 6, "strength": 0.8},
}


def new_effect(kind: str, **params) -> dict:
    if kind not in DEFAULTS:
        raise ValueError(f"unknown effect {kind!r}")
    e = {"type": kind, "enabled": True}
    e.update(DEFAULTS[kind])
    e.update(params)
    return e


def _col(v) -> int | None:
    if v in (None, "", "none"):
        return None
    if isinstance(v, int):
        return v
    return hex_to_rgb(str(v))


def _char(v, default: str) -> str:
    s = str(v) if v not in (None, "") else default
    from .figlet import graphemes
    g = graphemes(s)
    return g[0] if g else default


def _int(v, lo: int, hi: int, default: int) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _float(v, lo: float, hi: float, default: float) -> float:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return default
    if n != n:
        return default
    return max(lo, min(hi, n))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _grow(art: Art, left: int, top: int, right: int, bottom: int) -> Art:
    w = art.width + left + right
    h = art.height + top + bottom
    out = Art.blank(w, h)
    for y in range(art.height):
        for x in range(art.width):
            out.chars[y + top][x + left] = art.chars[y][x]
            out.fg[y + top][x + left] = art.fg[y][x]
            out.bg[y + top][x + left] = art.bg[y][x]
    out.meta = dict(art.meta)
    return out


def _offset_layer(art: Art, dx: int, dy: int, ch: str, color: int | None) -> Art:
    """Draw a copy of the ink at (dx, dy) underneath the original ink."""
    left, top = max(0, -dx), max(0, -dy)
    out = _grow(art, left, top, max(0, dx), max(0, dy))
    for y in range(art.height):
        for x in range(art.width):
            if art.is_ink(x, y):
                ty, tx = y + top + dy, x + left + dx
                sy, sx = y + top, x + left
                # only fill where the original has no ink
                oy, ox = ty - top, tx - left
                if 0 <= oy < art.height and 0 <= ox < art.width and art.is_ink(ox, oy):
                    continue
                if out.chars[ty][tx] in (" ", ""):
                    out.chars[ty][tx] = ch
                    out.fg[ty][tx] = color
    return out


def gradient_color(stops: list[int], t: float) -> int:
    if not stops:
        return 0xFFFFFF
    if len(stops) == 1:
        return stops[0]
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    pos = t * (len(stops) - 1)
    i = int(pos)
    if i >= len(stops) - 1:
        return stops[-1]
    f = pos - i
    a, b = split_rgb(stops[i]), split_rgb(stops[i + 1])
    return join_rgb(a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f)


def _t_for(mode: str, x: int, y: int, w: int, h: int) -> float:
    if mode == "vertical":
        return y / max(1, h - 1)
    if mode == "diagonal":
        return (x / max(1, w - 1) + y / max(1, h - 1)) / 2
    if mode == "diagonal_up":
        return (x / max(1, w - 1) + (h - 1 - y) / max(1, h - 1)) / 2
    if mode == "radial":
        cx, cy = (w - 1) / 2, (h - 1) / 2
        d = math.sqrt(((x - cx) / max(1, cx)) ** 2 + ((y - cy) / max(1, cy)) ** 2)
        return min(1.0, d / math.sqrt(2))
    return x / max(1, w - 1)


def hsl(h: float, s: float, l: float) -> int:
    r, g, b = colorsys.hls_to_rgb(h % 1.0, l, s)
    return join_rgb(r * 255, g * 255, b * 255)


# ---------------------------------------------------------------------------
# effect implementations
# ---------------------------------------------------------------------------

def fx_color(art: Art, p: dict) -> Art:
    fg, bg = _col(p.get("fg")), _col(p.get("bg"))
    for y in range(art.height):
        for x in range(art.width):
            if fg is not None and art.is_ink(x, y):
                art.fg[y][x] = fg
            if bg is not None:
                art.bg[y][x] = bg
    return art


def fx_gradient(art: Art, p: dict) -> Art:
    stops = [c for c in (_col(s) for s in (p.get("stops") or [])[:16]) if c is not None] or [0x7AA2FF, 0xB18CFF]
    mode = p.get("mode", "horizontal")
    target = p.get("target", "fg")
    w, h = art.width, art.height
    for y in range(h):
        for x in range(w):
            c = gradient_color(stops, _t_for(mode, x, y, w, h))
            if target == "bg":
                art.bg[y][x] = c
            elif art.is_ink(x, y):
                art.fg[y][x] = c
    return art


def fx_rainbow(art: Art, p: dict) -> Art:
    s = _float(p.get("saturation"), 0, 1, 0.75)
    l = _float(p.get("lightness"), 0, 1, 0.62)
    off = _float(p.get("offset"), -10, 10, 0.0)
    cycles = _float(p.get("cycles"), 0.1, 20, 1.0)
    mode = p.get("mode", "horizontal")
    w, h = art.width, art.height
    for y in range(h):
        for x in range(w):
            if art.is_ink(x, y):
                art.fg[y][x] = hsl(off + _t_for(mode, x, y, w, h) * cycles * 0.83, s, l)
    return art


def fx_shadow(art: Art, p: dict) -> Art:
    dx, dy = _int(p.get("dx"), -8, 8, 1), _int(p.get("dy"), -8, 8, 1)
    return _offset_layer(art, dx, dy, _char(p.get("char"), "░"), _col(p.get("color")))


def fx_double_shadow(art: Art, p: dict) -> Art:
    dx, dy = _int(p.get("dx"), -8, 8, 1), _int(p.get("dy"), -8, 8, 1)
    # first shadow behind the ink, then a second shadow behind ink + first shadow
    a = _offset_layer(art, dx, dy, _char(p.get("char1"), "▒"), _col(p.get("color1")))
    return _offset_layer(a, dx, dy, _char(p.get("char2"), "░"), _col(p.get("color2")))


def fx_outline(art: Art, p: dict) -> Art:
    ch = _char(p.get("char"), "·")
    diag = bool(p.get("diagonal", True))
    color = _col(p.get("color"))
    out = _grow(art, 1, 1, 1, 1)
    src = [[out.is_ink(x, y) for x in range(out.width)] for y in range(out.height)]
    nb = [(-1, 0), (1, 0), (0, -1), (0, 1)] + ([(-1, -1), (1, -1), (-1, 1), (1, 1)] if diag else [])
    for y in range(out.height):
        for x in range(out.width):
            if src[y][x]:
                continue
            for ddx, ddy in nb:
                xx, yy = x + ddx, y + ddy
                if 0 <= xx < out.width and 0 <= yy < out.height and src[yy][xx]:
                    out.chars[y][x] = ch
                    out.fg[y][x] = color
                    break
    return out


def fx_extrude(art: Art, p: dict) -> Art:
    depth = _int(p.get("depth"), 1, 12, 3)
    d = p.get("direction", "se")
    dx = 1 if "e" in d else -1 if "w" in d else 0
    dy = 1 if "s" in d else -1 if "n" in d else 0
    ch = _char(p.get("char"), "▒")
    color = _col(p.get("color"))
    left, top = max(0, -dx * depth), max(0, -dy * depth)
    out = _grow(art, left, top, max(0, dx * depth), max(0, dy * depth))
    ink = [(x, y) for y in range(art.height) for x in range(art.width) if art.is_ink(x, y)]
    for k in range(depth, 0, -1):
        for x, y in ink:
            tx, ty = x + left + dx * k, y + top + dy * k
            ox, oy = tx - left, ty - top
            if 0 <= ox < art.width and 0 <= oy < art.height and art.is_ink(ox, oy):
                continue
            out.chars[ty][tx] = ch
            out.fg[ty][tx] = color
    return out


def _map_chars(art: Art, table: dict) -> None:
    for r in art.chars:
        for i, c in enumerate(r):
            if c in table:
                r[i] = table[c]


def fx_mirror(art: Art, p: dict) -> Art:
    for rows in (art.chars, art.fg, art.bg):
        for r in rows:
            r.reverse()
    _map_chars(art, MIRROR_H)
    return art


def fx_flip_v(art: Art, p: dict) -> Art:
    art.chars.reverse(); art.fg.reverse(); art.bg.reverse()
    _map_chars(art, FLIP_V)
    return art


def fx_rotate(art: Art, p: dict) -> Art:
    angle = _int(p.get("angle"), 0, 360, 90) // 90 * 90 % 360
    for _ in range(angle // 90):
        h, w = art.height, art.width
        chars = [[art.chars[h - 1 - y][x] for y in range(h)] for x in range(w)]
        fg = [[art.fg[h - 1 - y][x] for y in range(h)] for x in range(w)]
        bg = [[art.bg[h - 1 - y][x] for y in range(h)] for x in range(w)]
        art = Art(chars, fg, bg, art.meta)
        _map_chars(art, ROT_90)
    return art


def fx_invert(art: Art, p: dict) -> Art:
    ch = _char(p.get("char"), "█")
    m = _int(p.get("margin"), 0, 10, 1)
    out = _grow(art, m, m, m, m)
    for y in range(out.height):
        for x in range(out.width):
            c = out.chars[y][x]
            if c == "":
                continue
            if c in INVERT_MAP:
                out.chars[y][x] = INVERT_MAP[c] if INVERT_MAP[c] != " " else " "
            elif c == " ":
                out.chars[y][x] = ch
            else:
                out.chars[y][x] = " "
    return out


def fx_fill(art: Art, p: dict) -> Art:
    ch = _char(p.get("char"), "█")
    for y in range(art.height):
        for x in range(art.width):
            if art.is_ink(x, y):
                art.chars[y][x] = ch
    return art


def fx_background(art: Art, p: dict) -> Art:
    ch = _char(p.get("char"), "·")
    color = _col(p.get("color"))
    for y in range(art.height):
        for x in range(art.width):
            if art.chars[y][x] == " ":
                art.chars[y][x] = ch
                art.fg[y][x] = color
    return art


def fx_noise(art: Art, p: dict) -> Art:
    rng = Rng(_int(p.get("seed"), 0, 2 ** 31, 7))
    amount = _float(p.get("amount"), 0, 1, 0.05)
    chars = [c for c in str(p.get("chars") or "░▒▓·:")][:64] or ["·"]
    for y in range(art.height):
        for x in range(art.width):
            r = rng.next()
            k = rng.int(len(chars))
            if r < amount and art.chars[y][x] == " ":
                art.chars[y][x] = chars[k]
    return art


GLITCH_CHARS = "▓▒░█▌▐▀▄#%&@$?!/\\|<>"


def fx_glitch(art: Art, p: dict) -> Art:
    rng = Rng(_int(p.get("seed"), 0, 2 ** 31, 13))
    amount = _float(p.get("amount"), 0, 1, 0.25)
    shift = _int(p.get("shift"), 0, 20, 3)
    out = _grow(art, shift, 0, shift, 0)
    for y in range(out.height):
        if rng.next() < amount and shift:
            s = rng.int(2 * shift + 1) - shift
            for rows in (out.chars, out.fg, out.bg):
                r = rows[y]
                if s > 0:
                    rows[y] = [(" " if rows is out.chars else None)] * s + r[:-s]
                elif s < 0:
                    rows[y] = r[-s:] + [(" " if rows is out.chars else None)] * (-s)
        for x in range(out.width):
            r = rng.next()
            k = rng.int(len(GLITCH_CHARS))
            if out.is_ink(x, y) and r < amount * 0.15:
                out.chars[y][x] = GLITCH_CHARS[k]
    return out


MATRIX_CHARS = "ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜﾝ0123456789"


def fx_matrix(art: Art, p: dict) -> Art:
    rng = Rng(_int(p.get("seed"), 0, 2 ** 31, 21))
    density = _float(p.get("density"), 0, 1, 0.5)
    base = _col(p.get("color")) or 0x33FF66
    r0, g0, b0 = split_rgb(base)
    h = art.height
    for x in range(art.width):
        head = rng.int(max(1, h))
        for y in range(h):
            k = rng.int(len(MATRIX_CHARS))
            rr = rng.next()
            if art.is_ink(x, y):
                art.chars[y][x] = MATRIX_CHARS[k]
                f = 1.0 if y == head else 0.55 + 0.45 * rr
                art.fg[y][x] = join_rgb(r0 * f, g0 * f, b0 * f) if y != head else 0xE8FFE8
            elif rr < density * 0.08:
                art.chars[y][x] = MATRIX_CHARS[k]
                art.fg[y][x] = join_rgb(r0 * 0.3, g0 * 0.3, b0 * 0.3)
    return art


ZALGO_UP = [chr(c) for c in list(range(0x0300, 0x0316)) + [0x033D, 0x033E, 0x033F, 0x0340, 0x0341, 0x0342, 0x0343, 0x0344, 0x0346, 0x034A, 0x034B, 0x034C, 0x0350, 0x0351, 0x0352, 0x0357, 0x035B, 0x0363, 0x0364, 0x0365, 0x0366, 0x0367, 0x0368, 0x0369, 0x036A, 0x036B, 0x036C, 0x036D, 0x036E, 0x036F]]
ZALGO_DOWN = [chr(c) for c in [0x0316, 0x0317, 0x0318, 0x0319, 0x031C, 0x031D, 0x031E, 0x031F, 0x0320, 0x0324, 0x0325, 0x0326, 0x0329, 0x032A, 0x032B, 0x032C, 0x032D, 0x032E, 0x032F, 0x0330, 0x0331, 0x0332, 0x0333, 0x0339, 0x033A, 0x033B, 0x033C, 0x0345, 0x0347, 0x0348, 0x0349, 0x034D, 0x034E, 0x0353, 0x0354, 0x0355, 0x0356, 0x0359, 0x035A]]


def zalgo_text(text: str, intensity: int = 2, seed: int = 3) -> str:
    rng = Rng(seed)
    out = []
    for c in text:
        out.append(c)
        if c.isspace():
            continue
        for _ in range(intensity):
            out.append(ZALGO_UP[rng.int(len(ZALGO_UP))])
            out.append(ZALGO_DOWN[rng.int(len(ZALGO_DOWN))])
    return "".join(out)


def fx_zalgo(art: Art, p: dict) -> Art:
    rng = Rng(_int(p.get("seed"), 0, 2 ** 31, 3))
    n = _int(p.get("intensity"), 1, 8, 2)
    for y in range(art.height):
        for x in range(art.width):
            if art.is_ink(x, y):
                marks = "".join(ZALGO_UP[rng.int(len(ZALGO_UP))] + ZALGO_DOWN[rng.int(len(ZALGO_DOWN))] for _ in range(n))
                art.chars[y][x] = art.chars[y][x] + marks
    return art


def fx_frame(art: Art, p: dict) -> Art:
    style = p.get("style", "rounded")
    pad = _int(p.get("padding"), 0, 10, 1)
    f = FRAMES.get(style, FRAMES["rounded"])
    color = _col(p.get("color"))
    title = str(p.get("title") or "")[:200]
    tl, top_c, tr, right_c, bl, br, left_c, bot_c = f[0], f[1], f[2], f[3], f[4], f[5], f[6], f[7]
    out = _grow(art, pad + 1, pad + 1 if style != "terminal" else pad + 2, pad + 1, pad + 1)
    w, h = out.width, out.height
    for x in range(w):
        out.chars[0][x] = top_c
        out.chars[h - 1][x] = bot_c
        out.fg[0][x] = out.fg[h - 1][x] = color
    for y in range(h):
        out.chars[y][0] = left_c
        out.chars[y][w - 1] = right_c
        out.fg[y][0] = out.fg[y][w - 1] = color
    out.chars[0][0], out.chars[0][w - 1], out.chars[h - 1][0], out.chars[h - 1][w - 1] = tl, tr, bl, br
    if style == "terminal":
        # title bar with window controls
        for x in range(1, w - 1):
            out.chars[2][x] = "─"
            out.fg[2][x] = color
        out.chars[2][0], out.chars[2][w - 1] = "├", "┤"
        dots = "● ● ●"
        for i, c in enumerate(dots):
            if 2 + i < w - 1:
                out.chars[1][2 + i] = c
        if title:
            start = max(8, (w - len(title)) // 2)
            for i, c in enumerate(title[: max(0, w - start - 2)]):
                out.chars[1][start + i] = c
    elif title:
        t = f" {title} "
        start = 2
        for i, c in enumerate(t[: max(0, w - 4)]):
            out.chars[0][start + i] = c
    return out


def fx_padding(art: Art, p: dict) -> Art:
    return _grow(art, _int(p.get("left"), 0, 50, 2), _int(p.get("top"), 0, 50, 1),
                 _int(p.get("right"), 0, 50, 2), _int(p.get("bottom"), 0, 50, 1))


def fx_glow(art: Art, p: dict) -> Art:
    art.meta["glow"] = {"color": p.get("color") or "#7aa2ff",
                        "radius": _int(p.get("radius"), 1, 40, 6),
                        "strength": _float(p.get("strength"), 0, 1, 0.8)}
    return art


EFFECTS = {
    "color": fx_color, "gradient": fx_gradient, "rainbow": fx_rainbow, "shadow": fx_shadow,
    "double_shadow": fx_double_shadow, "outline": fx_outline, "extrude": fx_extrude,
    "mirror": fx_mirror, "flip_v": fx_flip_v, "rotate": fx_rotate, "invert": fx_invert,
    "fill": fx_fill, "background": fx_background, "noise": fx_noise, "glitch": fx_glitch,
    "matrix": fx_matrix, "zalgo": fx_zalgo, "frame": fx_frame, "padding": fx_padding, "glow": fx_glow,
}


def apply_effects(art: Art, pipeline: list[dict]) -> Art:
    """Apply an effects pipeline to a copy of ``art`` (the input is never mutated)."""
    out = art.copy()
    for eff in pipeline or []:
        if not isinstance(eff, dict) or not eff.get("enabled", True):
            continue
        fn = EFFECTS.get(eff.get("type"))
        if fn is None:
            continue
        out = fn(out, eff)
        out.normalize()
        if out.width * out.height > MAX_EFFECT_CELLS:
            raise ValueError("effect output too large; reduce text, depth or padding")
    return out


def pipeline_representation(pipeline: list[dict]) -> dict:
    """Which targets can faithfully represent the enabled effects."""
    kinds = {EFFECT_INFO.get(e.get("type"), ("text",))[0] for e in pipeline or [] if e.get("enabled", True)}
    return {"plain_text": not (kinds & {"color", "graphic"}), "ansi": "graphic" not in kinds, "graphic": True,
            "lossy_in_text": sorted(EFFECT_INFO[e["type"]][1] for e in pipeline or []
                                    if e.get("enabled", True) and EFFECT_INFO.get(e.get("type"), ("text",))[0] != "text")}
