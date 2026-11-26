"""ExportManager: real, valid files in every supported format.

Text formats : TXT, ANSI (true colour / 256 / 16), HTML, SVG, Markdown,
               Python / JavaScript / C / C++ / PowerShell / Bash literals
Raster       : PNG, JPEG, WebP, BMP (Pillow); PNG and BMP also without Pillow
               using the bundled 8×16 DejaVu Sans Mono atlas
Project      : JSON (see project.py)
"""
from __future__ import annotations

import html
import io
import json
import struct
import zlib
from dataclasses import dataclass

from .art import Art, hex_to_rgb, rgb_to_hex, split_rgb
from .resources import load_resource

ANSI16 = [(0, 0, 0), (205, 49, 49), (13, 188, 121), (229, 229, 16), (36, 114, 200), (188, 63, 188), (17, 168, 205),
          (229, 229, 229), (102, 102, 102), (241, 76, 76), (35, 209, 139), (245, 245, 67), (59, 142, 234),
          (214, 112, 214), (41, 184, 219), (255, 255, 255)]


@dataclass
class ExportSettings:
    font_size: int = 16
    line_height: float = 1.2
    padding: int = 24
    background: str = "#0d1117"
    transparent: bool = False
    foreground: str = "#e6edf3"
    scale: float = 1.0
    ansi_mode: str = "truecolor"   # truecolor | 256 | 16 | none
    embed_font: bool = False
    jpeg_quality: int = 92
    title: str = "LeerBox Text Art"
    letter_spacing: float = 0.0    # extra horizontal space per cell, in cell widths

    @classmethod
    def from_dict(cls, d: dict | None) -> "ExportSettings":
        s = cls()
        for k, v in (d or {}).items():
            if hasattr(s, k):
                t = type(getattr(s, k))
                try:
                    setattr(s, k, t(v) if t is not bool else bool(v))
                except (TypeError, ValueError):
                    pass
        s.font_size = max(4, min(200, s.font_size))
        s.padding = max(0, min(1000, s.padding))
        s.scale = max(0.25, min(8.0, s.scale))
        s.line_height = max(0.8, min(3.0, s.line_height))
        s.jpeg_quality = max(10, min(100, s.jpeg_quality))
        s.letter_spacing = max(0.0, min(2.0, s.letter_spacing))
        return s


def _clean(c: str) -> str:
    return "".join(ch if (ord(ch) >= 32 and not 0x7F <= ord(ch) < 0xA0) else " " for ch in c)


# ---------------------------------------------------------------------------
# plain text & ANSI
# ---------------------------------------------------------------------------

def to_txt(art: Art) -> str:
    return "\n".join("".join(_clean(c) for c in row).rstrip() for row in art.chars) + "\n"


def rgb_to_256(c: int) -> int:
    r, g, b = split_rgb(c)
    if r == g == b:
        if r < 8:
            return 16
        if r > 248:
            return 231
        return 232 + int((r - 8) / 247 * 24 + 0.5)
    def q(v: int) -> int:
        return 0 if v < 48 else 1 if v < 115 else (v - 35) // 40
    return 16 + 36 * q(r) + 6 * q(g) + q(b)


def rgb_to_16(c: int) -> int:
    r, g, b = split_rgb(c)
    best, bd = 0, 1 << 30
    for i, (pr, pg, pb) in enumerate(ANSI16):
        d = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
        if d < bd:
            best, bd = i, d
    return best


def _sgr(fg: int | None, bg: int | None, mode: str) -> str:
    parts = ["0"]
    if fg is not None:
        if mode == "truecolor":
            parts.append("38;2;%d;%d;%d" % split_rgb(fg))
        elif mode == "256":
            parts.append(f"38;5;{rgb_to_256(fg)}")
        else:
            i = rgb_to_16(fg)
            parts.append(str(30 + i if i < 8 else 90 + i - 8))
    if bg is not None:
        if mode == "truecolor":
            parts.append("48;2;%d;%d;%d" % split_rgb(bg))
        elif mode == "256":
            parts.append(f"48;5;{rgb_to_256(bg)}")
        else:
            i = rgb_to_16(bg)
            parts.append(str(40 + i if i < 8 else 100 + i - 8))
    return "\x1b[" + ";".join(parts) + "m"


