"""Image Studio conversion modes: settings, preparation pipeline, colour engine and 30 renderers.

Each mode uses its own algorithm (density mapping with measured glyph coverage, error diffusion,
two-colour block optimisation, template/structure glyph matching, Sobel/Canny/DoG edge analysis,
marching squares, Otsu segmentation, palette-constrained colour selection …). The JS port is
web/src/engine/74_imgmodes.js.
"""
from __future__ import annotations

import math
import time
from bisect import bisect_left

from .art import Art
from .effects import Rng, gradient_color
from .imgcore import (RasterImage, adjust, blur, canny, composite, crop, flip, int_to_rgb01, luminance,
                      median_cut, np, otsu, pad, parse_color_list, require_numpy, resample_area, resample_plane,
                      rgb01_to_int, rgb_to_lab, rotate90, rotate_free, sobel, box_mean, ADJUST_DEFAULTS)
from .imgglyphs import (BRAILLE_DOTS, EMOJI_COLORS, QUADRANT_CHARS, GlyphMatcher, glyph_coverage_sum,
                        graphemes_simple, masks_float, resolve_palette, sextant_char, clean_palette)

# ---------------------------------------------------------------------- parameters
P_CHOICES = {
    "fit": ["stretch", "contain", "cover"],
    "rotate": [0, 90, 180, 270],
    "dither": ["none", "floyd", "atkinson", "bayer"],
    "edge_method": ["sobel", "canny", "dog"],
    "luma": ["rec709", "perceptual", "linear", "average"],
    "color": ["none", "original", "grayscale", "ansi16", "ansi256", "custom", "gradient", "dominant"],
    "color_target": ["fg", "bg", "both"],
    "equalize": ["none", "global", "clahe"],
    "text_mode": ["flow", "words", "fill"],
    "text_dir": ["auto", "ltr", "rtl"],
}
IMG_PARAMS: dict[str, tuple] = {
    "mode": ("str", "classic"),
    "cols": ("int", 100, 8, 1000), "rows": ("int", 0, 0, 1000),
    "cell_aspect": ("float", 0.5, 0.2, 2.0), "lock_aspect": ("bool", True),
    "target_aspect": ("float", 0.0, 0.0, 10.0), "fit": ("choice", "stretch"),
    "crop_x0": ("float", 0.0, 0.0, 1.0), "crop_y0": ("float", 0.0, 0.0, 1.0),
    "crop_x1": ("float", 1.0, 0.0, 1.0), "crop_y1": ("float", 1.0, 0.0, 1.0),
    "rotate": ("choice", 0), "angle": ("float", 0.0, -180.0, 180.0),
    "flip_h": ("bool", False), "flip_v": ("bool", False), "pad": ("float", 0.0, 0.0, 0.5),
    "exposure": ("float", 0.0, -3.0, 3.0), "brightness": ("float", 0.0, -1.0, 1.0),
    "contrast": ("float", 1.0, 0.0, 3.0), "gamma": ("float", 1.0, 0.2, 5.0),
    "saturation": ("float", 1.0, 0.0, 3.0), "vibrance": ("float", 0.0, -1.0, 1.0),
    "hue": ("float", 0.0, -180.0, 180.0), "sharpness": ("float", 0.0, 0.0, 3.0),
    "blur": ("float", 0.0, 0.0, 10.0), "denoise": ("float", 0.0, 0.0, 1.0),
    "black": ("float", 0.0, 0.0, 0.9), "white": ("float", 1.0, 0.1, 1.0),
    "highlights": ("float", 0.0, -1.0, 1.0), "shadows": ("float", 0.0, -1.0, 1.0),
    "posterize": ("int", 0, 0, 32), "grayscale": ("bool", False), "invert": ("bool", False),
    "remove_bg": ("float", 0.0, 0.0, 1.0), "equalize": ("choice", "none"), "local_contrast": ("float", 0.0, 0.0, 2.0),
    "palette": ("str", ""), "palette_reverse": ("bool", False),
    "dither": ("choice", "none"), "dither_strength": ("float", 1.0, 0.0, 1.0),
    "threshold": ("float", 0.5, 0.0, 1.0), "adaptive": ("bool", False),
    "edge_method": ("choice", "sobel"), "edge_strength": ("float", 1.0, 0.0, 3.0),
    "edge_threshold": ("float", 0.25, 0.0, 1.0), "levels": ("int", 6, 2, 16),
    "luma": ("choice", "rec709"), "light_on_dark": ("bool", True),
    "color": ("choice", "none"), "colors": ("str", "#000000,#ff0000,#ffff00,#ffffff"),
    "gradient": ("str", "#0b1e3f,#2a9d8f,#e9c46a,#ffffff"), "dominant_k": ("int", 6, 2, 16),
    "color_target": ("choice", "fg"), "background": ("str", "#000000"), "transparent_bg": ("bool", True),
    "text": ("str", "LeerBox"), "text_mode": ("choice", "flow"), "text_dir": ("choice", "auto"),
    "seed": ("int", 7, 0, 2 ** 31 - 1),
}


def sanitize_params(d: dict | None) -> dict:
    """Validate and clamp every parameter (unknown keys dropped); used for UI input and projects."""
    out = {}
    d = d or {}
    for k, spec in IMG_PARAMS.items():
        t, default = spec[0], spec[1]
        v = d.get(k, default)
        try:
            if t == "int":
                v = int(float(v)); v = max(spec[2], min(spec[3], v))
            elif t == "float":
                v = float(v)
                if not math.isfinite(v):
                    v = default
                v = max(spec[2], min(spec[3], v))
            elif t == "bool":
                v = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes", "on")
            elif t == "choice":
                ch = P_CHOICES[k]
                if isinstance(default, int):
                    v = int(float(v))
                v = v if v in ch else default
            else:
                v = clean_palette(v)[:2000] if k in ("palette", "text") else str(v)[:2000]
        except (TypeError, ValueError):
            v = default
        out[k] = v
    if out["mode"] not in MODES:
        out["mode"] = "classic"
    return out


# ---------------------------------------------------------------------- mode registry
# key: (label, family, sx, sy, unit, compat, description)
MODES: dict[str, tuple] = {
    "classic": ("Classic ASCII", "text", 1, 1, 1, "ascii", "Luminance → measured-density ASCII ramp (optional error diffusion)"),
    "extended": ("Extended ASCII", "text", 2, 2, 1, "cp437", "2×2 structure matching over CP437/Latin-1 glyphs"),
    "blocks": ("Unicode Block", "block", 1, 1, 1, "unicode", "Shade blocks ░▒▓█ with Floyd–Steinberg error diffusion"),
    "half": ("Unicode Half-Block", "block", 1, 2, 1, "unicode", "▀ with independent top/bottom colours (2 pixels per cell)"),
    "quadrant": ("Unicode Quadrant", "block", 2, 2, 1, "unicode", "16 quadrant patterns; optimal two-colour partition per cell"),
    "sextant": ("Unicode Sextant", "block", 2, 3, 1, "sextant", "64 sextant patterns (Unicode 13); optimal two-colour partition"),
    "braille": ("Unicode Braille", "braille", 2, 4, 1, "braille", "2×4 dots per cell; threshold, adaptive or dithered"),
    "ansi16": ("ANSI 16-Color", "color", 1, 2, 1, "unicode", "Half blocks; colours chosen from the 16-colour palette in CIELAB with error diffusion"),
    "ansi256": ("ANSI 256-Color", "color", 1, 2, 1, "unicode", "Half blocks; nearest xterm-256 colours in CIELAB"),
    "truecolor": ("ANSI TrueColor", "color", 1, 2, 1, "unicode", "Half blocks with exact 24-bit colours"),
    "mono": ("Monochrome", "block", 1, 2, 1, "unicode", "1-bit half blocks with error diffusion"),
    "grayscale": ("Grayscale", "color", 1, 2, 1, "unicode", "Half blocks in 26 grey levels with ordered dithering"),
    "binary": ("Binary", "text", 1, 1, 1, "ascii", "0/1 digits from adaptive (local-mean) thresholds"),
    "matrix": ("Matrix", "text", 1, 1, 1, "katakana", "Half-width katakana & digits, green luminance with deterministic rain streaks"),
    "emoji": ("Emoji", "emoji", 1, 1, 2, "emoji", "Nearest emoji by colour (CIELAB ΔE); 2 columns per emoji"),
    "pixel": ("Pixel Text", "color", 1, 1, 2, "unicode", "Square pixels (██) in a median-cut palette"),
    "dotted": ("Dotted", "text", 1, 1, 1, "unicode", "Halftone dots with a 45° clustered screen"),
    "edge": ("Edge Detection", "edge", 1, 1, 1, "ascii", "Sobel/Canny/DoG edges drawn with orientation glyphs - / | \\"),
    "contour": ("Contour", "edge", 1, 1, 1, "unicode", "Iso-luminance contour lines via marching squares (box drawing)"),
    "line": ("Line Art", "edge", 4, 8, 1, "ascii", "Difference-of-Gaussians lines + template matching over line glyphs"),
    "silhouette": ("Silhouette", "block", 2, 2, 1, "unicode", "Foreground segmentation (alpha or Otsu) drawn with quadrants"),
    "typographic": ("Typographic", "text", 4, 8, 1, "ascii", "Glyph shape matching on 4×8 coverage features (structure-aware)"),
    "words": ("Custom Word", "text", 1, 1, 1, "unicode", "Image rebuilt from repeated user text (multilingual, RTL aware)"),
    "math": ("Mathematical Symbol", "text", 4, 8, 1, "unicode", "Shape matching over mathematical operators"),
    "mosaic": ("Mosaic Character", "color", 4, 8, 1, "unicode", "Geometric glyphs with least-squares foreground/background colours"),
    "dense": ("High-Density Terminal", "color", 4, 8, 1, "sextant", "Best of all block elements & sextants with fitted colours"),
    "adaptive": ("Adaptive Character", "text", 4, 8, 1, "ascii", "Flat regions: density ramp; detailed regions: shape matching"),
    "hybrid": ("Hybrid Edge + Luminance", "edge", 1, 1, 1, "ascii", "Density ramp with Sobel edge glyphs overlaid"),
    "negative": ("Negative", "text", 1, 1, 1, "ascii", "Photographic negative in linear light, perceptual density mapping"),
    "multilayer": ("Multi-Layer", "color", 4, 8, 1, "ascii", "Low-pass colour background + detail glyphs + edge layer"),
}
MODE_KEYS = list(MODES)

