"""Independent Arabic text engine: contextual shaping, ligatures and bidi.

Two output families are offered and clearly distinguished in the UI:

* **Semantic (logical) text** – the original Unicode string. Correct for
  copy/paste, search and any shaping-capable renderer (browsers, Word, …).
* **Visual text** – presentation-form glyphs (U+FB50–U+FEFF) in visual
  left-to-right order. Looks right in terminals and editors that do not
  shape or reorder Arabic, but loses semantics (search, screen readers).
* **Raster art** – the visual text drawn with bitmap glyphs rasterized from
  OFL Arabic typefaces; preserves visual appearance only.

The bidirectional algorithm implements the Unicode Bidirectional Algorithm
(UAX #9) rules W1–W7, N1–N2, I1–I2, L1, L2 and bracket mirroring (L4) for
paragraphs without explicit embedding controls. Explicit embeddings/isolates
(LRE, RLE, LRI, …) are treated as boundary-neutral; LRM/RLM act as strong
types. The JavaScript port (web/src/engine/arabic.js) is verified against the
same fixtures.
"""
from __future__ import annotations

import json

from .resources import load_resource
from .figlet import graphemes

_TABLES: dict | None = None


def tables() -> dict:
    global _TABLES
    if _TABLES is None:
        _TABLES = json.loads(load_resource("arabic_tables.json").decode("utf-8"))
    return _TABLES


def build_tables() -> dict:
    """Generate shaping tables from the Unicode database (build-time helper)."""
    import unicodedata
    forms: dict[str, list[str]] = {}
    lig: dict[str, list[str]] = {}
    idx = {"<isolated>": 0, "<final>": 1, "<initial>": 2, "<medial>": 3}
    excluded = {0xFBE8, 0xFBE9}  # Uighur alef maksura initial/medial (not Arabic)
    for block in ((0xFE70, 0xFEFF), (0xFB50, 0xFDFF)):
        for cp in range(*block):
            if cp in excluded:
                continue
            d = unicodedata.decomposition(chr(cp))
            if not d.startswith("<"):
                continue
            tag, *codes = d.split()
            if tag not in idx:
                continue
            chars = "".join(chr(int(c, 16)) for c in codes)
            if len(chars) == 1:
                base = chars
                if block[0] == 0xFB50 and base in forms and any(forms[base]) and base < "٠":
                    continue  # prefer the core FE70 block for core Arabic letters
                forms.setdefault(base, ["", "", "", ""])
                if not forms[base][idx[tag]]:
                    forms[base][idx[tag]] = chr(cp)
            elif len(chars) == 2 and chars[0] == "ل" and chars[1] in "آأإا" and block[0] == 0xFE70:
                lig.setdefault(chars[1], ["", ""])
                if tag == "<isolated>":
                    lig[chars[1]][0] = chr(cp)
                elif tag == "<final>":
                    lig[chars[1]][1] = chr(cp)
    jt: dict[str, str] = {}
    for base, f in forms.items():
        if f[2] or f[3]:
            jt[base] = "D"
        elif f[1]:
            jt[base] = "R"
    jt["ـ"] = "C"
    jt["‍"] = "C"
    return {"forms": forms, "lig": lig, "jt": jt}


# ---------------------------------------------------------------------------
# Shaping
# ---------------------------------------------------------------------------

def _is_transparent(ch: str) -> bool:
    o = ord(ch)
    return (0x0610 <= o <= 0x061A or 0x064B <= o <= 0x065F or o == 0x0670
            or 0x06D6 <= o <= 0x06DC or 0x06DF <= o <= 0x06E4 or 0x06E7 <= o <= 0x06E8
            or 0x06EA <= o <= 0x06ED or 0x08D3 <= o <= 0x08FF or 0x0300 <= o <= 0x036F)


def is_arabic_char(ch: str) -> bool:
    o = ord(ch)
    return (0x0600 <= o <= 0x06FF or 0x0750 <= o <= 0x077F or 0x08A0 <= o <= 0x08FF
            or 0xFB50 <= o <= 0xFDFF or 0xFE70 <= o <= 0xFEFF)


def contains_arabic(text: str) -> bool:
    return any(is_arabic_char(c) for c in text)


DIGITS = {
    "western": "0123456789",
    "arabic": "٠١٢٣٤٥٦٧٨٩",
    "persian": "۰۱۲۳۴۵۶۷۸۹",
}


def convert_digits(text: str, style: str) -> str:
    if style not in DIGITS or style == "keep":
        return text
    target = DIGITS[style]
    out = []
    for c in text:
        for src in DIGITS.values():
            i = src.find(c)
            if i >= 0:
                c = target[i]
                break
        out.append(c)
    return "".join(out)