def to_ansi(art: Art, mode: str = "truecolor") -> str:
    if mode == "none":
        return to_txt(art)
    lines = []
    for y, row in enumerate(art.chars):
        out = []
        cur = (None, None)
        last = len(row)
        while last > 0 and row[last - 1] in (" ", "") and art.bg[y][last - 1] is None:
            last -= 1
        for x in range(last):
            c = row[x]
            if c == "":
                continue
            st = (art.fg[y][x] if c != " " else None, art.bg[y][x])
            if st != cur:
                out.append(_sgr(st[0], st[1], mode) if st != (None, None) else "\x1b[0m")
                cur = st
            out.append(_clean(c))
        if cur != (None, None):
            out.append("\x1b[0m")
        lines.append("".join(out))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# HTML / SVG
# ---------------------------------------------------------------------------

FONT_STACK = "'DejaVu Sans Mono','Cascadia Mono',Consolas,Menlo,'Liberation Mono',monospace"


def _runs(art: Art, y: int):
    """Yield (x, text, fg, bg) runs of equal colour in row y."""
    row = art.chars[y]
    x = 0
    w = len(row)
    while x < w:
        fg, bg = art.fg[y][x], art.bg[y][x]
        start = x
        buf = []
        while x < w and art.fg[y][x] == fg and art.bg[y][x] == bg:
            buf.append(_clean(row[x]) if row[x] != "" else "")
            x += 1
        yield start, "".join(buf), fg, bg


def _font_face_css() -> str:
    import base64
    ttf = zlib.decompress(load_resource("DejaVuSansMono.ttf.z"))
    return ("@font-face{font-family:'DejaVu Sans Mono';src:url(data:font/ttf;base64,"
            + base64.b64encode(ttf).decode("ascii") + ") format('truetype');}")


def to_html_fragment(art: Art, s: ExportSettings | None = None) -> str:
    s = s or ExportSettings()
    glow = art.meta.get("glow")
    shadow = ""
    if glow:
        shadow = f"text-shadow:0 0 {glow['radius']}px {html.escape(glow['color'])},0 0 {glow['radius'] * 2}px {html.escape(glow['color'])};"
    bg = "transparent" if s.transparent else html.escape(s.background)
    parts = [f'<pre style="margin:0;padding:{s.padding}px;background:{bg};color:{html.escape(s.foreground)};'
             f'font:{s.font_size}px/{s.line_height} {FONT_STACK};{shadow}white-space:pre'
             + (f';letter-spacing:{s.letter_spacing * 0.6021:.3f}em' if s.letter_spacing else "") + '">']
    for y in range(art.height):
        for _, text, fg, bgc in _runs(art, y):
            esc = html.escape(text, quote=False)
            if fg is None and bgc is None:
                parts.append(esc)
            else:
                st = (f"color:{rgb_to_hex(fg)};" if fg is not None else "") + (f"background:{rgb_to_hex(bgc)};" if bgc is not None else "")
                parts.append(f'<span style="{st}">{esc}</span>')
        parts.append("\n")
    parts.append("</pre>")
    return "".join(parts)


def to_html(art: Art, s: ExportSettings | None = None) -> str:
    s = s or ExportSettings()
    css = _font_face_css() if s.embed_font else ""
    page_bg = "transparent" if s.transparent else html.escape(s.background)
    return ("<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{html.escape(s.title)}</title><style>{css}body{{margin:0;background:{page_bg}}}</style></head>"
            f"<body>{to_html_fragment(art, s)}</body></html>\n")


def _cell_metrics(s: ExportSettings) -> tuple[float, float]:
    fs = s.font_size * s.scale
    return fs * 0.6021 * (1 + s.letter_spacing), fs * s.line_height


