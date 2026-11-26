"""Character palettes, measured glyph density and glyph shape matching for the Image Studio.

Glyph coverage masks (8×16, 0–255) are measured from DejaVu Sans Mono at build time
(tools/build_glyphs.py) and shared by both editions. Feature vectors are kept as exact integers
so density ordering, candidate selection and matching distances are bit-identical in Python and JS.
"""
from __future__ import annotations

import base64
import json
import re

from .imgcore import np, require_numpy
from .resources import load_resource

MASK_W, MASK_H = 8, 16
CELL_QUANT = 64  # cell features are quantised to 1/64 before matching (exact integer arithmetic, cacheable)

_GLYPH_ATLAS: dict | None = None
_GLYPH_RUNTIME_MASKS: dict = {}


def glyph_atlas() -> dict:
    """char → uint8 bytes (128) for every measured glyph."""
    global _GLYPH_ATLAS
    if _GLYPH_ATLAS is None:
        d = json.loads(load_resource("glyph_masks.json").decode("utf-8"))
        raw = base64.b64decode(d["masks"])
        n = d["w"] * d["h"]
        _GLYPH_ATLAS = {ch: raw[i * n:(i + 1) * n] for i, ch in enumerate(d["chars"])}
    return _GLYPH_ATLAS


def _runtime_mask(ch: str):
    """Rasterize a glyph that is not in the atlas (Pillow + DejaVu Sans Mono), or None."""
    if ch in _GLYPH_RUNTIME_MASKS:
        return _GLYPH_RUNTIME_MASKS[ch]
    m = None
    try:
        from PIL import Image, ImageDraw, ImageFont
        import io
        import zlib
        font = ImageFont.truetype(io.BytesIO(zlib.decompress(load_resource("DejaVuSansMono.ttf.z"))), 53)
        a, d = font.getmetrics()
        im = Image.new("L", (32, 64), 0)
        ImageDraw.Draw(im).text((0, round((64 - (a + d)) / 2 + a)), ch, font=font, fill=255, anchor="ls")
        m = im.reduce(4).tobytes()
        if not any(m) and ch.strip():
            m = None
    except Exception:
        m = None
    _GLYPH_RUNTIME_MASKS[ch] = m
    return m


def glyph_mask(ch: str) -> bytes | None:
    if ch in (" ", "", "⠀"):
        return bytes(MASK_W * MASK_H) if ch != "⠀" else glyph_atlas().get(ch, bytes(128))
    return glyph_atlas().get(ch) or _runtime_mask(ch)


def glyph_coverage_sum(ch: str) -> int:
    """Total coverage (sum of the 128 mask bytes). Unknown glyphs get 20 % coverage."""
    m = glyph_mask(ch)
    if m is None:
        return int(0.2 * 255 * MASK_W * MASK_H)
    return sum(m)


def graphemes_simple(s: str) -> list[str]:
    from .figlet import graphemes
    return [g for g in graphemes(s) if g and g not in ("\n", "\r", "\t")]


def sort_by_density(chars, reverse: bool = False) -> list[str]:
    """Sort glyphs from lightest to densest by *measured* coverage (ties by code point)."""
    uniq = list(dict.fromkeys(chars))
    out = sorted(uniq, key=lambda c: (glyph_coverage_sum(c), [ord(x) for x in c]))
    return out[::-1] if reverse else out