def shape(text: str, ligatures: bool = True) -> str:
    """Return ``text`` with Arabic letters replaced by contextual presentation forms.

    Order stays logical; combine with :func:`visual_order` for display.
    """
    t = tables()
    forms, jt, lig = t["forms"], t["jt"], t["lig"]
    chars = list(text)
    n = len(chars)
    types = []
    for c in chars:
        if _is_transparent(c):
            types.append("T")
        else:
            types.append(jt.get(c, "U"))

    def prev_type(i: int) -> str:
        j = i - 1
        while j >= 0 and types[j] == "T":
            j -= 1
        return types[j] if j >= 0 else "U"

    def next_index(i: int) -> int:
        j = i + 1
        while j < n and types[j] == "T":
            j += 1
        return j

    out: list[str] = []
    i = 0
    while i < n:
        c = chars[i]
        ty = types[i]
        if ty in ("T", "U") or c not in forms:
            out.append(c)
            i += 1
            continue
        pt = prev_type(i)
        joins_prev = pt in ("D", "C") and ty in ("D", "R", "C")
        j = next_index(i)
        # lam-alef ligature
        if ligatures and c == "ل" and j < n and chars[j] in lig:
            iso, fin = lig[chars[j]]
            glyph = fin if joins_prev else iso
            if glyph:
                out.append(glyph)
                out.extend(chars[i + 1:j])  # marks attached to lam
                i = j + 1
                continue
        nt = types[j] if j < n else "U"
        joins_next = ty in ("D", "C") and nt in ("D", "R", "C")
        f = forms[c]
        if joins_prev and joins_next:
            g = f[3] or f[1] or f[0]
        elif joins_prev:
            g = f[1] or f[0]
        elif joins_next:
            g = f[2] or f[0]
        else:
            g = f[0]
        out.append(g or c)
        i += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# Bidirectional algorithm (UAX #9 subset)
# ---------------------------------------------------------------------------

_MIRROR = {"(": ")", ")": "(", "[": "]", "]": "[", "{": "}", "}": "{", "<": ">", ">": "<",
           "«": "»", "»": "«", "‹": "›", "›": "‹", "⁅": "⁆", "⁆": "⁅", "﴾": "﴿", "﴿": "﴾"}

_ET = set("#$%°¢£¤¥‰‱′″‴₠₡₢₣₤₥₦₧₨₩₪₫€₭₮₯₰₱₲₳₴₵₸₹₺₼₽+-")
_ES = set("+-")
_CS = set(",.:/ ، ")


def bidi_class(ch: str) -> str:
    """Bidi class of a character (simplified, range based, shared with JS)."""
    o = ord(ch)
    if ch == "\n" or ch == " ":
        return "B"
    if ch in "\t\x0b\x1f":
        return "S"
    if ch in "            　\x0c":
        return "WS"
    if o in (0x200E,):
        return "L"
    if o in (0x200F,):
        return "R"
    if o == 0x061C:
        return "AL"
    if 0x200B <= o <= 0x200D or o == 0xFEFF or 0x202A <= o <= 0x202E or 0x2066 <= o <= 0x2069 or o < 0x20 or 0x7F <= o < 0xA0:
        return "BN"
    if 0x30 <= o <= 0x39 or o in (0xB2, 0xB3, 0xB9) or 0x6F0 <= o <= 0x6F9 or 0xFF10 <= o <= 0xFF19 or 0x2070 <= o <= 0x2079 or 0x2080 <= o <= 0x2089:
        return "EN"
    if 0x660 <= o <= 0x669 or o in (0x66B, 0x66C) or 0x600 <= o <= 0x605 or o == 0x6DD:
        return "AN"
    if ch in _ES:
        return "ES"
    if ch in _ET or o == 0x66A:
        return "ET"
    if ch in _CS:
        return "CS"
    if _is_transparent(ch) or 0x0300 <= o <= 0x036F or 0x0591 <= o <= 0x05BD or o in (0x05BF, 0x05C1, 0x05C2, 0x05C4, 0x05C5, 0x05C7) or 0x20D0 <= o <= 0x20FF or 0xFE20 <= o <= 0xFE2F:
        return "NSM"
    if 0x0590 <= o <= 0x05FF or 0x07C0 <= o <= 0x085F or 0xFB1D <= o <= 0xFB4F or 0x10800 <= o <= 0x10FFF or 0x1E800 <= o <= 0x1EFFF:
        return "R"
    if 0x0600 <= o <= 0x07BF or 0x0860 <= o <= 0x08FF or 0xFB50 <= o <= 0xFDFF or 0xFE70 <= o <= 0xFEFF:
        return "AL"
    if o < 0x80:
        if ch.isalpha():
            return "L"
        return "ON"
    if 0x2000 <= o <= 0x2BFF or 0x3001 <= o <= 0x3003 or 0xFE50 <= o <= 0xFE6F or 0xA1 <= o <= 0xBF or o in (0xD7, 0xF7):
        return "ON"
    return "L"