def to_svg(art: Art, s: ExportSettings | None = None) -> str:
    s = s or ExportSettings()
    cw, ch = _cell_metrics(s)
    pad = s.padding * s.scale
    fs = s.font_size * s.scale
    W = round(art.width * cw + 2 * pad, 2)
    H = round(art.height * ch + 2 * pad, 2)
    glow = art.meta.get("glow")
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">']
    style = f"text{{font-family:{FONT_STACK};font-size:{fs:.2f}px;white-space:pre}}"
    if s.embed_font:
        style = _font_face_css() + style
    out.append(f"<style>{html.escape(style, quote=False)}</style>")
    if glow:
        sd = max(0.5, glow["radius"] * s.scale / 2)
        out.append(f'<defs><filter id="glow" x="-20%" y="-20%" width="140%" height="140%">'
                   f'<feGaussianBlur stdDeviation="{sd:.2f}" result="b"/>'
                   f'<feFlood flood-color="{html.escape(glow["color"])}" flood-opacity="{glow["strength"]:.2f}"/>'
                   f'<feComposite in2="b" operator="in" result="g"/><feMerge><feMergeNode in="g"/>'
                   f'<feMergeNode in="SourceGraphic"/></feMerge></filter></defs>')
    if not s.transparent:
        out.append(f'<rect width="100%" height="100%" fill="{html.escape(s.background)}"/>')
    for y in range(art.height):
        for x0, text, fg, bgc in _runs(art, y):
            if bgc is not None:
                out.append(f'<rect x="{pad + x0 * cw:.2f}" y="{pad + y * ch:.2f}" width="{len(text) * cw + 0.5:.2f}" '
                           f'height="{ch + 0.5:.2f}" fill="{rgb_to_hex(bgc)}"/>')
    out.append(f'<g{" filter=\"url(#glow)\"" if glow else ""} fill="{html.escape(s.foreground)}">')
    base = fs * 0.8 + (ch - fs) / 2
    for y in range(art.height):  # block elements and sextants are exact rectangles (no font gaps)
        for x in range(art.width):
            c = art.chars[y][x]
            rects = _BLOCKS.get(c)
            if rects:
                fg = art.fg[y][x]
                fill = f' fill="{rgb_to_hex(fg)}"' if fg is not None else ""
                for a, b, c2, d in rects:
                    out.append(f'<rect x="{pad + (x + a) * cw:.2f}" y="{pad + (y + b) * ch:.2f}" width="{(c2 - a) * cw + 0.3:.2f}" '
                               f'height="{(d - b) * ch + 0.3:.2f}"{fill}/>')
    for y in range(art.height):
        spans = []
        for x0, text, fg, bgc in _runs(art, y):
            if any(ch_ in _BLOCKS for ch_ in text):
                text = "".join(" " if ch_ in _BLOCKS else ch_ for ch_ in text)
            if not text.strip():
                continue
            # position each cell explicitly so non-monospace fallback glyphs cannot drift
            stripped_l = len(text) - len(text.lstrip(" "))
            t = text.strip(" ")
            fill = f' fill="{rgb_to_hex(fg)}"' if fg is not None else ""
            xs = " ".join(f"{pad + (x0 + stripped_l + i) * cw:.2f}" for i in range(len(t)))
            spans.append(f'<tspan x="{xs}"{fill}>{html.escape(t, quote=False)}</tspan>')
        if spans:
            out.append(f'<text y="{pad + y * ch + base:.2f}" xml:space="preserve">{"".join(spans)}</text>')
    out.append("</g></svg>\n")
    return "".join(out)


# ---------------------------------------------------------------------------
# Markdown & source literals
# ---------------------------------------------------------------------------

def to_markdown(art: Art, title: str = "") -> str:
    body = to_txt(art).rstrip("\n")
    fence = "```"
    while fence in body:
        fence += "`"
    head = f"## {title}\n\n" if title else ""
    return f"{head}{fence}text\n{body}\n{fence}\n"


def _lines(art: Art, ansi: str | None) -> list[str]:
    text = to_ansi(art, ansi) if ansi else to_txt(art)
    return text.rstrip("\n").split("\n")


def _esc_c_like(s: str, quote: str = '"', non_ascii: str = "keep") -> str:
    out = []
    for ch in s:
        o = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif ch == quote:
            out.append("\\" + quote)
        elif ch == "\x1b":
            out.append("\\x1b" if non_ascii != "octal" else "\\033")
        elif o < 32 or o == 127:
            out.append(f"\\x{o:02x}" if non_ascii != "octal" else f"\\{o:03o}")
        elif o > 127 and non_ascii == "octal":
            out.extend(f"\\{b:03o}" for b in ch.encode("utf-8"))
        else:
            out.append(ch)
    return "".join(out)