COMPAT_NOTES = {
    "ascii": "Plain ASCII — works everywhere.",
    "cp437": "Latin-1/CP437 symbols — most terminal fonts.",
    "unicode": "Unicode block elements — all modern terminal fonts.",
    "sextant": "Sextants need a font with Unicode 13 Legacy Computing glyphs (e.g. Cascadia Code, Iosevka); "
               "others show boxes. DejaVu-based graphical exports draw them geometrically.",
    "braille": "Braille patterns — most modern fonts; spacing varies in some proportional fonts.",
    "emoji": "Emoji are double-width and need a colour-emoji font; terminal alignment can vary.",
    "katakana": "Half-width katakana need a CJK-capable font (e.g. MS Gothic, Noto Sans Mono CJK).",
}

DEFAULT_PALETTE = {"classic": "ascii_extended", "extended": "cp437", "blocks": "blocks", "binary": "binary",
                   "dotted": "dots", "typographic": "ascii_high", "math": "math", "adaptive": "ascii_high",
                   "hybrid": "ascii_extended", "negative": "ascii_extended", "multilayer": "ascii_high",
                   "line": "lines", "matrix": "katakana", "emoji": "emoji"}
DEFAULT_DITHER = {"blocks": "floyd", "mono": "floyd", "ansi16": "floyd", "grayscale": "bayer"}

ANSI16_RGB = [0x000000, 0xCD3131, 0x0DBC79, 0xE5E510, 0x2472C8, 0xBC3FBC, 0x11A8CD, 0xE5E5E5,
              0x666666, 0xF14C4C, 0x23D18B, 0xF5F543, 0x3B8EEA, 0xD670D6, 0x29B8DB, 0xFFFFFF]


def xterm256() -> list[int]:
    lv = [0, 95, 135, 175, 215, 255]
    out = list(ANSI16_RGB)
    for r in lv:
        for g in lv:
            for b in lv:
                out.append((r << 16) | (g << 8) | b)
    for i in range(24):
        v = 8 + 10 * i
        out.append((v << 16) | (v << 8) | v)
    return out


GRAY26 = [0x000000] + [((8 + 10 * i) * 0x010101) for i in range(24)] + [0xFFFFFF]
BAYER8 = [[0, 32, 8, 40, 2, 34, 10, 42], [48, 16, 56, 24, 50, 18, 58, 26], [12, 44, 4, 36, 14, 46, 6, 38],
          [60, 28, 52, 20, 62, 30, 54, 22], [3, 35, 11, 43, 1, 33, 9, 41], [51, 19, 59, 27, 49, 17, 57, 25],
          [15, 47, 7, 39, 13, 45, 5, 37], [63, 31, 55, 23, 61, 29, 53, 21]]
MATRIX_GLYPHS = "".join(chr(c) for c in range(0xFF66, 0xFF9E)) + "0123456789"