# ---------------------------------------------------------------------- palette library
PALETTES: dict[str, dict] = {
    "ascii_basic": {"label": "Basic ASCII", "chars": " .:-=+*#%@", "kind": "ramp"},
    "ascii_basic_rev": {"label": "Basic ASCII (reversed)", "chars": "@%#*+=-:. ", "kind": "ramp", "keep_order": True},
    "ascii_extended": {"label": "Extended ASCII", "kind": "set",
                       "chars": " .'`^\",:;Il!i><~+_-?][}{1)(|\\/tfjrxnuvczXYUJCLQ0OZmwqpdbkhao*#MW&8%B@$"},
    "ascii_high": {"label": "High-density ASCII", "kind": "set",
                   "chars": " .`'-,:;!|/\\()[]{}<>?+=*%#&$@0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"},
    "ascii_low": {"label": "Low-density ASCII", "chars": " .,'`:-;~\"^", "kind": "ramp"},
    "cp437": {"label": "Extended (CP437/Latin-1)", "kind": "set",
              "chars": " .·∙:-=+±÷≈≡░▒▓█▀▄▌▐■│─┼┤├┬┴┌┐└┘║═╬╔╗╚╝⌐¬ºª°¹²³«»¶§¤¦ßæÆøØ¥£¢©®αΓπΣσµτΦΘΩδ∞φε∩√ⁿ"},
    "blocks": {"label": "Unicode shade blocks", "chars": " ░▒▓█", "kind": "ramp", "keep_order": True},
    "braille": {"label": "Braille patterns", "chars": "".join(chr(0x2800 + i) for i in range(256)), "kind": "set"},
    "geometric": {"label": "Geometric symbols", "chars": " ·∙•◦○◘◙●◌◊◇◆□■▪▫▲△▼▽◀▶◢◣◤◥", "kind": "set"},
    "math": {"label": "Mathematical symbols", "kind": "set",
             "chars": " ·∘∙−+×÷=≠≈∼≤≥±∓∑∏∫∂∇√∞∝∈∉∋⊂⊃⊆⊇∩∪∧∨¬∀∃∅⊕⊗⊥∠∴∵≡≅"},
    "binary": {"label": "Binary digits", "chars": " 01", "kind": "ramp"},
    "alpha": {"label": "Alphabetic", "chars": " ABCDEFGHIJKLMNOPQRSTUVWXYZ", "kind": "ramp"},
    "numeric": {"label": "Numeric", "chars": " 0123456789", "kind": "ramp"},
    "dots": {"label": "Dots (halftone)", "chars": " ·∙•●", "kind": "ramp", "keep_order": True},
    "lines": {"label": "Line glyphs", "chars": " -_|/\\()<>^v.,'`=+", "kind": "set"},
    "symbols": {"label": "Custom Unicode symbols", "chars": " ·✦✧★☆♠♣♥♦♪♫☼", "kind": "ramp"},
    "katakana": {"label": "Half-width katakana", "kind": "set",
                 "chars": "".join(chr(c) for c in range(0xFF66, 0xFF9E))},
    "emoji": {"label": "Emoji (colour squares & hearts)", "chars": "⬛🟫🟥🟧🟨🟩🟦🟪⬜", "kind": "emoji", "keep_order": True},
}

# nominal colours of the emoji palette (rendered colours differ slightly between emoji fonts)
EMOJI_COLORS = [
    ("⬛", 0x1E1E1E), ("⬜", 0xF0F0F0), ("🟥", 0xDD2E44), ("🟧", 0xF4900C), ("🟨", 0xFDCB58), ("🟩", 0x78B159),
    ("🟦", 0x55ACEE), ("🟪", 0xAA8ED6), ("🟫", 0xC1694F), ("❤️", 0xDD2E44), ("🧡", 0xF4900C), ("💛", 0xFDCB58),
    ("💚", 0x78B159), ("💙", 0x5DADEC), ("💜", 0xAA8ED6), ("🤎", 0xA0522D), ("🖤", 0x31373D), ("🤍", 0xFFFFFF),
    ("🌑", 0x3D3D3D), ("🌕", 0xFFD983), ("🔴", 0xDD2E44), ("🟠", 0xF4900C), ("🟡", 0xFDCB58), ("🟢", 0x78B159),
    ("🔵", 0x55ACEE), ("🟣", 0xAA8ED6), ("🟤", 0xC1694F), ("⚫", 0x31373D), ("⚪", 0xE6E7E8),
]

MAX_PALETTE_GLYPHS = 512


def clean_palette(s: str) -> str:
    """Remove control characters; limit length."""
    s = "".join(c for c in str(s) if (ord(c) >= 32 and not 0x7F <= ord(c) < 0xA0))
    g = graphemes_simple(s)
    return "".join(g[:MAX_PALETTE_GLYPHS])


def resolve_palette(spec: str, default: str = "ascii_basic", reverse: bool = False, sort: bool = True) -> list[str]:
    """Palette key or literal characters → list of glyphs ordered light → dense."""
    spec = spec or default
    if spec in PALETTES:
        p = PALETTES[spec]
        chars = graphemes_simple(p["chars"])
        if p.get("kind") == "emoji":
            return chars[::-1] if reverse else chars
        ordered = chars if p.get("keep_order") or not sort else sort_by_density(chars)
    else:
        chars = graphemes_simple(clean_palette(spec))
        if not chars:
            chars = graphemes_simple(PALETTES[default]["chars"])
        ordered = sort_by_density(chars) if sort else list(dict.fromkeys(chars))
    if len(ordered) == 1:
        ordered = [" "] + ordered
    return ordered[::-1] if reverse else ordered


def palette_from_figlet(font) -> str:
    """Characters used to draw a FIGlet font's glyphs, sorted by measured density."""
    seen = set()
    for glyph in getattr(font, "glyphs", {}).values():
        for row in glyph:
            for c in row:
                if c != getattr(font, "hardblank", "$") and ord(c) >= 32:
                    seen.add(c)
    seen.add(" ")
    return "".join(sort_by_density(seen))


def export_palettes(items: list[dict]) -> str:
    return json.dumps({"leerbox_palettes": 1, "palettes": [{"name": str(i["name"])[:80], "chars": clean_palette(i["chars"])}
                                                           for i in items]}, ensure_ascii=False, indent=1)