def to_code(art: Art, lang: str, var: str = "ART", ansi: str | None = None) -> str:
    lines = _lines(art, ansi)
    if lang == "python":
        body = "\n".join(f'    "{_esc_c_like(ln)}\\n"' for ln in lines)
        return f"{var} = (\n{body}\n)\nprint({var}, end=\"\")\n"
    if lang == "javascript":
        body = ",\n".join(f'  "{_esc_c_like(ln).replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")}"' for ln in lines)
        return f"const {var.lower()} = [\n{body}\n].join(\"\\n\");\nconsole.log({var.lower()});\n"
    if lang in ("c", "cpp"):
        body = "\n".join(f'    "{_esc_c_like(ln, non_ascii="octal")}\\n"' for ln in lines)
        if lang == "c":
            return f"#include <stdio.h>\n\nstatic const char *{var.lower()} =\n{body};\n\nint main(void) {{\n    fputs({var.lower()}, stdout);\n    return 0;\n}}\n"
        return f"#include <iostream>\n\nstatic const char *{var.lower()} =\n{body};\n\nint main() {{\n    std::cout << {var.lower()};\n    return 0;\n}}\n"
    if lang == "powershell":
        # single-quoted here-strings are literal; fall back to escaped strings when a line starts with '@
        if ansi or any(ln.lstrip().startswith("'@") for ln in lines):
            def ps(s: str) -> str:
                return s.replace("`", "``").replace('"', '`"').replace("$", "`$").replace("\x1b", "`e")
            body = ",\n".join(f'    "{ps(ln)}"' for ln in lines)
            return f"${var} = @(\n{body}\n) -join [Environment]::NewLine\nWrite-Output ${var}\n"
        return f"${var} = @'\n" + "\n".join(lines) + f"\n'@\nWrite-Output ${var}\n"
    if lang == "bash":
        if ansi:
            def sh(s: str) -> str:
                return s.replace("\\", "\\\\").replace("'", "\\'").replace("\x1b", "\\e")
            return "#!/usr/bin/env bash\nprintf '%s\\n' \\\n" + " \\\n".join(f"  $'{sh(ln)}'" for ln in lines) + "\n"
        delim = "LEERBOX_ART"
        while any(ln.strip() == delim for ln in lines):
            delim += "_"
        return f"#!/usr/bin/env bash\ncat <<'{delim}'\n" + "\n".join(lines) + f"\n{delim}\n"
    raise ValueError(f"unknown language {lang!r}")


CODE_LANGS = {"python": "Python", "javascript": "JavaScript", "c": "C", "cpp": "C++", "powershell": "PowerShell", "bash": "Bash"}


# ---------------------------------------------------------------------------
# raster export
# ---------------------------------------------------------------------------

def _have_pillow() -> bool:
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False


HAVE_PILLOW = _have_pillow()

