"""FIGfont / TOIlet font parser and layout engine.

Implements the FIGfont 2.0 specification:
  * FLF ("flf2a") and TLF ("tlf2a") headers, comments, hardblanks and endmarks
  * the 95 required ASCII glyphs, the 7 optional Deutsch glyphs and code-tagged
    glyphs (decimal, octal and hexadecimal tags)
  * horizontal layouts: full width, fitting (kerning), controlled smushing
    (rules 1-6) and universal smushing
  * vertical layouts: full height, fitting, controlled smushing (rules 1-5)
    and universal smushing
  * left-to-right and right-to-left print direction
  * zipped fonts (figlet supports fonts stored inside a ZIP container)

The horizontal algorithm mirrors figlet 2.2.5 / pyfiglet (``smushamt`` and
``smushem``) so output is byte-for-byte comparable with the reference
implementations. The shared JavaScript engine (web/src/engine/figlet.js) is a
line-by-line port of this module and is verified against the same golden
fixtures.
"""
from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass, field

# Layout bits (FIGfont 2.0 "full_layout")
SM_EQUAL = 1
SM_LOWLINE = 2
SM_HIERARCHY = 4
SM_PAIR = 8
SM_BIGX = 16
SM_HARDBLANK = 32
SM_KERN = 64
SM_SMUSH = 128
VSM_EQUAL = 256
VSM_LOWLINE = 512
VSM_HIERARCHY = 1024
VSM_HLINE = 2048
VSM_VLINE = 4096
VSM_KERN = 8192
VSM_SMUSH = 16384

DEUTSCH = (196, 214, 220, 228, 246, 252, 223)

MAX_FONT_BYTES = 6 * 1024 * 1024
MAX_FONT_HEIGHT = 256
MAX_LINE_LENGTH = 4000
MAX_GLYPHS = 70000

_CODETAG_RE = re.compile(r"^\s*(-?)(0[xX][0-9a-fA-F]+|0[0-7]*|[1-9][0-9]*)(?:\s|$)")


class FontError(ValueError):
    """Raised when a font file is malformed or violates safety limits."""


