"""RenderingEngine facade: one call renders text with any font type into an Art grid."""
from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from dataclasses import asdict, dataclass, fields

from .arabic import bidi_class, visual_clusters
from .art import Art
from .effects import apply_effects
from .figlet import FigFont, RenderOptions, render_figlet_rows
from .raster import RasterFont, RasterOptions, render_raster

MAX_INPUT_CHARS = 5000


@dataclass
class TextOptions:
    # FIGlet layout
    h_layout: str = "default"
    v_layout: str = "default"
    width: int = 0
    align: str = "left"
    direction: str = "auto"
    letter_spacing: int = 0
    line_spacing: int = 0
    fallback: bool = True
    missing: str = "skip"
    # raster
    raster_mode: str = "block"
    raster_char: str = "@"
    raster_scale: int = 1
    raster_aspect: int = 1
    raster_invert: bool = False
    # Arabic
    arabic_shaping: bool = True
    ligatures: bool = True
    diacritics: bool = True
    digits: str = "keep"

    @classmethod
    def from_dict(cls, d: dict | None) -> "TextOptions":
        o = cls()
        if not isinstance(d, dict):
            return o
        for f in fields(cls):
            if f.name in d:
                v = d[f.name]
                t = type(getattr(o, f.name))
                try:
                    if t is bool:
                        v = bool(v)
                    elif t is int:
                        v = max(-50, min(10000, int(v)))
                    else:
                        v = str(v)[:64]
                except (TypeError, ValueError):
                    continue
                setattr(o, f.name, v)
        return o

    def to_dict(self) -> dict:
        return asdict(self)


def _has_rtl(text: str) -> bool:
    return any(bidi_class(c) in ("R", "AL") for c in text)


def render_font(font: FigFont | RasterFont, text: str, o: TextOptions) -> Art:
    text = text[:MAX_INPUT_CHARS]
    if isinstance(font, RasterFont):
        ro = RasterOptions(mode=o.raster_mode, char=o.raster_char, scale=o.raster_scale,
                           aspect=o.raster_aspect, letter_spacing=max(0, o.letter_spacing),
                           line_spacing=2 + max(0, o.line_spacing),
                           align="auto" if o.align == "left" and _has_rtl(text) else o.align,
                           direction=o.direction, arabic_shaping=o.arabic_shaping, ligatures=o.ligatures,
                           diacritics=o.diacritics, digits=o.digits, invert=o.raster_invert)
        return render_raster(font, text, ro)
    if _has_rtl(text) and o.direction != "ltr":
        text = "\n".join("".join(visual_clusters(ln, o.direction)) for ln in text.split("\n"))
    ro = RenderOptions(h_layout=o.h_layout, v_layout=o.v_layout, width=max(0, o.width), align=o.align,
                       direction="auto" if o.direction == "auto" else o.direction,
                       letter_spacing=max(0, o.letter_spacing), line_spacing=max(0, o.line_spacing),
                       fallback=o.fallback, missing=o.missing)
    rows = render_figlet_rows(font, text, ro)
    return Art.from_text("\n".join(rows))


class RenderCache:
    """Thread-safe LRU cache keyed by (font id, text, options, effects)."""

    def __init__(self, limit: int = 256):
        self.limit = limit
        self.data: OrderedDict[str, Art] = OrderedDict()
        self.lock = threading.Lock()

    @staticmethod
    def key(fid: str, text: str, o: TextOptions, effects: list | None) -> str:
        h = hashlib.sha1()
        h.update(fid.encode()); h.update(b"\0"); h.update(text.encode("utf-8", "surrogatepass"))
        h.update(json.dumps(o.to_dict(), sort_keys=True).encode())
        h.update(json.dumps(effects or [], sort_keys=True).encode())
        return h.hexdigest()

    def get(self, k: str) -> Art | None:
        with self.lock:
            a = self.data.get(k)
            if a is not None:
                self.data.move_to_end(k)
            return a

    def put(self, k: str, a: Art) -> None:
        with self.lock:
            self.data[k] = a
            while len(self.data) > self.limit:
                self.data.popitem(last=False)


class RenderingEngine:
    def __init__(self, fonts):
        self.fonts = fonts
        self.cache = RenderCache()

    def render(self, fid: str, text: str, o: TextOptions | None = None, effects: list | None = None,
               use_cache: bool = True) -> Art:
        o = o or TextOptions()
        k = RenderCache.key(fid, text, o, effects) if use_cache else ""
        if use_cache:
            hit = self.cache.get(k)
            if hit is not None:
                return hit
        art = render_font(self.fonts.font(fid), text, o)
        if effects:
            art = apply_effects(art, effects)
        if use_cache:
            self.cache.put(k, art)
        return art

    def unsupported_chars(self, fid: str, text: str) -> list[str]:
        """Characters the font cannot draw even after Unicode fallbacks."""
        from .figlet import fallback_codepoint, graphemes, char_width
        font = self.fonts.font(fid)
        bad = []
        for cl in graphemes(text):
            if cl in ("\n", " ", "\t") or char_width(cl) == 0:
                continue
            if isinstance(font, RasterFont):
                from .arabic import is_arabic_char
                from .raster import _find_glyph
                if is_arabic_char(cl[0]) and font.script == "arabic":
                    continue
                g = font.glyphs.get(cl[0])
                if g is None and (_find_glyph(font, cl[0]) is None or _find_glyph(font, cl[0]) is font.glyphs.get("?")):
                    bad.append(cl)
            else:
                if fallback_codepoint(font.has, cl) is None:
                    bad.append(cl)
        seen = []
        for b in bad:
            if b not in seen:
                seen.append(b)
        return seen