_BLOCKS = {
    "█": [(0, 0, 1, 1)], "▀": [(0, 0, 1, .5)], "▄": [(0, .5, 1, 1)], "▌": [(0, 0, .5, 1)], "▐": [(.5, 0, 1, 1)],
    "▖": [(0, .5, .5, 1)], "▗": [(.5, .5, 1, 1)], "▘": [(0, 0, .5, .5)], "▝": [(.5, 0, 1, .5)],
    "▙": [(0, 0, .5, 1), (.5, .5, 1, 1)], "▚": [(0, 0, .5, .5), (.5, .5, 1, 1)], "▛": [(0, 0, 1, .5), (0, .5, .5, 1)],
    "▜": [(0, 0, 1, .5), (.5, .5, 1, 1)], "▞": [(.5, 0, 1, .5), (0, .5, .5, 1)], "▟": [(.5, 0, 1, 1), (0, .5, .5, 1)],
    "▁": [(0, .875, 1, 1)], "▂": [(0, .75, 1, 1)], "▃": [(0, .625, 1, 1)], "▅": [(0, .375, 1, 1)], "▆": [(0, .25, 1, 1)],
    "▇": [(0, .125, 1, 1)], "▉": [(0, 0, .875, 1)], "▊": [(0, 0, .75, 1)], "▋": [(0, 0, .625, 1)], "▍": [(0, 0, .375, 1)],
    "▎": [(0, 0, .25, 1)], "▏": [(0, 0, .125, 1)], "▔": [(0, 0, 1, .125)], "▕": [(.875, 0, 1, 1)],
}
for _bits in range(1, 63):
    if _bits in (21, 42):
        continue
    _n = _bits - 1 - (1 if _bits > 21 else 0) - (1 if _bits > 42 else 0)
    _BLOCKS[chr(0x1FB00 + _n)] = [((_b % 2) / 2, (_b // 2) / 3, (_b % 2 + 1) / 2, (_b // 2 + 1) / 3)
                                  for _b in range(6) if _bits >> _b & 1]
_SHADES = {"░": 0.25, "▒": 0.5, "▓": 0.75}


def _image_size(art: Art, s: ExportSettings) -> tuple[int, int, float, float, float]:
    cw, ch = _cell_metrics(s)
    pad = s.padding * s.scale
    W = int(art.width * cw + 2 * pad + 0.999)
    H = int(art.height * ch + 2 * pad + 0.999)
    if W * H > 120_000_000 or W > 30000 or H > 30000:
        raise ValueError(f"image would be {W}×{H}px; reduce scale, font size or text")
    return W, H, cw, ch, pad


def render_image(art: Art, s: ExportSettings | None = None):
    """Rasterize with Pillow. Returns an RGBA PIL image."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    s = s or ExportSettings()
    W, H, cw, ch, pad = _image_size(art, s)
    bg = (0, 0, 0, 0) if s.transparent else (*split_rgb(hex_to_rgb(s.background)), 255)
    img = Image.new("RGBA", (W, H), bg)
    fs = max(4, int(s.font_size * s.scale + 0.5))
    mono = ImageFont.truetype(io.BytesIO(zlib.decompress(load_resource("DejaVuSansMono.ttf.z"))), fs)
    sans = ImageFont.truetype(io.BytesIO(zlib.decompress(load_resource("DejaVuSans.ttf.z"))), fs)
    notdef = bytes(mono.getmask("\ue000"))
    have: dict[str, object] = {}
    def font_for(c: str):
        if c not in have:
            have[c] = mono if bytes(mono.getmask(c)) != notdef else sans
        return have[c]
    text_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    td = ImageDraw.Draw(text_layer)
    bd = ImageDraw.Draw(img)
    default_fg = (*split_rgb(hex_to_rgb(s.foreground)), 255)
    base = (ch - fs) / 2 + fs * 0.8  # baseline offset inside a cell
    for y in range(art.height):
        for x in range(art.width):
            c = art.chars[y][x]
            x0, y0 = pad + x * cw, pad + y * ch
            if art.bg[y][x] is not None:
                bd.rectangle([int(x0), int(y0), int(x0 + cw + 0.999), int(y0 + ch + 0.999)], fill=(*split_rgb(art.bg[y][x]), 255))
            if c in (" ", "", "\u2800"):
                continue
            col = (*split_rgb(art.fg[y][x]), 255) if art.fg[y][x] is not None else default_fg
            if c in _BLOCKS:
                for a, b, cc, d in _BLOCKS[c]:
                    td.rectangle([int(x0 + a * cw), int(y0 + b * ch), int(x0 + cc * cw + 0.999) - 1, int(y0 + d * ch + 0.999) - 1], fill=col)
            elif c in _SHADES:
                td.rectangle([int(x0), int(y0), int(x0 + cw + 0.999) - 1, int(y0 + ch + 0.999) - 1],
                             fill=(col[0], col[1], col[2], int(255 * _SHADES[c])))
            elif 0x2801 <= ord(c[0]) <= 0x28FF:
                v = ord(c[0]) - 0x2800
                dots = [(0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2), (0, 3), (1, 3)]
                r = max(1.0, min(cw / 4, ch / 8) * 0.8)
                for bit, (dx, dy) in enumerate(dots):
                    if v >> bit & 1:
                        cx, cy = x0 + cw * (0.3 + 0.4 * dx), y0 + ch * (0.14 + 0.24 * dy)
                        td.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
            else:
                td.text((x0, y0 + base), c, font=font_for(c[0]), fill=col, anchor="ls")
    glow = art.meta.get("glow")
    if glow:
        gc = split_rgb(hex_to_rgb(glow["color"]))
        alpha = text_layer.getchannel("A")
        blurred = alpha.filter(ImageFilter.GaussianBlur(max(1, glow["radius"] * s.scale / 2)))
        blurred = blurred.point(lambda v: min(255, int(v * (1 + glow["strength"]))))
        glow_img = Image.new("RGBA", (W, H), (*gc, 0))
        glow_img.putalpha(blurred)
        img = Image.alpha_composite(img, glow_img)
    return Image.alpha_composite(img, text_layer)


def to_raster_bytes(art: Art, fmt: str, s: ExportSettings | None = None) -> bytes:
    s = s or ExportSettings()
    fmt = fmt.lower()
    if not HAVE_PILLOW:
        if fmt in ("png", "bmp"):
            return _fallback_raster(art, fmt, s)
        raise RuntimeError(f"{fmt.upper()} export requires Pillow (pip install pillow)")
    from PIL import Image
    Image.init()  # register all codec plugins (Pillow 13 loads WebP lazily)
    if fmt == "webp" and "WEBP" not in Image.SAVE:
        raise RuntimeError("this Pillow build has no WebP encoder")
    img = render_image(art, s)
    buf = io.BytesIO()
    if fmt == "png":
        img.save(buf, "PNG", optimize=True)
    elif fmt == "webp":
        img.save(buf, "WEBP", quality=s.jpeg_quality, lossless=s.jpeg_quality >= 100)
    elif fmt in ("jpg", "jpeg"):
        flat = Image.new("RGB", img.size, split_rgb(hex_to_rgb(s.background)))
        flat.paste(img, mask=img.getchannel("A"))
        flat.save(buf, "JPEG", quality=s.jpeg_quality, optimize=True)
    elif fmt == "bmp":
        flat = Image.new("RGB", img.size, split_rgb(hex_to_rgb(s.background)))
        flat.paste(img, mask=img.getchannel("A"))
        flat.save(buf, "BMP")
    else:
        raise ValueError(f"unknown image format {fmt!r}")
    return buf.getvalue()


_ATLAS: dict | None = None


def _fallback_raster(art: Art, fmt: str, s: ExportSettings) -> bytes:
    """Pure-Python PNG/BMP writer using the bundled 8×16 bitmap atlas (integer scale)."""
    global _ATLAS
    if _ATLAS is None:
        _ATLAS = json.loads(load_resource("mono_atlas.json").decode("utf-8"))
    k = max(1, int(round(s.scale * s.font_size / 16)))
    cw, ch, pad = 8 * k, 16 * k, int(s.padding * s.scale)
    W, H = art.width * cw + 2 * pad, art.height * ch + 2 * pad
    if W * H > 60_000_000:
        raise ValueError("image too large")
    bgc = split_rgb(hex_to_rgb(s.background))
    alpha = fmt == "png" and s.transparent
    bpp = 4 if alpha else 3
    px = bytearray((list(bgc) + ([0] if alpha else [])) * (W * H))
    dfg = split_rgb(hex_to_rgb(s.foreground))
    def put(x: int, y: int, c: tuple) -> None:
        if 0 <= x < W and 0 <= y < H:
            i = (y * W + x) * bpp
            px[i:i + 3] = bytes(c)
            if alpha:
                px[i + 3] = 255
    for y in range(art.height):
        for x in range(art.width):
            c = art.chars[y][x]
            x0, y0 = pad + x * cw, pad + y * ch
            if art.bg[y][x] is not None:
                b = split_rgb(art.bg[y][x])
                for yy in range(ch):
                    for xx in range(cw):
                        put(x0 + xx, y0 + yy, b)
            if c in (" ", ""):
                continue
            col = split_rgb(art.fg[y][x]) if art.fg[y][x] is not None else dfg
            if c in _BLOCKS or c in _SHADES:
                rects = _BLOCKS.get(c, [(0, 0, 1, 1)])
                dens = _SHADES.get(c, 1.0)
                for a, b, cc, d in rects:
                    for yy in range(int(b * ch), int(d * ch)):
                        for xx in range(int(a * cw), int(cc * cw)):
                            if dens >= 1 or ((xx // k + yy // k) % (4 if dens < .4 else 2) == 0) or (dens > .6 and (xx // k) % 2):
                                put(x0 + xx, y0 + yy, col)
                continue
            if 0x2801 <= ord(c[0]) <= 0x28FF:
                v = ord(c[0]) - 0x2800
                for bit, (dx, dy) in enumerate([(0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2), (0, 3), (1, 3)]):
                    if v >> bit & 1:
                        for yy in range(2 * k):
                            for xx in range(2 * k):
                                put(x0 + (1 + 4 * dx) * k + xx, y0 + (1 + 4 * dy) * k + yy, col)
                continue
            g = _ATLAS["g"].get(c[0]) or _ATLAS["g"].get("?")
            for yy in range(16):
                row = int(g[yy * 2:yy * 2 + 2], 16)
                for xx in range(8):
                    if row >> xx & 1:
                        for sy in range(k):
                            for sx in range(k):
                                put(x0 + xx * k + sx, y0 + yy * k + sy, col)
    if fmt == "bmp":
        return encode_bmp(W, H, px, bpp)
    return encode_png(W, H, px, bpp)


def encode_png(w: int, h: int, px: bytes | bytearray, bpp: int) -> bytes:
    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    stride = w * bpp
    raw = b"".join(b"\0" + bytes(px[y * stride:(y + 1) * stride]) for y in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">2I5B", w, h, 8, 6 if bpp == 4 else 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def encode_bmp(w: int, h: int, px: bytes | bytearray, bpp: int) -> bytes:
    row_size = (w * 3 + 3) & ~3
    data = bytearray()
    for y in range(h - 1, -1, -1):
        row = bytearray()
        for x in range(w):
            i = (y * w + x) * bpp
            row += bytes((px[i + 2], px[i + 1], px[i]))
        row += b"\0" * (row_size - w * 3)
        data += row
    header = b"BM" + struct.pack("<IHHI", 54 + len(data), 0, 0, 54)
    info = struct.pack("<IiiHHIIiiII", 40, w, h, 1, 24, 0, len(data), 2835, 2835, 0, 0)
    return header + info + bytes(data)


# ---------------------------------------------------------------------------
# dispatcher
# ---------------------------------------------------------------------------

FORMATS = {
    "txt": ("Plain text", ".txt"), "ansi": ("ANSI art", ".ans"), "html": ("HTML page", ".html"),
    "svg": ("SVG vector", ".svg"), "png": ("PNG image", ".png"), "jpeg": ("JPEG image", ".jpg"),
    "webp": ("WebP image", ".webp"), "bmp": ("BMP image", ".bmp"), "md": ("Markdown", ".md"),
    "py": ("Python literal", ".py"), "js": ("JavaScript literal", ".js"), "c": ("C literal", ".c"),
    "cpp": ("C++ literal", ".cpp"), "ps1": ("PowerShell string", ".ps1"), "sh": ("Bash string", ".sh"),
}


def export_bytes(art: Art, fmt: str, s: ExportSettings | None = None) -> bytes:
    s = s or ExportSettings()
    if fmt == "txt":
        return to_txt(art).encode("utf-8")
    if fmt == "ansi":
        return to_ansi(art, s.ansi_mode).encode("utf-8")
    if fmt == "html":
        return to_html(art, s).encode("utf-8")
    if fmt == "svg":
        return to_svg(art, s).encode("utf-8")
    if fmt == "md":
        return to_markdown(art, s.title if s.title != "LeerBox Text Art" else "").encode("utf-8")
    code = {"py": "python", "js": "javascript", "c": "c", "cpp": "cpp", "ps1": "powershell", "sh": "bash"}
    if fmt in code:
        data = to_code(art, code[fmt])
        return (("\ufeff" if fmt == "ps1" else "") + data).encode("utf-8")
    if fmt in ("png", "jpeg", "jpg", "webp", "bmp"):
        return to_raster_bytes(art, fmt, s)
    raise ValueError(f"unknown export format {fmt!r}")