@dataclass
class FigFont:
    name: str
    kind: str  # 'flf' | 'tlf'
    hardblank: str
    height: int
    baseline: int
    max_length: int
    old_layout: int
    comment_lines: int
    print_direction: int
    full_layout: int
    codetag_count: int
    comment: str
    glyphs: dict[int, list[str]] = field(default_factory=dict)

    # ---- derived layout -------------------------------------------------
    @property
    def h_mode(self) -> int:
        """Horizontal smush mode bits (figlet's ``smush2``)."""
        return self.full_layout & (63 | SM_KERN | SM_SMUSH)

    @property
    def v_mode(self) -> int:
        return self.full_layout & (VSM_EQUAL | VSM_LOWLINE | VSM_HIERARCHY | VSM_HLINE
                                    | VSM_VLINE | VSM_KERN | VSM_SMUSH)

    def has(self, cp: int) -> bool:
        return cp in self.glyphs

    @property
    def max_width(self) -> int:
        return max((len(g[0]) for g in self.glyphs.values() if g), default=0)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def decode_font_bytes(raw: bytes) -> tuple[str, str]:
    """Return (text, kind). Handles ZIP containers, BOMs and legacy encodings."""
    if len(raw) > MAX_FONT_BYTES:
        raise FontError("font file exceeds size limit")
    if raw[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                infos = [i for i in zf.infolist() if not i.is_dir()]
                if not infos:
                    raise FontError("empty zipped font")
                info = infos[0]
                if info.file_size > MAX_FONT_BYTES:
                    raise FontError("zipped font exceeds size limit")
                if info.compress_size and info.file_size / max(1, info.compress_size) > 200:
                    raise FontError("suspicious compression ratio")
                with zf.open(info) as fh:
                    raw = fh.read(MAX_FONT_BYTES + 1)
                if len(raw) > MAX_FONT_BYTES:
                    raise FontError("zipped font exceeds size limit")
        except zipfile.BadZipFile as exc:
            raise FontError(f"bad zipped font: {exc}") from None
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    head = raw[:5]
    if head == b"tlf2a":
        kind = "tlf"
    elif head == b"flf2a":
        kind = "flf"
    else:
        raise FontError("not a FIGlet (flf2a) or TOIlet (tlf2a) font")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        if kind == "tlf":
            text = raw.decode("utf-8", errors="replace")
        else:
            text = raw.decode("latin-1")
    return text, kind


def _hdr_int(tok: str, default: int | None = None) -> int:
    try:
        return int(tok)
    except (TypeError, ValueError):
        if default is None:
            raise FontError(f"invalid header number: {tok!r}") from None
        return default


def parse_font(data: bytes | str, name: str = "font") -> FigFont:
    """Parse FLF/TLF data into a :class:`FigFont`."""
    if isinstance(data, bytes):
        text, kind = decode_font_bytes(data)
    else:
        if len(data) > MAX_FONT_BYTES:
            raise FontError("font text exceeds size limit")
        text = data.lstrip("﻿")
        kind = "tlf" if text.startswith("tlf2a") else "flf"
        if not text.startswith(("flf2a", "tlf2a")):
            raise FontError("not a FIGlet (flf2a) or TOIlet (tlf2a) font")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    header = lines[0].split()
    magic = header[0] if header else ""
    if len(magic) < 6 or magic[:5] not in ("flf2a", "tlf2a"):
        raise FontError("invalid signature")
    hardblank = magic[5]
    if len(header) < 6:
        raise FontError("header has too few fields")
    height = _hdr_int(header[1])
    baseline = _hdr_int(header[2])
    max_length = _hdr_int(header[3])
    old_layout = _hdr_int(header[4])
    comment_lines = _hdr_int(header[5])
    print_direction = _hdr_int(header[6], 0) if len(header) > 6 else 0
    full_layout = _hdr_int(header[7], -1) if len(header) > 7 else -1
    codetag_count = _hdr_int(header[8], 0) if len(header) > 8 else 0
    if not 1 <= height <= MAX_FONT_HEIGHT:
        raise FontError(f"invalid font height {height}")
    if comment_lines < 0 or comment_lines > len(lines):
        raise FontError("invalid comment line count")
    if old_layout < -1 or old_layout > 63:
        # tolerate out-of-range values by masking, as figlet does
        old_layout = max(-1, min(63, old_layout))
    if full_layout < 0:
        if old_layout == 0:
            full_layout = SM_KERN
        elif old_layout < 0:
            full_layout = 0
        else:
            full_layout = (old_layout & 31) | SM_SMUSH
    full_layout &= 32767
    if print_direction not in (0, 1):
        print_direction = 0

    comment = "\n".join(lines[1:1 + comment_lines])
    pos = 1 + comment_lines
    glyphs: dict[int, list[str]] = {}
    n_lines = len(lines)

    def read_glyph() -> list[str] | None:
        nonlocal pos
        if pos + height > n_lines:
            return None
        rows = []
        for i in range(height):
            line = lines[pos + i]
            if len(line) > MAX_LINE_LENGTH:
                raise FontError("glyph line too long")
            k = len(line) - 1
            while k >= 0 and line[k].isspace():
                k -= 1
            if k >= 0:
                end = line[k]
                while k >= 0 and line[k] == end:
                    k -= 1
            rows.append(line[:k + 1])
        pos += height
        width = max(len(r) for r in rows)
        return [r.ljust(width) for r in rows]

    def looks_like_codetag(idx: int) -> bool:
        if idx >= n_lines:
            return False
        m = _CODETAG_RE.match(lines[idx])
        if not m:
            return False
        nxt = lines[idx + 1:idx + 1 + height]
        if len(nxt) < height:
            return False
        ends = {ln.rstrip()[-1:] for ln in nxt}
        if len(ends) != 1 or not next(iter(ends)):
            return False
        return lines[idx].rstrip()[-1:] not in ends

    for cp in range(32, 127):
        g = read_glyph()
        if g is None:
            if cp == 32:
                raise FontError("truncated font: no glyphs")
            break
        glyphs[cp] = g
    if len(glyphs) == 95:
        for cp in DEUTSCH:
            if pos >= n_lines or not lines[pos].strip() and pos + 1 >= n_lines:
                break
            if looks_like_codetag(pos):
                break
            g = read_glyph()
            if g is None:
                break
            glyphs[cp] = g
        while pos < n_lines:
            line = lines[pos]
            if not line.strip():
                pos += 1
                continue
            m = _CODETAG_RE.match(line)
            if not m:
                break
            neg, tok = m.group(1), m.group(2)
            if tok.lower().startswith("0x"):
                cp = int(tok, 16)
            elif tok.startswith("0") and len(tok) > 1:
                cp = int(tok, 8)
            else:
                cp = int(tok)
            pos += 1
            g = read_glyph()
            if g is None:
                break
            if neg or cp > 0x10FFFF:
                continue  # negative codes are reserved; never reachable from text
            glyphs[cp] = g
            if len(glyphs) > MAX_GLYPHS:
                raise FontError("too many glyphs")
    if 32 not in glyphs:
        raise FontError("font has no space glyph")
    return FigFont(name=name, kind=kind, hardblank=hardblank, height=height,
                   baseline=baseline, max_length=max_length, old_layout=old_layout,
                   comment_lines=comment_lines, print_direction=print_direction,
                   full_layout=full_layout, codetag_count=codetag_count,
                   comment=comment, glyphs=glyphs)


# ---------------------------------------------------------------------------
# Unicode helpers (grapheme clusters, widths, fallbacks)
# ---------------------------------------------------------------------------

def _is_mark(ch: str) -> bool:
    return unicodedata.category(ch) in ("Mn", "Me", "Mc")


def graphemes(text: str) -> list[str]:
    """Simplified extended grapheme cluster segmentation.

    Clusters a base character with following combining marks, variation
    selectors, ZWJ sequences and regional-indicator pairs. The JavaScript
    edition implements the identical algorithm so both editions agree.
    """
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        j = i + 1
        ch = text[i]
        if ch == "\r" and j < n and text[j] == "\n":
            out.append("\n")
            i = j + 1
            continue
        if 0x1F1E6 <= ord(ch) <= 0x1F1FF and j < n and 0x1F1E6 <= ord(text[j]) <= 0x1F1FF:
            j += 1
        while j < n:
            c = text[j]
            o = ord(c)
            if _is_mark(c) or 0xFE00 <= o <= 0xFE0F or 0xE0100 <= o <= 0xE01EF or 0x1F3FB <= o <= 0x1F3FF:
                j += 1
            elif o == 0x200D and j + 1 < n:
                j += 2
            else:
                break
        out.append(text[i:j])
        i = j
    return out


_WIDE_RANGES = (
    (0x1100, 0x115F), (0x2E80, 0x303E), (0x3041, 0x33FF), (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF), (0xA000, 0xA4CF), (0xAC00, 0xD7A3), (0xF900, 0xFAFF),
    (0xFE30, 0xFE4F), (0xFF00, 0xFF60), (0xFFE0, 0xFFE6), (0x1F300, 0x1F64F),
    (0x1F900, 0x1F9FF), (0x20000, 0x2FFFD), (0x30000, 0x3FFFD),
)


def char_width(ch: str) -> int:
    """Terminal display width of a grapheme cluster (0, 1 or 2)."""
    if not ch:
        return 0
    o = ord(ch[0])
    if o < 32 or 0x7F <= o < 0xA0:
        return 0
    if _is_mark(ch[0]) or o == 0x200B:
        return 0
    for a, b in _WIDE_RANGES:
        if a <= o <= b:
            return 2
    return 1


def fallback_codepoint(font_has, cluster: str) -> int | None:
    """Pick the best code point a font can draw for a grapheme cluster."""
    if len(cluster) == 1 and font_has(ord(cluster)):
        return ord(cluster)
    nfc = unicodedata.normalize("NFC", cluster)
    if len(nfc) == 1 and font_has(ord(nfc)):
        return ord(nfc)
    base = cluster[0]
    if font_has(ord(base)):
        return ord(base)
    decomposed = unicodedata.normalize("NFKD", base)
    stripped = "".join(c for c in decomposed if not _is_mark(c))
    if len(stripped) == 1 and font_has(ord(stripped)):
        return ord(stripped)
    for alt in (base.upper(), base.lower(), stripped.upper(), stripped.lower()):
        if len(alt) == 1 and font_has(ord(alt)):
            return ord(alt)
    return None


# ---------------------------------------------------------------------------
# Horizontal layout
# ---------------------------------------------------------------------------

_HIER = ("|", "/\\", "[]", "{}", "()", "<>")


def _hier_class(ch: str) -> int:
    for i, s in enumerate(_HIER):
        if ch in s:
            return i
    return -1


class _LineBuilder:
    __slots__ = ("font", "mode", "rtl", "rows", "prev_w", "cur_w", "spacing")

    def __init__(self, font: FigFont, mode: int, rtl: bool, spacing: int):
        self.font = font
        self.mode = mode
        self.rtl = rtl
        self.rows = [""] * font.height
        self.prev_w = 0
        self.cur_w = 0
        self.spacing = spacing

    def smush_chars(self, left: str, right: str) -> str | None:
        if left == " ":
            return right
        if right == " ":
            return left
        if self.prev_w < 2 or self.cur_w < 2:
            return None
        mode = self.mode
        if not mode & SM_SMUSH:
            return None
        hb = self.font.hardblank
        if not mode & 63:
            if left == hb:
                return right
            if right == hb:
                return left
            return left if self.rtl else right
        if mode & SM_HARDBLANK and left == hb and right == hb:
            return left
        if left == hb or right == hb:
            return None
        if mode & SM_EQUAL and left == right:
            return left
        if mode & SM_LOWLINE:
            if left == "_" and right in "|/\\[]{}()<>":
                return right
            if right == "_" and left in "|/\\[]{}()<>":
                return left
        if mode & SM_HIERARCHY:
            cl, cr = _hier_class(left), _hier_class(right)
            if cl >= 0 and cr >= 0 and cl != cr:
                return right if cr > cl else left
        if mode & SM_PAIR:
            if left + right in ("[]", "][", "{}", "}{", "()", ")("):
                return "|"
        if mode & SM_BIGX:
            if left == "/" and right == "\\":
                return "|"
            if left == "\\" and right == "/":
                return "Y"
            if left == ">" and right == "<":
                return "X"
        return None

    def smush_amount(self, glyph: list[str]) -> int:
        if not self.mode & (SM_SMUSH | SM_KERN):
            return 0
        max_smush = self.cur_w
        for row in range(self.font.height):
            line_l, line_r = self.rows[row], glyph[row]
            if self.rtl:
                line_l, line_r = line_r, line_l
            linebd = len(line_l.rstrip(" ")) - 1
            if linebd < 0:
                linebd = 0
            if linebd < len(line_l):
                ch1 = line_l[linebd]
            else:
                linebd, ch1 = 0, ""
            charbd = len(line_r) - len(line_r.lstrip(" "))
            if charbd < len(line_r):
                ch2 = line_r[charbd]
            else:
                charbd, ch2 = len(line_r), ""
            amt = charbd + len(line_l) - 1 - linebd
            if ch1 == "" or ch1 == " ":
                amt += 1
            elif ch2 != "" and self.smush_chars(ch1, ch2) is not None:
                amt += 1
            if amt < max_smush:
                max_smush = amt
        return max_smush

    def add(self, glyph: list[str]) -> None:
        self.prev_w = self.cur_w
        self.cur_w = len(glyph[0]) if glyph else 0
        amount = self.smush_amount(glyph)
        empty = not self.rows[0] and all(not r for r in self.rows)
        if self.spacing and not empty:
            amount -= self.spacing
        if amount < 0:
            pad = " " * (-amount)
            glyph = [pad + r for r in glyph] if not self.rtl else [r + pad for r in glyph]
            amount = 0
        for row in range(self.font.height):
            left, right = self.rows[row], glyph[row]
            if self.rtl:
                left, right = right, left
            if amount:
                buf = list(left)
                ll = len(left)
                for i in range(amount):
                    idx = ll - amount + i
                    rc = right[i] if i < len(right) else ""
                    if 0 <= idx < ll:
                        sm = self.smush_chars(buf[idx], rc)
                        buf[idx] = sm if sm is not None else rc
                left = "".join(buf)
            self.rows[row] = left + right[amount:]


def resolve_h_mode(font: FigFont, layout: str) -> int:
    base = font.h_mode
    if layout in ("default", "", None):
        return base
    if layout == "full":
        return 0
    if layout == "fitted":
        return SM_KERN
    if layout == "smush":  # controlled smushing: font rules, forced on
        return (base & 63) | SM_SMUSH
    if layout == "universal":
        return SM_SMUSH
    raise ValueError(f"unknown horizontal layout {layout!r}")


def resolve_v_mode(font: FigFont, layout: str) -> int:
    base = font.v_mode
    if layout in ("default", "", None):
        return base
    if layout == "full":
        return 0
    if layout == "fitted":
        return VSM_KERN
    if layout == "smush":
        return (base & (VSM_EQUAL | VSM_LOWLINE | VSM_HIERARCHY | VSM_HLINE | VSM_VLINE)) | VSM_SMUSH
    if layout == "universal":
        return VSM_SMUSH
    raise ValueError(f"unknown vertical layout {layout!r}")


def _glyph_for(font: FigFont, cluster: str, fallback: bool, missing: str) -> list[str] | None:
    if cluster == "\t":
        cluster = " "
    if fallback:
        cp = fallback_codepoint(font.has, cluster)
    else:
        cp = ord(cluster[0]) if len(cluster) >= 1 and font.has(ord(cluster[0])) else None
    if cp is not None:
        return font.glyphs[cp]
    if char_width(cluster) == 0 and cluster not in (" ",):
        return None
    if missing == "skip":
        return None
    if missing == "zero" and 0 in font.glyphs:
        return font.glyphs[0]
    if missing == "question" and 63 in font.glyphs:
        return font.glyphs[63]
    if 0 in font.glyphs:
        return font.glyphs[0]
    return None


def render_line_rows(font: FigFont, clusters: list[str], h_mode: int, rtl: bool,
                     spacing: int = 0, fallback: bool = True, missing: str = "skip") -> list[str]:
    b = _LineBuilder(font, h_mode, rtl, spacing)
    for cl in clusters:
        g = _glyph_for(font, cl, fallback, missing)
        if g is None:
            continue
        b.add(g)
    return b.rows


# ---------------------------------------------------------------------------
# Vertical layout
# ---------------------------------------------------------------------------

def _v_smush_char(top: str, bot: str, mode: int, hb: str) -> str | None:
    if top == " ":
        return bot
    if bot == " ":
        return top
    if not mode & 0x7F00 & ~VSM_KERN:
        return None
    rules = mode & (VSM_EQUAL | VSM_LOWLINE | VSM_HIERARCHY | VSM_HLINE | VSM_VLINE)
    if mode & VSM_SMUSH and not rules:
        if top == hb:
            return bot
        if bot == hb:
            return top
        return bot
    if mode & VSM_EQUAL and top == bot:
        return top
    if mode & VSM_LOWLINE:
        if top == "_" and bot in "|/\\[]{}()<>":
            return bot
        if bot == "_" and top in "|/\\[]{}()<>":
            return top
    if mode & VSM_HIERARCHY:
        ct, cb = _hier_class(top), _hier_class(bot)
        if ct >= 0 and cb >= 0 and ct != cb:
            return bot if cb > ct else top
    if mode & VSM_HLINE:
        if (top == "-" and bot == "_") or (top == "_" and bot == "-"):
            return "="
    if mode & VSM_VLINE and top == "|" and bot == "|":
        return "|"
    return None


def _v_overlap(upper: list[str], lower: list[str], mode: int, hb: str) -> int:
    """Largest number of rows block ``lower`` may overlap block ``upper``."""
    if not mode & (VSM_KERN | VSM_SMUSH) or not upper or not lower:
        return 0
    smush = bool(mode & VSM_SMUSH)
    best = 0
    for d in range(1, min(len(upper), len(lower)) + 1):
        collided = False
        ok = True
        for i in range(d):
            a = upper[len(upper) - d + i]
            b = lower[i]
            for x in range(min(len(a), len(b))):
                ca, cb = a[x], b[x]
                if ca == " " or cb == " ":
                    continue
                if not smush:
                    ok = False
                    break
                if _v_smush_char(ca, cb, mode, hb) is None:
                    ok = False
                    break
                if not (mode & VSM_VLINE and ca == "|" and cb == "|"):
                    collided = True
            if not ok:
                break
        if not ok:
            break
        best = d
        if collided:
            break
    return best


def _v_merge(upper: list[str], lower: list[str], d: int, mode: int, hb: str) -> list[str]:
    if d <= 0:
        return upper + lower
    head = upper[:len(upper) - d]
    mid = []
    for i in range(d):
        a = upper[len(upper) - d + i]
        b = lower[i]
        w = max(len(a), len(b))
        a, b = a.ljust(w), b.ljust(w)
        row = []
        for x in range(w):
            sm = _v_smush_char(a[x], b[x], mode, hb)
            row.append(sm if sm is not None else b[x])
        mid.append("".join(row))
    return head + mid + lower[d:]


# ---------------------------------------------------------------------------
# Public rendering API
# ---------------------------------------------------------------------------

@dataclass
class RenderOptions:
    h_layout: str = "default"   # default | full | fitted | smush | universal
    v_layout: str = "default"
    width: int = 0              # wrap width in columns, 0 = no wrapping
    align: str = "left"         # left | center | right
    direction: str = "auto"     # auto | ltr | rtl
    letter_spacing: int = 0
    line_spacing: int = 0
    fallback: bool = True
    missing: str = "skip"       # skip | question | zero
    max_input: int = 5000


def _wrap_line(font: FigFont, clusters: list[str], opts: RenderOptions, h_mode: int, rtl: bool) -> list[list[str]]:
    """Greedy word wrap driven by real rendered widths."""
    width = opts.width
    if width <= 0:
        return [clusters]

    def w_of(cl: list[str]) -> int:
        rows = render_line_rows(font, cl, h_mode, rtl, opts.letter_spacing, opts.fallback, opts.missing)
        return max((len(r.rstrip()) for r in rows), default=0)

    words: list[list[str]] = []
    cur: list[str] = []
    for c in clusters:
        if c == " ":
            if cur:
                words.append(cur)
            cur = []
        else:
            cur.append(c)
    if cur:
        words.append(cur)
    out: list[list[str]] = []
    line: list[str] = []
    for word in words:
        cand = line + [" "] + word if line else word
        if w_of(cand) <= width:
            line = cand
            continue
        if line:
            out.append(line)
            line = []
        if w_of(word) <= width:
            line = word
            continue
        piece: list[str] = []
        for c in word:
            if piece and w_of(piece + [c]) > width:
                out.append(piece)
                piece = []
            piece.append(c)
        line = piece
    if line or not out:
        out.append(line)
    return out


def render_figlet_rows(font: FigFont, text: str, opts: RenderOptions | None = None) -> list[str]:
    """Render ``text`` and return output rows with hardblanks converted to spaces."""
    opts = opts or RenderOptions()
    if len(text) > opts.max_input:
        text = text[:opts.max_input]
    h_mode = resolve_h_mode(font, opts.h_layout)
    v_mode = resolve_v_mode(font, opts.v_layout)
    rtl = font.print_direction == 1 if opts.direction == "auto" else opts.direction == "rtl"
    hb = font.hardblank
    blocks: list[list[str]] = []
    for raw_line in text.replace("\r\n", "\n").split("\n"):
        clusters = graphemes(raw_line)
        for piece in _wrap_line(font, clusters, opts, h_mode, rtl):
            rows = render_line_rows(font, piece, h_mode, rtl, opts.letter_spacing,
                                    opts.fallback, opts.missing)
            w = max((len(r) for r in rows), default=0)
            blocks.append([r.ljust(w) for r in rows])
    out: list[str] = []
    for i, blk in enumerate(blocks):
        if i == 0:
            out = list(blk)
            continue
        if opts.line_spacing > 0:
            out = out + [""] * opts.line_spacing + blk
        else:
            d = _v_overlap(out, blk, v_mode, hb)
            out = _v_merge(out, blk, d, v_mode, hb)
    out = [r.replace(hb, " ") if hb != " " else r for r in out]
    out = [r.rstrip() for r in out]
    width = max((len(r) for r in out), default=0)
    if opts.align in ("center", "right"):
        target = max(width, opts.width) if opts.width else width
        if opts.align == "center":
            out = [(" " * ((target - len(r)) // 2) + r) for r in out]
        else:
            out = [r.rjust(target) for r in out]
    return out


def render_figlet(font: FigFont, text: str, opts: RenderOptions | None = None) -> str:
    return "\n".join(render_figlet_rows(font, text, opts))


def glyph_hash_key(font: FigFont, ascii_only: bool = False) -> str:
    """Normalized content key used for duplicate detection."""
    import hashlib
    h = hashlib.sha256()
    h.update(str(font.height).encode())
    for cp in sorted(font.glyphs):
        if ascii_only and not 32 <= cp <= 126:
            continue
        rows = [r.replace(font.hardblank, "\x00").rstrip() for r in font.glyphs[cp]]
        h.update(f"{cp}:".encode() + "\x01".join(rows).encode("utf-8", "surrogatepass") + b"\x02")
    return h.hexdigest()