def _strong(t: str) -> str:
    return "R" if t in ("R", "AL", "EN", "AN") else t


def resolve_levels(types: list[str], base: int) -> list[int]:
    n = len(types)
    t = list(types)
    sos = "R" if base % 2 else "L"
    # W1
    prev = sos
    for i in range(n):
        if t[i] == "NSM":
            t[i] = prev
        elif t[i] != "BN":
            prev = t[i]
    # W2
    last = sos
    for i in range(n):
        if t[i] in ("L", "R", "AL"):
            last = t[i]
        elif t[i] == "EN" and last == "AL":
            t[i] = "AN"
    # W3
    t = ["R" if x == "AL" else x for x in t]
    # W4
    for i in range(1, n - 1):
        if t[i] == "ES" and t[i - 1] == "EN" and t[i + 1] == "EN":
            t[i] = "EN"
        elif t[i] == "CS" and t[i - 1] == t[i + 1] and t[i - 1] in ("EN", "AN"):
            t[i] = t[i - 1]
    # W5
    i = 0
    while i < n:
        if t[i] == "ET":
            j = i
            while j < n and t[j] == "ET":
                j += 1
            if (i > 0 and t[i - 1] == "EN") or (j < n and t[j] == "EN"):
                for k in range(i, j):
                    t[k] = "EN"
            i = j
        else:
            i += 1
    # W6
    t = ["ON" if x in ("ES", "ET", "CS") else x for x in t]
    # W7
    last = sos
    for i in range(n):
        if t[i] in ("L", "R"):
            last = t[i]
        elif t[i] == "EN" and last == "L":
            t[i] = "L"
    # N1/N2
    eor = sos
    i = 0
    neutral = ("B", "S", "WS", "ON", "BN")
    while i < n:
        if t[i] in neutral:
            j = i
            while j < n and t[j] in neutral:
                j += 1
            before = _strong(t[i - 1]) if i > 0 else sos
            after = _strong(t[j]) if j < n else eor
            d = before if before == after else ("R" if base % 2 else "L")
            for k in range(i, j):
                t[k] = d
            i = j
        else:
            i += 1
    # I1/I2
    levels = []
    for x in t:
        if base % 2 == 0:
            levels.append(base + (1 if x == "R" else 2 if x in ("AN", "EN") else 0))
        else:
            levels.append(base + (1 if x in ("L", "EN", "AN") else 0))
    # L1: trailing whitespace and separators -> base level
    for i in range(n - 1, -1, -1):
        if types[i] in ("WS", "S", "B", "BN"):
            levels[i] = base
        else:
            break
    for i in range(n):
        if types[i] in ("S", "B"):
            levels[i] = base
            j = i - 1
            while j >= 0 and types[j] in ("WS", "BN"):
                levels[j] = base
                j -= 1
    return levels


def paragraph_level(text: str, direction: str = "auto") -> int:
    if direction == "rtl":
        return 1
    if direction == "ltr":
        return 0
    for c in text:
        bc = bidi_class(c)
        if bc == "L":
            return 0
        if bc in ("R", "AL"):
            return 1
    return 0


def visual_clusters(line: str, direction: str = "auto") -> list[str]:
    """Reorder a single line (logical order) into visual grapheme clusters."""
    clusters = graphemes(line)
    if not clusters:
        return []
    base = paragraph_level(line, direction)
    types = [bidi_class(c[0]) for c in clusters]
    if base == 0 and not any(x in ("R", "AL", "AN") for x in types):
        return clusters
    levels = resolve_levels(types, base)
    idx = list(range(len(clusters)))
    top = max(levels)
    low_odd = min((lv for lv in levels if lv % 2), default=top + 1)
    for lv in range(top, low_odd - 1, -1):
        i = 0
        while i < len(idx):
            if levels[idx[i]] >= lv:
                j = i
                while j < len(idx) and levels[idx[j]] >= lv:
                    j += 1
                idx[i:j] = idx[i:j][::-1]
                i = j
            else:
                i += 1
    out = []
    for k in idx:
        c = clusters[k]
        if levels[k] % 2 and c[0] in _MIRROR:
            c = _MIRROR[c[0]] + c[1:]
        out.append(c)
    return out


def visual_text(text: str, direction: str = "auto", shape_text: bool = True,
                ligatures: bool = True, digits: str = "keep") -> str:
    """Shaped presentation forms in visual order (for non-shaping displays)."""
    text = convert_digits(text, digits)
    lines = []
    for line in text.split("\n"):
        s = shape(line, ligatures) if shape_text else line
        lines.append("".join(visual_clusters(s, direction)))
    return "\n".join(lines)


def strip_diacritics(text: str) -> str:
    return "".join(c for c in text if not _is_transparent(c))