# ---------------------------------------------------------------------- planning
def plan_grid(src_w: int, src_h: int, p: dict) -> dict:
    """Output geometry: character columns/rows, sample grid and working resolution."""
    m = MODES[p["mode"]]
    sx, sy, unit = m[2], m[3], m[4]
    cols = max(8, int(p["cols"]))
    gcols = max(4, cols // unit)
    pix_aspect = p["cell_aspect"] * unit  # width/height of one logical cell
    src_aspect = src_w / max(1, src_h)
    target = p["target_aspect"] if p["target_aspect"] > 0 else src_aspect
    if p["rows"] > 0 and p["lock_aspect"]:
        rows_fit = p["rows"]
        rows = max(1, int(gcols * pix_aspect / target + 0.5))
        if rows > rows_fit:  # automatic fit inside cols × rows
            rows = rows_fit
            gcols = max(4, int(rows * target / pix_aspect + 0.5))
    elif p["rows"] > 0:
        rows = p["rows"]
    else:
        rows = max(1, int(gcols * pix_aspect / target + 0.5))
    rows = min(rows, 1000)
    sw, sh = gcols * sx, rows * sy
    return {"cols": gcols * unit, "gcols": gcols, "rows": rows, "sx": sx, "sy": sy, "unit": unit,
            "sw": sw, "sh": sh, "target_aspect": target}


# measured cost per sample in µs (Python, tools/benchmark_image.py); the JS edition is ~3-4× faster
MODE_COST_US = {"sextant": 3.3, "quadrant": 1.6, "dense": 1.6, "ansi16": 5.8, "line": 1.0, "mosaic": 0.7, "multilayer": 0.9,
                "silhouette": 0.6, "typographic": 0.45, "math": 0.45, "adaptive": 0.45, "extended": 0.9}


def estimate_cost(src_w: int, src_h: int, p: dict, js: bool = False) -> dict:
    """Memory/time estimate shown before expensive renders (calibrated on benchmarks, ±50 %)."""
    g = plan_grid(src_w, src_h, p)
    cells = g["gcols"] * g["rows"]
    samples = g["sw"] * g["sh"]
    per = MODE_COST_US.get(p["mode"], 0.6)
    if p["dither"] in ("floyd", "atkinson") or p["mode"] in ("blocks", "mono"):
        per += 0.5
    ms = 60 + samples * per / 1000
    if js:
        ms /= 3.5
    ansi_bytes = cells * (40 if p["color"] != "none" or MODES[p["mode"]][1] == "color" else 3)
    mem = samples * 8 * 12 + cells * 120
    return {"cols": g["cols"], "rows": g["rows"], "cells": cells, "samples": samples, "est_ms": round(ms, 1),
            "est_text_bytes": cells * 3 + g["rows"], "est_ansi_bytes": ansi_bytes, "est_memory_bytes": mem,
            "heavy": ms > 2500 or mem > 600 * 1024 * 1024}


def prepare(src: RasterImage, p: dict) -> tuple[RasterImage, dict]:
    """Geometry → working resolution → adjustments. Returns (work image, grid plan).

    The geometry/resampling stage is cached on the source image (it depends only on geometry settings
    and the output grid), so changing adjustments or modes does not re-resample a large source."""
    gkeys = ("crop_x0", "crop_y0", "crop_x1", "crop_y1", "rotate", "flip_h", "flip_v", "angle", "pad", "target_aspect",
             "fit", "cols", "rows", "cell_aspect", "lock_aspect", "mode")
    m = MODES[p["mode"]]
    key = (id(src), src.width, src.height) + tuple(p[k] for k in gkeys[:-1]) + (m[2], m[3], m[4])
    cache = src.info.setdefault("_geom_cache", {})
    hit = cache.get(key)
    if hit is None:
        hit = _prepare_geometry(src, p)
        if len(cache) >= 6:
            cache.pop(next(iter(cache)))
        cache[key] = hit
    img, g = hit
    adj = {k: p[k] for k in ADJUST_DEFAULTS}
    return adjust(img, adj), dict(g)


def _prepare_geometry(src: RasterImage, p: dict):
    img = src
    if (p["crop_x0"], p["crop_y0"], p["crop_x1"], p["crop_y1"]) != (0.0, 0.0, 1.0, 1.0):
        img = crop(img, p["crop_x0"], p["crop_y0"], p["crop_x1"], p["crop_y1"])
    if p["rotate"]:
        img = rotate90(img, p["rotate"])
    if p["flip_h"] or p["flip_v"]:
        img = flip(img, p["flip_h"], p["flip_v"])
    if p["angle"]:
        img = rotate_free(img, p["angle"])
    if p["pad"] > 0:
        k = int(max(img.width, img.height) * p["pad"] + 0.5)
        img = pad(img, k, k, k, k)
    g = plan_grid(img.width, img.height, p)
    if p["target_aspect"] > 0 and p["fit"] != "stretch":
        cur = img.width / img.height
        tgt = p["target_aspect"]
        if p["fit"] == "contain":
            if cur > tgt:
                extra = int(img.width / tgt - img.height + 0.5); img = pad(img, 0, extra // 2, 0, extra - extra // 2)
            else:
                extra = int(img.height * tgt - img.width + 0.5); img = pad(img, extra // 2, 0, extra - extra // 2, 0)
        else:
            if cur > tgt:
                nw = img.height * tgt / img.width; img = crop(img, (1 - nw) / 2, 0, (1 + nw) / 2, 1)
            else:
                nh = img.width / tgt / img.height; img = crop(img, 0, (1 - nh) / 2, 1, (1 + nh) / 2)
    ww = min(img.width, max(g["sw"] * 2, 16))
    wh = max(1, int(img.height * ww / img.width + 0.5))
    if (ww, wh) != (img.width, img.height):
        img = resample_area(img, ww, wh)
    img = RasterImage(img.rgb, img.a, {k: v for k, v in img.info.items() if k != "_geom_cache"})
    return img, g


# ---------------------------------------------------------------------- context
class Ctx:
    """Per-render helpers shared by the mode functions."""

    def __init__(self, work: RasterImage, g: dict, p: dict):
        self.work, self.g, self.p = work, g, p
        self.bg = parse_color_list(p["background"])[0] if parse_color_list(p["background"]) else 0
        self._cache = {}
        self.rng_seed = p["seed"]

    def flat(self):
        if "flat" not in self._cache:
            self._cache["flat"] = composite(self.work, self.bg)
        return self._cache["flat"]

    def grid(self, sx: int | None = None, sy: int | None = None):
        """(rgb, alpha) sampled to gcols*sx × rows*sy by area averaging."""
        sx = self.g["sx"] if sx is None else sx
        sy = self.g["sy"] if sy is None else sy
        key = ("grid", sx, sy)
        if key not in self._cache:
            w, h = self.g["gcols"] * sx, self.g["rows"] * sy
            r = resample_area(self.work, w, h)
            br, bg_, bb = int_to_rgb01(self.bg)
            flat = r.rgb * r.a[:, :, None] + np.array([br, bg_, bb]) * (1 - r.a[:, :, None])
            self._cache[key] = (flat, r.a)
        return self._cache[key]

    def lum(self, rgb):
        return luminance(rgb, self.p["luma"])

    def ink(self, rgb, a, light_on_dark=None):
        L = self.lum(rgb)
        lod = self.p["light_on_dark"] if light_on_dark is None else light_on_dark
        v = L if lod else 1.0 - L
        if self.p["transparent_bg"]:
            v = np.where(a < 0.5, 0.0, v)
        return np.clip(v, 0, 1)

    def blank(self, a):
        """Cells that should stay empty because the source is transparent there."""
        if not self.p["transparent_bg"]:
            return np.zeros(a.shape, dtype=bool)
        return a < 0.5


# ---------------------------------------------------------------------- colour engine
def _nearest_palette(rgb_cells, palette: list[int]):
    """Nearest palette colour in CIELAB (ΔE76), with an exact-colour cache."""
    flat = rgb_cells.reshape(-1, 3)
    keys = rgb01_to_int(flat)
    uniq, inv = np.unique(keys, return_inverse=True)
    pal = np.array([int_to_rgb01(c) for c in palette])
    plab = rgb_to_lab(pal)
    u_rgb = np.stack([(uniq >> 16) & 255, (uniq >> 8) & 255, uniq & 255], axis=1) / 255.0
    ulab = rgb_to_lab(u_rgb)
    out = np.zeros(len(uniq), dtype=np.int64)
    for s in range(0, len(uniq), 8192):
        d = ((ulab[s:s + 8192, None, :] - plab[None, :, :]) ** 2).sum(axis=2)
        out[s:s + 8192] = np.argmin(d, axis=1)
    return np.array(palette, dtype=np.int64)[out[inv.ravel()]].reshape(rgb_cells.shape[:-1])


def color_palette(ctx: Ctx, mode: str) -> list[int] | None:
    p = ctx.p
    if mode == "ansi16":
        return ANSI16_RGB
    if mode == "ansi256":
        return xterm256()
    if mode == "custom":
        return parse_color_list(p["colors"]) or [0, 0xFFFFFF]
    if mode == "dominant":
        if "dominant" not in ctx._cache:
            ctx._cache["dominant"] = [int(r * 255 + 0.5) << 16 | int(g * 255 + 0.5) << 8 | int(b * 255 + 0.5)
                                      for r, g, b in median_cut(ctx.flat(), p["dominant_k"])]
        return ctx._cache["dominant"]
    return None


def map_colors(ctx: Ctx, rgb, mode: str | None = None):
    """Colour engine: cell colours → 0xRRGGBB int array (or None for monochrome output)."""
    mode = ctx.p["color"] if mode is None else mode
    if mode == "none":
        return None
    if mode == "original":
        return rgb01_to_int(rgb)
    if mode == "grayscale":
        L = luminance(rgb)
        return rgb01_to_int(np.repeat(L[..., None], 3, axis=-1))
    if mode == "gradient":
        stops = parse_color_list(ctx.p["gradient"]) or [0, 0xFFFFFF]
        L = luminance(rgb)
        lut = [gradient_color(stops, i / 255) for i in range(256)]
        return np.array(lut, dtype=np.int64)[np.clip(np.floor(L * 255 + 0.5), 0, 255).astype(np.int64)]
    pal = color_palette(ctx, mode)
    return _nearest_palette(rgb, pal)


def _contrast_fg(colors):
    """Black or white text for coloured backgrounds."""
    r, g, b = (colors >> 16) & 255, (colors >> 8) & 255, colors & 255
    return np.where(0.2126 * r + 0.7152 * g + 0.0722 * b > 140, 0x111111, 0xF5F5F5)


def _dim(colors, f: float):
    r, g, b = (colors >> 16) & 255, (colors >> 8) & 255, colors & 255
    return (np.floor(r * f + 0.5).astype(np.int64) << 16) | (np.floor(g * f + 0.5).astype(np.int64) << 8) | np.floor(b * f + 0.5).astype(np.int64)


def build_art(chars, fg=None, bg=None, blank=None) -> Art:
    """numpy/list grids → Art (None where no colour)."""
    rows = [list(r) for r in chars] if not isinstance(chars, list) else chars
    h = len(rows)
    w = len(rows[0]) if h else 0

    def conv(c):
        if c is None:
            return [[None] * w for _ in range(h)]
        lst = c.tolist()
        if blank is not None:
            bl = blank.tolist()
            for y in range(h):
                for x in range(w):
                    if bl[y][x]:
                        lst[y][x] = None
        return lst
    if blank is not None:
        bl = blank.tolist()
        for y in range(h):
            r = rows[y]
            for x in range(w):
                if bl[y][x]:
                    r[x] = " "
    return Art(rows, conv(fg), conv(bg))


def apply_char_colors(ctx: Ctx, chars, rgb, blank=None) -> Art:
    """Assign colours for single-character-per-cell modes according to color/color_target."""
    cols = map_colors(ctx, rgb)
    if cols is None:
        return build_art(chars, blank=blank)
    t = ctx.p["color_target"]
    if t == "fg":
        return build_art(chars, cols, None, blank)
    if t == "bg":
        return build_art(chars, _contrast_fg(cols), cols, blank)
    return build_art(chars, cols, _dim(cols, 0.3), blank)


# ---------------------------------------------------------------------- quantisation / dithering
def density_levels(chars: list[str]) -> list[float]:
    s = [glyph_coverage_sum(c) for c in chars]
    lo, hi = min(s), max(s)
    if hi == lo:
        n = len(chars)
        return [i / max(1, n - 1) for i in range(n)]
    return [(v - lo) / (hi - lo) for v in s]


def _nearest_level(levels: list[float], v: float) -> int:
    i = bisect_left(levels, v)
    if i <= 0:
        return 0
    if i >= len(levels):
        return len(levels) - 1
    return i - 1 if v - levels[i - 1] <= levels[i] - v else i


def quantize_levels(values, levels: list[float], method: str = "none", strength: float = 1.0):
    """Map a 2-D array of 0..1 values to indices of (ascending) levels with optional dithering."""
    H, W = values.shape
    n = len(levels)
    if method in ("none", "bayer"):
        v = values
        if method == "bayer" and n > 1:
            step = 1.0 / (n - 1)
            B = np.array(BAYER8, dtype=np.float64)
            tile = B[np.arange(H)[:, None] % 8, np.arange(W)[None, :] % 8]
            v = values + (tile / 64.0 - 0.5 + 1 / 128) * step * strength
        L = np.array(levels)
        i = np.clip(np.searchsorted(L, v, side="left"), 0, n - 1)
        im1 = np.clip(i - 1, 0, n - 1)
        choose_lower = (i > 0) & ((v - L[im1]) <= (L[i] - v))
        return np.where(choose_lower, im1, i)
    g = values.tolist()
    out = [[0] * W for _ in range(H)]
    if method == "floyd":
        taps = ((1, 0, 7 / 16), (-1, 1, 3 / 16), (0, 1, 5 / 16), (1, 1, 1 / 16))
    else:  # atkinson
        taps = ((1, 0, 1 / 8), (2, 0, 1 / 8), (-1, 1, 1 / 8), (0, 1, 1 / 8), (1, 1, 1 / 8), (0, 2, 1 / 8))
    for y in range(H):
        row = g[y]
        orow = out[y]
        for x in range(W):
            v = row[x]
            q = _nearest_level(levels, v)
            orow[x] = q
            err = (v - levels[q]) * strength
            if err:
                for dx, dy, f in taps:
                    xx, yy = x + dx, y + dy
                    if 0 <= xx < W and yy < H:
                        g[yy][xx] += err * f
    return np.array(out, dtype=np.int64)


def adaptive_mask(ink, threshold: float, radius: int | None = None):
    """Local-mean adaptive threshold: on where ink exceeds the neighbourhood mean by an offset."""
    r = radius if radius is not None else max(2, min(ink.shape) // 12)
    mean = box_mean(ink, r)
    return ink > mean + (threshold - 0.5) * 0.4


def binarize(ctx: Ctx, ink):
    p = ctx.p
    if p["adaptive"]:
        return adaptive_mask(ink, p["threshold"]) & (ink > 0.04)
    if p["dither"] != "none":
        q = quantize_levels(ink, [0.0, 1.0], p["dither"], p["dither_strength"])
        return q == 1
    return ink >= p["threshold"]


# ---------------------------------------------------------------------- shared renderers
def _ramp(ctx: Ctx, chars: list[str], ink, rgb, a, dither: str | None = None):
    levels = density_levels(chars)
    q = quantize_levels(ink, levels, dither or ctx.p["dither"], ctx.p["dither_strength"])
    arr = np.array(chars, dtype=object)[q]
    return apply_char_colors(ctx, arr.tolist(), rgb, ctx.blank(a))


def _palette(ctx: Ctx, mode: str) -> list[str]:
    return resolve_palette(ctx.p["palette"] or DEFAULT_PALETTE.get(mode, "ascii_extended"), reverse=ctx.p["palette_reverse"])


def _cell_features(arr, fw: int, fh: int):
    """(rows*fh, cols*fw[,C]) → (rows*cols, fh*fw[,C]) blocks in reading order."""
    H, W = arr.shape[:2]
    rows, cols = H // fh, W // fw
    if arr.ndim == 2:
        return arr.reshape(rows, fh, cols, fw).transpose(0, 2, 1, 3).reshape(rows * cols, fh * fw)
    C = arr.shape[2]
    return arr.reshape(rows, fh, cols, fw, C).transpose(0, 2, 1, 3, 4).reshape(rows * cols, fh * fw, C)


def _cell_mean_rgb(rgb, fw, fh):
    return _cell_features(rgb, fw, fh).mean(axis=1).reshape(rgb.shape[0] // fh, rgb.shape[1] // fw, 3)


def _cell_mean(a, fw, fh):
    return _cell_features(a, fw, fh).mean(axis=1).reshape(a.shape[0] // fh, a.shape[1] // fw)


_MATCHERS: dict = {}


def matcher_for(chars: list[str], fw: int, fh: int, k: int = 24) -> GlyphMatcher:
    key = ("".join(chars), fw, fh, k)
    m = _MATCHERS.get(key)
    if m is None:
        if len(_MATCHERS) > 24:
            _MATCHERS.clear()
        m = _MATCHERS[key] = GlyphMatcher(chars, fw, fh, k)
    return m


def _shape_match(ctx: Ctx, chars: list[str], fw: int, fh: int, k: int = 24, ink=None):
    rgb, a = ctx.grid(fw, fh)
    if ink is None:
        ink = ctx.ink(rgb, a)
    m = matcher_for(chars, fw, fh, k)
    idx = m.match(_cell_features(ink, fw, fh))
    rows, cols = ctx.g["rows"], ctx.g["gcols"]
    out = np.array(m.chars, dtype=object)[idx].reshape(rows, cols)
    return out, _cell_mean_rgb(rgb, fw, fh), _cell_mean(a, fw, fh)


def _fit_masks(P, M, chunk: int = 2048):
    """Least-squares two-colour fit of every cell P (n,F,3) against every mask M (G,F).

    For mask m the optimal colours solve [Σm² Σm(1−m); Σm(1−m) Σ(1−m)²]·[fg; bg] = [Σm·P; Σ(1−m)·P];
    colours are clipped to 0–1 and the exact squared error of the clipped colours is used.
    Returns (best glyph index, fg (n,3), bg (n,3)). Ties keep the lower glyph index.
    """
    n, F = P.shape[0], P.shape[1]
    G = M.shape[0]
    s1 = M.sum(axis=1); s2 = (M * M).sum(axis=1)
    a11, a12, a22 = s2, s1 - s2, F - 2 * s1 + s2
    det = a11 * a22 - a12 * a12
    sing = np.abs(det) < 1e-9
    sdet = np.where(sing, 1.0, det)
    best_g = np.zeros(n, dtype=np.int64); best_fg = np.zeros((n, 3)); best_bg = np.zeros((n, 3))
    for s in range(0, n, chunk):
        Pc = P[s:s + chunk]
        sumP = Pc.sum(axis=1)                         # (c,3)
        sq = (Pc * Pc).sum(axis=(1, 2))                # (c,)
        mp = np.einsum("nfc,gf->ngc", Pc, M)          # (c,G,3)
        b2 = sumP[:, None, :] - mp
        fg = (a22[None, :, None] * mp - a12[None, :, None] * b2) / sdet[None, :, None]
        bg = (a11[None, :, None] * b2 - a12[None, :, None] * mp) / sdet[None, :, None]
        mean = (sumP / F)[:, None, :]
        fg = np.where(sing[None, :, None], mean, fg); bg = np.where(sing[None, :, None], mean, bg)
        fg = np.clip(fg, 0, 1); bg = np.clip(bg, 0, 1)
        err = (sq[:, None] - 2 * (fg * mp).sum(axis=2) - 2 * (bg * b2).sum(axis=2)
               + (fg * fg).sum(axis=2) * s2[None, :] + 2 * (fg * bg).sum(axis=2) * a12[None, :]
               + (bg * bg).sum(axis=2) * a22[None, :])
        err = np.floor(err * 1e8 + 0.5)  # quantised so mathematically tied glyphs resolve identically in both editions
        gi = np.argmin(err, axis=1)
        r = np.arange(len(Pc))
        best_g[s:s + chunk] = gi
        best_fg[s:s + chunk] = fg[r, gi]
        best_bg[s:s + chunk] = bg[r, gi]
    return best_g, best_fg, best_bg


def _two_color_patterns(ctx: Ctx, sx: int, sy: int, char_of):
    """Exhaustive two-colour partition per cell over all 2^(sx*sy) patterns (minimises squared RGB error)."""
    rgb, a = ctx.grid(sx, sy)
    rows, cols = ctx.g["rows"], ctx.g["gcols"]
    k = sx * sy
    if ctx.p["color"] == "none":
        ink = ctx.ink(rgb, a)
        bits = binarize(ctx, ink)
        B = _cell_features(bits.astype(np.int64), sx, sy)
        code = (B * (1 << np.arange(k))[None, :]).sum(axis=1)
        chars = [char_of(int(c)) for c in code]
        arr = np.array(chars, dtype=object).reshape(rows, cols)
        return build_art(arr.tolist(), blank=ctx.blank(_cell_mean(a, sx, sy)))
    P = _cell_features(rgb, sx, sy)
    codes = list(range(1, 1 << k))
    M = np.array([[(c >> i) & 1 for i in range(k)] for c in codes], dtype=np.float64)
    gi, fg, bg = _fit_masks(P, M)
    code = np.array(codes, dtype=np.int64)[gi]
    full = code == (1 << k) - 1
    bg = np.where(full[:, None], fg, bg)
    chars = np.array([char_of(int(c)) for c in code], dtype=object).reshape(rows, cols)
    cm = "original" if ctx.p["color"] in ("none", "original") else None
    fgc = map_colors(ctx, fg.reshape(rows, cols, 3), cm)
    bgc = map_colors(ctx, bg.reshape(rows, cols, 3), cm)
    return build_art(chars.tolist(), fgc, bgc, ctx.blank(_cell_mean(a, sx, sy)))


def _fit_glyph_colors(ctx: Ctx, chars: list[str], fw: int, fh: int):
    """For each cell choose the glyph + fg/bg colours minimising ‖P − (m·fg + (1−m)·bg)‖² (least squares)."""
    rgb, a = ctx.grid(fw, fh)
    rows, cols = ctx.g["rows"], ctx.g["gcols"]
    P = _cell_features(rgb, fw, fh)
    gi, fg, bg = _fit_masks(P, masks_float(chars, fw, fh))
    out = np.array(chars, dtype=object)[gi].reshape(rows, cols)
    cm = "original" if ctx.p["color"] in ("none", "original") else None
    fgc = map_colors(ctx, fg.reshape(rows, cols, 3), cm)
    bgc = map_colors(ctx, bg.reshape(rows, cols, 3), cm)
    return build_art(out.tolist(), fgc, bgc, ctx.blank(_cell_mean(a, fw, fh)))


def _edge_field(ctx: Ctx):
    """Edge magnitude (0..1, scaled by edge_strength) and orientation tensors at the working resolution."""
    if "edges" in ctx._cache:
        return ctx._cache["edges"]
    L = ctx.lum(ctx.flat())
    gx, gy = sobel(blur(L, 0.7))
    mag = np.sqrt(gx * gx + gy * gy) / 4.0 * ctx.p["edge_strength"]
    method = ctx.p["edge_method"]
    if method == "canny":
        e, _, _ = canny(L, ctx.p["edge_threshold"] * 0.5, ctx.p["edge_threshold"])
        mag = np.where(e, np.maximum(mag, ctx.p["edge_threshold"] + 1e-6), 0.0)
    elif method == "dog":
        d = blur(L, 1.0) - blur(L, 1.6)
        mag = np.clip(np.abs(d) * 12 * ctx.p["edge_strength"], 0, 1)
    ctx._cache["edges"] = (np.clip(mag, 0, 1), gx * gx, gy * gy, gx * gy)
    return ctx._cache["edges"]


def _orientation_chars(ctx: Ctx):
    """Per-cell edge strength and orientation glyph from the averaged structure tensor."""
    mag, jxx, jyy, jxy = _edge_field(ctx)
    rows, cols = ctx.g["rows"], ctx.g["gcols"]
    M = resample_plane(mag, cols, rows)
    Jxx, Jyy, Jxy = (resample_plane(j, cols, rows) for j in (jxx, jyy, jxy))
    phi = 0.5 * np.arctan2(2 * Jxy, Jxx - Jyy)  # gradient direction, y down
    edge = (np.degrees(-phi) + 90.0) % 180.0     # edge direction, y up, 0..180
    glyph = np.where((edge < 31.5) | (edge >= 148.5), "-",
                     np.where(edge < 76.5, "/", np.where(edge < 103.5, "|", "\\"))).astype(object)
    return M, glyph


# ---------------------------------------------------------------------- the 30 modes
def m_classic(ctx):
    rgb, a = ctx.grid(1, 1)
    return _ramp(ctx, _palette(ctx, "classic"), ctx.ink(rgb, a), rgb, a)


def m_extended(ctx):
    chars, rgb, a = _shape_match(ctx, _palette(ctx, "extended"), 2, 2, 32)
    return apply_char_colors(ctx, chars.tolist(), rgb, ctx.blank(a))


def m_blocks(ctx):
    rgb, a = ctx.grid(1, 1)
    chars = resolve_palette(ctx.p["palette"] or "blocks", reverse=ctx.p["palette_reverse"])
    d = ctx.p["dither"] if ctx.p["dither"] != "none" else "floyd"
    return _ramp(ctx, chars, ctx.ink(rgb, a), rgb, a, d)


def m_half(ctx):
    rgb, a = ctx.grid(1, 2)
    rows, cols = ctx.g["rows"], ctx.g["gcols"]
    top, bot = rgb[0::2], rgb[1::2]
    at, ab = a[0::2], a[1::2]
    if ctx.p["color"] == "none":
        bits = binarize(ctx, ctx.ink(rgb, a))
        code = bits[0::2].astype(np.int64) | (bits[1::2].astype(np.int64) << 1)
        chars = np.array(list(" ▀▄█"), dtype=object)[code]
        return build_art(chars.tolist())
    fg = map_colors(ctx, top)
    bgc = map_colors(ctx, bot)
    chars = np.full((rows, cols), "▀", dtype=object)
    if ctx.p["transparent_bg"]:
        tt, tb = at < 0.5, ab < 0.5
        chars = np.where(tt & tb, " ", np.where(tt, "▄", chars))
        fg2 = np.where(tt, bgc, fg)
        bg2 = np.where(tt | tb, -1, bgc)
        art = build_art(chars.tolist(), fg2, None)
        bl = bg2.tolist()
        art.bg = [[None if v < 0 else v for v in r] for r in bl]
        for y in range(rows):
            for x in range(cols):
                if chars[y, x] == " ":
                    art.fg[y][x] = None
        return art
    return build_art(chars.tolist(), fg, bgc)


def m_quadrant(ctx):
    return _two_color_patterns(ctx, 2, 2, lambda c: QUADRANT_CHARS[c])


def m_sextant(ctx):
    return _two_color_patterns(ctx, 2, 3, sextant_char)


def m_braille(ctx):
    rgb, a = ctx.grid(2, 4)
    rows, cols = ctx.g["rows"], ctx.g["gcols"]
    ink = ctx.ink(rgb, a)
    on = binarize(ctx, ink)
    if ctx.p["transparent_bg"]:
        on &= a >= 0.5
    code = np.zeros((rows, cols), dtype=np.int64)
    for bit, (dx, dy) in enumerate(BRAILLE_DOTS):
        code |= on[dy::4, dx::2].astype(np.int64) << bit
    chars = np.vectorize(lambda c: chr(0x2800 + int(c)), otypes=[object])(code)
    if ctx.p["color"] == "none":
        return build_art(chars.tolist())
    F = _cell_features(rgb, 2, 4)
    O = _cell_features(on.astype(np.float64), 2, 4)
    cnt = O.sum(axis=1)
    mean_on = (F * O[:, :, None]).sum(axis=1) / np.maximum(cnt, 1)[:, None]
    mean_all = F.mean(axis=1)
    col = np.where((cnt > 0)[:, None], mean_on, mean_all).reshape(rows, cols, 3)
    return apply_char_colors(ctx, chars.tolist(), col, None)


def _palette_diffuse(rgb, palette: list[int], dither: str, strength: float):
    """Error diffusion in RGB with nearest-palette selection in CIELAB (cached per exact colour)."""
    H, W = rgb.shape[:2]
    pal = np.array([int_to_rgb01(c) for c in palette])
    plab = rgb_to_lab(pal).tolist()
    pal_l = pal.tolist()
    cache: dict = {}
    from .imgcore import rgb_to_lab as _lab

    def nearest(r, g, b):
        key = (int(r * 255 + 0.5) if r > 0 else 0, int(g * 255 + 0.5) if g > 0 else 0, int(b * 255 + 0.5) if b > 0 else 0)
        key = (min(255, key[0]), min(255, key[1]), min(255, key[2]))
        if key in cache:
            return cache[key]
        lab = _lab(np.array([key[0] / 255, key[1] / 255, key[2] / 255])).tolist()
        bi, bd = 0, float("inf")
        for i, q in enumerate(plab):
            d = (lab[0] - q[0]) ** 2 + (lab[1] - q[1]) ** 2 + (lab[2] - q[2]) ** 2
            if d < bd:
                bd, bi = d, i
        cache[key] = bi
        return bi
    g = rgb.tolist()
    out = [[0] * W for _ in range(H)]
    taps = ((1, 0, 7 / 16), (-1, 1, 3 / 16), (0, 1, 5 / 16), (1, 1, 1 / 16)) if dither == "floyd" else \
        ((1, 0, 1 / 8), (2, 0, 1 / 8), (-1, 1, 1 / 8), (0, 1, 1 / 8), (1, 1, 1 / 8), (0, 2, 1 / 8))
    for y in range(H):
        for x in range(W):
            r, gg, b = g[y][x]
            i = nearest(r, gg, b)
            out[y][x] = palette[i]
            q = pal_l[i]
            er, eg, eb = (r - q[0]) * strength, (gg - q[1]) * strength, (b - q[2]) * strength
            for dx, dy, f in taps:
                xx, yy = x + dx, y + dy
                if 0 <= xx < W and yy < H:
                    c = g[yy][xx]
                    g[yy][xx] = [c[0] + er * f, c[1] + eg * f, c[2] + eb * f]
    return np.array(out, dtype=np.int64)


def _half_from_colors(ctx, colors, a):
    rows, cols = ctx.g["rows"], ctx.g["gcols"]
    fg, bgc = colors[0::2], colors[1::2]
    chars = np.full((rows, cols), "▀", dtype=object)
    blank = ctx.blank(np.maximum(a[0::2], a[1::2]))
    return build_art(chars.tolist(), fg, bgc, blank)


def _ansi_palette_mode(ctx, palette, default_dither):
    rgb, a = ctx.grid(1, 2)
    d = ctx.p["dither"] if ctx.p["dither"] != "none" else default_dither
    if d in ("floyd", "atkinson"):
        colors = _palette_diffuse(rgb, palette, d, ctx.p["dither_strength"])
    else:
        colors = _nearest_palette(rgb, palette)
    return _half_from_colors(ctx, colors, a)


def m_ansi16(ctx):
    return _ansi_palette_mode(ctx, ANSI16_RGB, "floyd")


def m_ansi256(ctx):
    return _ansi_palette_mode(ctx, xterm256(), "none")


def m_truecolor(ctx):
    rgb, a = ctx.grid(1, 2)
    return _half_from_colors(ctx, rgb01_to_int(rgb), a)


def m_mono(ctx):
    rgb, a = ctx.grid(1, 2)
    ink = ctx.ink(rgb, a)
    d = ctx.p["dither"] if ctx.p["dither"] != "none" else "floyd"
    if ctx.p["adaptive"]:
        bits = adaptive_mask(ink, ctx.p["threshold"])
    else:
        bits = quantize_levels(ink, [0.0, 1.0], d, ctx.p["dither_strength"]) == 1
    code = bits[0::2].astype(np.int64) | (bits[1::2].astype(np.int64) << 1)
    return build_art(np.array(list(" ▀▄█"), dtype=object)[code].tolist())


def m_grayscale(ctx):
    rgb, a = ctx.grid(1, 2)
    L = ctx.lum(rgb)
    levels = [((c >> 16) & 255) / 255 for c in GRAY26]
    d = ctx.p["dither"] if ctx.p["dither"] != "none" else "bayer"
    q = quantize_levels(L, levels, d, ctx.p["dither_strength"])
    colors = np.array(GRAY26, dtype=np.int64)[q]
    return _half_from_colors(ctx, colors, a)


def m_binary(ctx):
    rgb, a = ctx.grid(1, 1)
    ink = ctx.ink(rgb, a)
    r = max(2, min(ink.shape) // 10)
    mean = box_mean(ink, r)
    t = ctx.p["threshold"]
    hi = ink > np.maximum(mean, t)
    lo = ink > np.minimum(mean, t) * 0.5
    chars = np.where(hi, "1", np.where(lo, "0", " ")).astype(object)
    return apply_char_colors(ctx, chars.tolist(), rgb, ctx.blank(a))


def m_matrix(ctx):
    rgb, a = ctx.grid(1, 1)
    rows, cols = ctx.g["rows"], ctx.g["gcols"]
    L = ctx.lum(rgb)
    if not ctx.p["light_on_dark"]:
        L = 1 - L
    rng = Rng(ctx.p["seed"])
    glyphs = graphemes_simple(MATRIX_GLYPHS)
    heads = [rng.int(rows + 8) for _ in range(cols)]
    trail = [4 + rng.int(max(4, rows // 2)) for _ in range(cols)]
    chars = [[" "] * cols for _ in range(rows)]
    fg = [[None] * cols for _ in range(rows)]
    Ll = L.tolist()
    blank = ctx.blank(a).tolist()
    for y in range(rows):
        for x in range(cols):
            v = Ll[y][x]
            g = glyphs[rng.int(len(glyphs))]
            if v < 0.08 or blank[y][x]:
                continue
            d = heads[x] - y
            boost = 1.0 if d == 0 else (0.35 * (1 - d / trail[x]) if 0 < d < trail[x] else 0.0)
            chars[y][x] = g
            gl = min(1.0, v * 0.9 + boost * 0.5)
            if d == 0:
                fg[y][x] = (int(180 + 75 * gl) << 16) | (255 << 8) | int(180 + 75 * gl)
            else:
                fg[y][x] = (int(30 * gl) << 16) | (int(60 + 195 * gl) << 8) | int(40 * gl)
    return Art(chars, fg, [[None] * cols for _ in range(rows)])


def m_emoji(ctx):
    rgb, a = ctx.grid(1, 1)
    rows, cols = ctx.g["rows"], ctx.g["gcols"]
    spec = ctx.p["palette"]
    if spec and spec != "emoji":
        allowed = set(graphemes_simple(spec))
        pal = [(e, c) for e, c in EMOJI_COLORS if e in allowed] or EMOJI_COLORS
    else:
        pal = EMOJI_COLORS
    picked = _nearest_palette(rgb, [c for _, c in pal])
    by_color = {}
    for e, c in pal:
        by_color.setdefault(c, e)
    blank = ctx.blank(a).tolist()
    pk = picked.tolist()
    chars = []
    for y in range(rows):
        r = []
        for x in range(cols):
            if blank[y][x]:
                r += [" ", " "]
            else:
                r += [by_color[pk[y][x]], ""]
        chars.append(r)
    return Art(chars)


def m_pixel(ctx):
    rgb, a = ctx.grid(1, 1)
    rows, cols = ctx.g["rows"], ctx.g["gcols"]
    mode = ctx.p["color"]
    if mode in ("none", "original"):
        k = ctx.p["dominant_k"] if mode == "none" else 0
        colors = _nearest_palette(rgb, [int(r * 255 + 0.5) << 16 | int(g * 255 + 0.5) << 8 | int(b * 255 + 0.5)
                                        for r, g, b in median_cut(ctx.flat(), max(2, k or 16))]) if k else rgb01_to_int(rgb)
    else:
        colors = map_colors(ctx, rgb)
    blank = ctx.blank(a)
    c2 = np.repeat(colors, 2, axis=1)
    chars = np.where(np.repeat(blank, 2, axis=1), " ", "█").astype(object)
    return build_art(chars.tolist(), c2, None, np.repeat(blank, 2, axis=1))


def m_dotted(ctx):
    rgb, a = ctx.grid(1, 1)
    chars = resolve_palette(ctx.p["palette"] or "dots", reverse=ctx.p["palette_reverse"])
    levels = density_levels(chars)
    ink = ctx.ink(rgb, a)
    H, W = ink.shape
    n = len(levels)
    # 45° clustered screen: alternate cells are offset by half a level (classic AM halftone look)
    off = np.where((np.arange(H)[:, None] + np.arange(W)[None, :]) % 2 == 0, -0.25, 0.25) / max(1, n - 1)
    q = quantize_levels(np.clip(ink + off, 0, 1), levels, "none")
    arr = np.array(chars, dtype=object)[q]
    return apply_char_colors(ctx, arr.tolist(), rgb, ctx.blank(a))


def m_edge(ctx):
    rgb, a = ctx.grid(1, 1)
    M, glyph = _orientation_chars(ctx)
    chars = np.where(M >= ctx.p["edge_threshold"] * 0.5, glyph, " ").astype(object)
    return apply_char_colors(ctx, chars.tolist(), rgb, ctx.blank(a))


CONTOUR_CHARS = {1: "╯", 2: "╰", 4: "╭", 8: "╮", 3: "─", 12: "─", 9: "│", 6: "│", 5: "╳", 10: "╳"}


def m_contour(ctx):
    rows, cols = ctx.g["rows"], ctx.g["gcols"]
    L = ctx.lum(ctx.flat())
    Lc = resample_plane(blur(L, 1.0), cols + 1, rows + 1)
    n = ctx.p["levels"]
    band = np.clip(np.floor(Lc * n), 0, n - 1).astype(np.int64)
    tl, tr, br, bl = band[:-1, :-1], band[:-1, 1:], band[1:, 1:], band[1:, :-1]
    mx = np.maximum(np.maximum(tl, tr), np.maximum(br, bl))
    mask = (tl == mx).astype(np.int64) | ((tr == mx).astype(np.int64) << 1) | ((br == mx).astype(np.int64) << 2) | ((bl == mx).astype(np.int64) << 3)
    pc = np.vectorize(lambda m: bin(int(m)).count("1"))(mask)
    mask = np.where(pc > 2, 15 - mask, mask)
    chars = np.vectorize(lambda m: CONTOUR_CHARS.get(int(m), " "), otypes=[object])(mask)
    rgb, a = ctx.grid(1, 1)
    if ctx.p["color"] == "none":
        return build_art(chars.tolist(), blank=ctx.blank(a))
    if ctx.p["color"] == "gradient":
        stops = parse_color_list(ctx.p["gradient"]) or [0, 0xFFFFFF]
        lut = np.array([gradient_color(stops, i / max(1, n - 1)) for i in range(n)], dtype=np.int64)
        return build_art(chars.tolist(), lut[mx], None, ctx.blank(a))
    return apply_char_colors(ctx, chars.tolist(), rgb, ctx.blank(a))


def m_line(ctx):
    rgb, a = ctx.grid(4, 8)
    L = ctx.lum(ctx.flat())
    s = max(0.6, ctx.work.width / (ctx.g["gcols"] * 4) * 0.6)
    d = blur(L, s) - blur(L, s * 1.6)
    lines = np.clip(-d * 40 * ctx.p["edge_strength"] - ctx.p["edge_threshold"], 0, 1)
    lw = resample_plane(lines, ctx.g["gcols"] * 4, ctx.g["rows"] * 8)
    if ctx.p["transparent_bg"]:
        lw = np.where(a < 0.5, 0.0, lw)
    chars, crgb, ca = _shape_match(ctx, _palette(ctx, "line"), 4, 8, 18, ink=lw)
    return apply_char_colors(ctx, chars.tolist(), crgb, None)


def foreground_mask(ctx: Ctx):
    """Foreground: alpha where the image is transparent, else the Otsu class not dominating the border."""
    work = ctx.work
    if (work.a < 0.5).mean() > 0.01:
        return work.a >= 0.5
    L = ctx.lum(ctx.flat())
    t = otsu(L)
    dark = L < t
    border = np.concatenate([dark[0], dark[-1], dark[:, 0], dark[:, -1]])
    return dark if border.mean() < 0.5 else ~dark


def m_silhouette(ctx):
    rows, cols = ctx.g["rows"], ctx.g["gcols"]
    fgm = foreground_mask(ctx).astype(np.float64)
    m = resample_plane(fgm, cols * 2, rows * 2) >= 0.5
    B = _cell_features(m.astype(np.int64), 2, 2)
    code = (B * np.array([1, 2, 4, 8])[None, :]).sum(axis=1).reshape(rows, cols)
    chars = np.array(list(QUADRANT_CHARS), dtype=object)[code]
    rgb, a = ctx.grid(1, 1)
    return apply_char_colors(ctx, chars.tolist(), rgb, None)


def m_typographic(ctx):
    chars, rgb, a = _shape_match(ctx, _palette(ctx, "typographic"), 4, 8, 24)
    return apply_char_colors(ctx, chars.tolist(), rgb, ctx.blank(a))


def _text_stream(text: str, direction: str):
    from .arabic import contains_arabic, paragraph_level, shape
    from .figlet import char_width
    text = " ".join(clean_palette(text).split()) or "LeerBox"
    rtl = direction == "rtl" or (direction == "auto" and paragraph_level(text, "auto") == 1)
    if contains_arabic(text):
        text = shape(text)
    gs = graphemes_simple(text + " ")
    return [(g, max(1, char_width(g))) for g in gs], rtl


def m_words(ctx):
    rgb, a = ctx.grid(1, 1)
    rows, cols = ctx.g["rows"], ctx.g["gcols"]
    ink = ctx.ink(rgb, a)
    p = ctx.p
    stream, rtl = _text_stream(p["text"], p["text_dir"])
    words = []
    cur = []
    for g, w in stream:
        cur.append((g, w))
        if g == " ":
            words.append(cur); cur = []
    if cur:
        words.append(cur)
    on = (ink >= p["threshold"] * 0.6) if p["text_mode"] != "fill" else np.ones(ink.shape, dtype=bool)
    if p["transparent_bg"]:
        on &= a >= 0.5
    onl = on.tolist()
    chars = [[" "] * cols for _ in range(rows)]
    si, wi = 0, 0
    for y in range(rows):
        xs = list(range(cols - 1, -1, -1)) if rtl else list(range(cols))
        if p["text_mode"] == "words":
            k = 0
            while k < len(xs):
                if not onl[y][xs[k]]:
                    k += 1; continue
                run = 0
                while k + run < len(xs) and onl[y][xs[k + run]]:
                    run += 1
                pos = k
                while True:
                    word = words[wi % len(words)]
                    wl = sum(w for _, w in word)
                    if pos + wl - (1 if word[-1][0] == " " else 0) > k + run:
                        break
                    for g, w in word:
                        if pos >= k + run:
                            break
                        if w == 2 and pos + 1 < k + run:
                            if rtl:
                                chars[y][xs[pos + 1]] = g; chars[y][xs[pos]] = ""
                            else:
                                chars[y][xs[pos]] = g; chars[y][xs[pos + 1]] = ""
                            pos += 2
                        elif w == 1:
                            chars[y][xs[pos]] = g; pos += 1
                        else:
                            pos += 1
                    wi += 1
                for j in range(pos, k + run):
                    chars[y][xs[j]] = "·"
                k += run
        else:
            k = 0
            while k < len(xs):
                if not onl[y][xs[k]]:
                    k += 1; continue
                g, w = stream[si % len(stream)]
                if w == 2:
                    if k + 1 < len(xs) and onl[y][xs[k + 1]]:
                        if rtl:
                            chars[y][xs[k + 1]] = g; chars[y][xs[k]] = ""
                        else:
                            chars[y][xs[k]] = g; chars[y][xs[k + 1]] = ""
                        k += 2; si += 1
                    else:
                        k += 1
                    continue
                chars[y][xs[k]] = g
                k += 1; si += 1
    art = apply_char_colors(ctx, chars, rgb, None)
    if ctx.p["color"] == "none" and p["text_mode"] == "fill":
        # without colour the 'fill' layout encodes luminance by case: dense regions upper-case
        il = ink.tolist()
        for y in range(rows):
            for x in range(cols):
                c = art.chars[y][x]
                if len(c) == 1 and il[y][x] < 0.35:
                    art.chars[y][x] = c.lower() if il[y][x] >= 0.12 else ("." if c.strip() else c)
                elif len(c) == 1:
                    art.chars[y][x] = c.upper()
    return art


def m_math(ctx):
    chars, rgb, a = _shape_match(ctx, _palette(ctx, "math"), 4, 8, 16)
    return apply_char_colors(ctx, chars.tolist(), rgb, ctx.blank(a))


MOSAIC_GLYPHS = [" ", "█", "▀", "▄", "▌", "▐", "◢", "◣", "◤", "◥", "●", "◆", "▲", "▼", "■", "◖", "◗"]


def _available(chars):
    from .imgglyphs import glyph_mask
    return [c for c in chars if glyph_mask(c) is not None]


def m_mosaic(ctx):
    return _fit_glyph_colors(ctx, _available(MOSAIC_GLYPHS), 4, 8)


DENSE_GLYPHS = ([" ", "█", "▀", "▄", "▌", "▐", "▖", "▗", "▘", "▝", "▚", "▞", "▙", "▛", "▜", "▟"]
                + [chr(c) for c in range(0x2581, 0x2588)] + [chr(c) for c in range(0x2589, 0x2590)]
                + [chr(c) for c in range(0x1FB00, 0x1FB3C)])


def m_dense(ctx):
    return _fit_glyph_colors(ctx, DENSE_GLYPHS, 4, 8)


def m_adaptive(ctx):
    rgb, a = ctx.grid(4, 8)
    ink = ctx.ink(rgb, a)
    rows, cols = ctx.g["rows"], ctx.g["gcols"]
    feats = _cell_features(ink, 4, 8)
    std = feats.std(axis=1).reshape(rows, cols)
    chars = _palette(ctx, "adaptive")
    shaped, crgb, ca = _shape_match(ctx, chars, 4, 8, 24, ink=ink)
    mean_ink = feats.mean(axis=1).reshape(rows, cols)
    levels = density_levels(chars)
    q = quantize_levels(mean_ink, levels, ctx.p["dither"], ctx.p["dither_strength"])
    ramp = np.array(chars, dtype=object)[q]
    detail = std > 0.12 + (ctx.p["edge_threshold"] - 0.25) * 0.3
    out = np.where(detail, shaped, ramp)
    return apply_char_colors(ctx, out.tolist(), crgb, ctx.blank(ca))


def m_hybrid(ctx):
    rgb, a = ctx.grid(1, 1)
    chars = _palette(ctx, "hybrid")
    q = quantize_levels(ctx.ink(rgb, a), density_levels(chars), ctx.p["dither"], ctx.p["dither_strength"])
    base = np.array(chars, dtype=object)[q]
    M, glyph = _orientation_chars(ctx)
    out = np.where(M >= ctx.p["edge_threshold"], glyph, base)
    return apply_char_colors(ctx, out.tolist(), rgb, ctx.blank(a))


def m_negative(ctx):
    rgb, a = ctx.grid(1, 1)
    from .imgcore import linear_to_srgb, srgb_to_linear
    neg = linear_to_srgb(1.0 - srgb_to_linear(rgb))
    L = luminance(neg, "perceptual")
    ink = L if ctx.p["light_on_dark"] else 1 - L
    if ctx.p["transparent_bg"]:
        ink = np.where(a < 0.5, 0.0, ink)
    chars = _palette(ctx, "negative")
    q = quantize_levels(np.clip(ink, 0, 1), density_levels(chars), ctx.p["dither"], ctx.p["dither_strength"])
    return apply_char_colors(ctx, np.array(chars, dtype=object)[q].tolist(), neg, ctx.blank(a))


def m_multilayer(ctx):
    rgb, a = ctx.grid(4, 8)
    rows, cols = ctx.g["rows"], ctx.g["gcols"]
    cm = _cell_mean_rgb(rgb, 4, 8)
    low_c = blur(cm, 1.5)                                   # layer 1: low-pass colour
    L = ctx.lum(rgb)
    det = _cell_mean(np.abs(L - blur(L, 3.0)), 4, 8)         # layer 2: high-pass luminance detail
    det_n = np.clip(det * 6, 0, 1)
    chars = _palette(ctx, "multilayer")
    q = quantize_levels(det_n, density_levels(chars), "none")
    mid = np.array(chars, dtype=object)[q]
    M, glyph = _orientation_chars(ctx)                       # layer 3: edges
    edge = M >= ctx.p["edge_threshold"]
    out = np.where(edge, glyph, mid)
    bgc = rgb01_to_int(low_c * 0.55)
    fgc = rgb01_to_int(np.clip(cm * 1.25 + 0.08, 0, 1))
    fgc = np.where(edge, rgb01_to_int(np.clip(cm * 0.5 + 0.5, 0, 1)), fgc)
    if ctx.p["color"] not in ("none", "original"):
        fgc = map_colors(ctx, cm)
        bgc = map_colors(ctx, low_c * 0.55)
    art = build_art(out.tolist(), fgc, bgc, ctx.blank(_cell_mean(a, 4, 8)))
    art.meta["layers"] = ["background: low-pass colour", "detail: high-pass luminance glyphs", "edges: orientation glyphs"]
    return art


RENDERERS = {
    "classic": m_classic, "extended": m_extended, "blocks": m_blocks, "half": m_half, "quadrant": m_quadrant,
    "sextant": m_sextant, "braille": m_braille, "ansi16": m_ansi16, "ansi256": m_ansi256, "truecolor": m_truecolor,
    "mono": m_mono, "grayscale": m_grayscale, "binary": m_binary, "matrix": m_matrix, "emoji": m_emoji,
    "pixel": m_pixel, "dotted": m_dotted, "edge": m_edge, "contour": m_contour, "line": m_line,
    "silhouette": m_silhouette, "typographic": m_typographic, "words": m_words, "math": m_math,
    "mosaic": m_mosaic, "dense": m_dense, "adaptive": m_adaptive, "hybrid": m_hybrid, "negative": m_negative,
    "multilayer": m_multilayer,
}
assert set(RENDERERS) == set(MODES)


class RenderCancelled(Exception):
    pass


def render_image_art(src: RasterImage, params: dict | None = None, cancel=None) -> tuple[Art, dict]:
    """Full pipeline: sanitize → prepare → mode renderer. Returns (art, stats)."""
    require_numpy()
    p = sanitize_params(params)
    t0 = time.perf_counter()
    work, g = prepare(src, p)
    if cancel is not None and cancel():
        raise RenderCancelled()
    ctx = Ctx(work, g, p)
    art = RENDERERS[p["mode"]](ctx)
    if cancel is not None and cancel():
        raise RenderCancelled()
    art.meta["image_mode"] = p["mode"]
    dt = (time.perf_counter() - t0) * 1000
    txt_bytes = sum(len("".join(r).rstrip().encode("utf-8")) + 1 for r in art.chars)
    stats = {"mode": p["mode"], "label": MODES[p["mode"]][0], "cols": art.width, "rows": art.height,
             "chars": art.width * art.height, "source": [src.width, src.height], "work": [work.width, work.height],
             "ms": round(dt, 1), "text_bytes": txt_bytes, "compat": COMPAT_NOTES[MODES[p["mode"]][5]],
             "est_memory_bytes": work.width * work.height * 8 * 6 + art.width * art.height * 120}
    return art, stats