def import_palettes(text: str) -> list[dict]:
    try:
        d = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"not a palette file: {exc}") from exc
    if not isinstance(d, dict) or not isinstance(d.get("palettes"), list):
        raise ValueError("not a LeerBox palette file")
    out = []
    for p in d["palettes"][:200]:
        if isinstance(p, dict) and isinstance(p.get("chars"), str):
            chars = clean_palette(p["chars"])
            if chars:
                out.append({"name": re.sub(r"[\x00-\x1f]", "", str(p.get("name", "Imported")))[:80] or "Imported",
                            "chars": chars})
    return out


# ---------------------------------------------------------------------- shape matching
class GlyphMatcher:
    """Nearest-glyph search on fw×fh coverage features with density-window candidate selection.

    Glyph features are integer sums of mask bytes over each feature block (×CELL_QUANT); cell features
    are quantised ink values (0..CELL_QUANT) × 255 × block size — all distances are exact integers.
    """

    def __init__(self, chars: list[str], fw: int, fh: int, k: int = 24):
        require_numpy()
        assert MASK_W % fw == 0 and MASK_H % fh == 0
        self.fw, self.fh, self.k = fw, fh, k
        bx, by = MASK_W // fw, MASK_H // fh
        self.block = bx * by
        feats = []
        for ch in chars:
            m = glyph_mask(ch)
            arr = (np.frombuffer(m, dtype=np.uint8).astype(np.int64).reshape(MASK_H, MASK_W) if m is not None
                   else np.full((MASK_H, MASK_W), 51, dtype=np.int64))
            f = arr.reshape(fh, by, fw, bx).sum(axis=(1, 3)).ravel() * CELL_QUANT
            feats.append(f)
        G = np.array(feats, dtype=np.int64)
        dens = G.sum(axis=1)
        order = sorted(range(len(chars)), key=lambda i: (int(dens[i]), [ord(x) for x in chars[i]]))
        self.chars = [chars[i] for i in order]
        self.G = G[order].astype(np.float64)
        self.dens = dens[order].astype(np.float64)
        self.max_mean = float(self.dens.max()) / (G.shape[1] * 255 * self.block * CELL_QUANT) if len(chars) else 1.0
        self.k = max(1, min(k, len(chars)))

    def quantize_cells(self, ink):
        """ink: (n, fh*fw) in 0..1 → integer feature units scaled so a full-ink cell equals the densest glyph."""
        q = np.floor(np.clip(ink, 0, 1) * self.max_mean * CELL_QUANT + 0.5)
        return q * (255 * self.block)

    def match(self, ink, chunk: int = 4096):
        """Return glyph indices (into self.chars) for each row of ink features."""
        C = self.quantize_cells(ink)
        uniq, inv = np.unique(C, axis=0, return_inverse=True)
        inv = inv.ravel()
        res = np.zeros(len(uniq), dtype=np.int64)
        n, K = len(self.chars), self.k
        for s in range(0, len(uniq), chunk):
            U = uniq[s:s + chunk]
            m = U.sum(axis=1)
            idx = np.searchsorted(self.dens, m, side="left")
            start = np.clip(idx - K // 2, 0, n - K)
            cand = start[:, None] + np.arange(K)[None, :]
            d = ((U[:, None, :] - self.G[cand]) ** 2).sum(axis=2)
            res[s:s + chunk] = cand[np.arange(len(U)), np.argmin(d, axis=1)]
        return res[inv]


def masks_float(chars: list[str], fw: int, fh: int):
    """(n, fh*fw) mean coverage 0..1 per feature block (for reconstruction and two-colour fitting)."""
    require_numpy()
    bx, by = MASK_W // fw, MASK_H // fh
    out = []
    for ch in chars:
        m = glyph_mask(ch)
        arr = (np.frombuffer(m, dtype=np.uint8).astype(np.float64).reshape(MASK_H, MASK_W) / 255 if m is not None
               else np.full((MASK_H, MASK_W), 0.2))
        out.append(arr.reshape(fh, by, fw, bx).mean(axis=(1, 3)).ravel())
    return np.array(out)


def sextant_char(bits: int) -> str:
    """6-bit sextant pattern (bit0 top-left … bit5 bottom-right) → character."""
    if bits == 0:
        return " "
    if bits == 63:
        return "█"
    if bits == 21:
        return "▌"
    if bits == 42:
        return "▐"
    n = bits - 1
    if bits > 21:
        n -= 1
    if bits > 42:
        n -= 1
    return chr(0x1FB00 + n)


QUADRANT_CHARS = " ▘▝▀▖▌▞▛▗▚▐▜▄▙▟█"  # bit0 TL, bit1 TR, bit2 BL, bit3 BR


def braille_char(bits: int) -> str:
    """8-bit dot pattern (ISO 11548-1 numbering: bit0=dot1 … bit7=dot8) → U+2800+bits."""
    return chr(0x2800 + (bits & 0xFF))


BRAILLE_DOTS = [(0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2), (0, 3), (1, 3)]  # (x, y) for bits 0..7
