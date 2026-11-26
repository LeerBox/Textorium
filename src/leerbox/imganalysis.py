"""Image analysis, recommendations, reconstruction metrics and Smart Optimize.

Everything here is deterministic signal processing and simple rules — no machine learning. The quality
metrics (luminance RMSE, SSIM, edge correlation, CIELAB ΔE, size) are approximations of visual quality.
"""
from __future__ import annotations

import time

from .art import Art
from .imgcore import (RasterImage, blur, box_mean, composite, luminance, median_cut, np, otsu, require_numpy,
                      resample_area, rgb_to_lab, sobel)
from .imgglyphs import EMOJI_COLORS, glyph_mask
from .imgmodes import MODES, RenderCancelled, render_image_art, sanitize_params, prepare

# ---------------------------------------------------------------------- analysis
ORIENT_NAMES = ["horizontal", "diagonal ↗", "vertical", "diagonal ↘"]


def analyze(src: RasterImage) -> dict:
    """Measure the image and derive recommended settings (each with a reason)."""
    require_numpy()
    s = min(1.0, 384 / max(src.width, src.height))
    work = resample_area(src, max(8, round(src.width * s)), max(8, round(src.height * s)))
    flat = composite(work, 0xFFFFFF)
    L = luminance(flat)
    H, W = L.shape
    pct = np.percentile(L, [1, 5, 50, 95, 99])
    hist = np.bincount(np.clip((L * 16).astype(np.int64), 0, 15).ravel(), minlength=16) / L.size
    r, g, b = flat[..., 0] * 255, flat[..., 1] * 255, flat[..., 2] * 255
    rg, yb = r - g, 0.5 * (r + g) - b
    colorfulness = float(np.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2))
    gx, gy = sobel(L)
    mag = np.hypot(gx, gy) / 4
    edge_density = float((mag > 0.1).mean())
    local_std = np.sqrt(np.maximum(box_mean(L * L, 2) - box_mean(L, 2) ** 2, 0))
    texture = float(local_std.mean())
    detail = float(np.abs(L - blur(L, 1.0)).mean())
    t = otsu(L)
    lo, hi = L[L < t], L[L >= t]
    var = float(L.var()) or 1e-9
    between = (lo.size * hi.size / L.size ** 2) * ((hi.mean() if hi.size else 0) - (lo.mean() if lo.size else 0)) ** 2
    separation = float(between / var)
    border = np.concatenate([L[0], L[-1], L[:, 0], L[:, -1]])
    center = L[H // 4:3 * H // 4, W // 4:3 * W // 4]
    border_contrast = float(abs(border.mean() - center.mean()))
    alpha_frac = float((work.a < 0.5).mean())
    partial_alpha = float(((work.a > 0.02) & (work.a < 0.98)).mean())
    pal = median_cut(flat, 6)
    labs = rgb_to_lab(np.array(pal))
    flab = rgb_to_lab(flat.reshape(-1, 3)[::max(1, L.size // 20000)])
    near = np.argmin(((flab[:, None, :] - labs[None, :, :]) ** 2).sum(axis=2), axis=1)
    share = np.bincount(near, minlength=len(pal)) / len(near)
    dominant = sorted(({"color": "#%02x%02x%02x" % tuple(int(round(v * 255)) for v in c), "share": round(float(sh), 3)}
                       for c, sh in zip(pal, share)), key=lambda d: -d["share"])
    grid = [[round(float(L[i * H // 4:(i + 1) * H // 4, j * W // 4:(j + 1) * W // 4].mean()), 3) for j in range(4)]
            for i in range(4)]
    ang = (np.degrees(np.arctan2(-gy, gx)) + 90.0) % 180.0
    ob = np.bincount(np.clip(((ang + 22.5) % 180 / 45).astype(np.int64), 0, 3).ravel(), weights=mag.ravel(), minlength=4)
    ob = ob / max(1e-9, ob.sum())
    unique_colors = int(len(np.unique((np.floor(flat.reshape(-1, 3) * 15.99)).astype(np.int64) @ np.array([256, 16, 1]))))
    metrics = {
        "width": src.width, "height": src.height, "aspect": round(src.width / src.height, 4),
        "mean_luminance": round(float(L.mean()), 4), "luminance_std": round(float(L.std()), 4),
        "percentiles": {k: round(float(v), 4) for k, v in zip(("p1", "p5", "p50", "p95", "p99"), pct)},
        "dynamic_range": round(float(pct[4] - pct[0]), 4), "histogram16": [round(float(v), 4) for v in hist],
        "colorfulness": round(colorfulness, 2), "edge_density": round(edge_density, 4),
        "texture": round(texture, 4), "detail": round(detail, 4), "otsu_threshold": round(t, 4),
        "fg_bg_separation": round(separation, 4), "border_contrast": round(border_contrast, 4),
        "transparent_fraction": round(alpha_frac, 4), "partial_alpha_fraction": round(partial_alpha, 4),
        "dominant_colors": dominant, "local_luminance_4x4": grid,
        "gradient_orientation": {n: round(float(v), 3) for n, v in zip(ORIENT_NAMES, ob)},
        "quantized_colors_4bit": unique_colors,
    }
    return {"metrics": metrics, "recommendations": recommend_settings(metrics)}


def recommend_settings(m: dict) -> list[dict]:
    """Rule-based recommendations. Every item: {key, value, reason}; apply with recommended_params()."""
    rec = []

    def add(key, value, reason):
        rec.append({"key": key, "value": value, "reason": reason})
    logo = m["fg_bg_separation"] > 0.75 and m["quantized_colors_4bit"] < 400 and m["texture"] < 0.08
    colorful = m["colorfulness"] > 35
    transparent = m["transparent_fraction"] > 0.05
    if transparent and logo:
        add("mode", "silhouette", "transparent background and few flat colours → crisp silhouette")
    elif logo and colorful:
        add("mode", "sextant", "flat-colour logo/graphic → sextant blocks with fitted colours keep edges sharp")
    elif logo:
        add("mode", "quadrant", "high-contrast graphic with clear figure/ground → quadrant blocks")
    elif colorful:
        add("mode", "truecolor", f"colourful image (colourfulness {m['colorfulness']:.0f}) → half-block true colour")
    elif m["detail"] > 0.035:
        add("mode", "braille", "fine detail without much colour → Braille gives 8 dots per cell")
    else:
        add("mode", "classic", "smooth monochrome image → density-mapped ASCII reads well")
    cols = 80
    if m["detail"] > 0.05 or m["edge_density"] > 0.25:
        cols = 140
    elif m["detail"] > 0.025:
        cols = 110
    elif m["detail"] < 0.01:
        cols = 60
    if m["aspect"] > 1.6:
        cols = int(cols * 1.25)
    add("cols", min(300, cols), f"detail {m['detail']:.3f}, edge density {m['edge_density']:.2f}, aspect {m['aspect']:.2f}")
    if m["dynamic_range"] < 0.55:
        add("equalize", "clahe", f"narrow luminance range ({m['dynamic_range']:.2f}) → adaptive histogram equalization")
    elif m["dynamic_range"] < 0.8:
        add("contrast", round(min(2.0, 0.9 / max(0.2, m["dynamic_range"])), 2), "moderate range → stretch contrast")
    if m["mean_luminance"] < 0.3:
        add("shadows", 0.4, "dark image → lift shadows")
    elif m["mean_luminance"] > 0.78:
        add("highlights", -0.4, "bright image → recover highlights")
    add("palette", "ascii_high" if m["texture"] > 0.06 else "ascii_extended",
        "textured image → larger glyph set" if m["texture"] > 0.06 else "smooth image → measured 70-glyph ramp")
    add("edge_strength", 1.6 if m["edge_density"] < 0.06 else (0.8 if m["edge_density"] > 0.3 else 1.0),
        f"edge density {m['edge_density']:.2f}")
    add("color", "none" if m["colorfulness"] < 8 else ("ansi256" if m["colorfulness"] < 30 else "original"),
        f"colourfulness {m['colorfulness']:.0f}: " + ("practically grey" if m["colorfulness"] < 8 else
                                                       "moderate → 256 colours suffice" if m["colorfulness"] < 30 else
                                                       "rich colour → keep original colours"))
    smooth = m["texture"] < 0.05 and m["dynamic_range"] > 0.5
    add("dither", "none" if logo else ("floyd" if smooth else "atkinson"),
        "flat graphic: dithering would add noise" if logo else
        "smooth gradients → Floyd–Steinberg avoids banding" if smooth else "textured → Atkinson keeps contrast")
    if transparent:
        add("transparent_bg", True, f"{m['transparent_fraction'] * 100:.0f}% transparent pixels stay empty")
    return rec


def recommended_params(analysis: dict, base: dict | None = None) -> dict:
    p = dict(base or {})
    for r in analysis["recommendations"]:
        p[r["key"]] = r["value"]
    return sanitize_params(p)


# ---------------------------------------------------------------------- reconstruction & metrics
BLOCK_LIKE = set(range(0x2580, 0x25A0)) | set(range(0x1FB00, 0x1FB3C))


def reconstruct(art: Art, p: dict, fw: int = 4, fh: int = 8):
    """Simulated display of the art at fw×fh samples per cell → (rgb H×W×3), vectorised."""
    rows, cols = art.height, art.width
    lod = p.get("light_on_dark", True)
    dfg, dbg = ((0xEBEBEB, 0x0D0D0D) if lod else (0x0D0D0D, 0xF7F7F7))
    emoji = dict(EMOJI_COLORS)
    chars = [list(r) for r in art.chars]
    fgs = [list(r) for r in art.fg]
    bgs = [list(r) for r in art.bg]
    for y in range(rows):  # continuation cells repeat the wide glyph's left half
        for x in range(1, cols):
            if chars[y][x] == "":
                chars[y][x], fgs[y][x], bgs[y][x] = chars[y][x - 1], fgs[y][x - 1], bgs[y][x - 1]
    uniq = sorted({c for r in chars for c in r})
    index = {c: i for i, c in enumerate(uniq)}
    masks, text_max = [], 0.0
    for c in uniq:
        m = glyph_mask(c) if c not in emoji else None
        if c in emoji:
            arr = np.ones((fh, fw))
        elif m is None:
            arr = np.full((fh, fw), 0.2)
        else:
            arr = (np.frombuffer(m, dtype=np.uint8).astype(np.float64).reshape(16, 8) / 255
                   ).reshape(fh, 16 // fh, fw, 8 // fw).mean(axis=(1, 3))
        if c not in emoji and len(c) == 1 and ord(c) not in BLOCK_LIKE and c.strip():
            text_max = max(text_max, float(arr.mean()))
        masks.append(arr)
    norm = 1.0 / text_max if 0 < text_max < 0.8 else 1.0
    for i, c in enumerate(uniq):
        if c not in emoji and len(c) == 1 and ord(c) not in BLOCK_LIKE:
            masks[i] = np.clip(masks[i] * norm, 0, 1)
    M = np.array(masks)
    idx = np.array([[index[c] for c in r] for r in chars], dtype=np.int64)
    fgi = np.array([[(emoji[c] if c in emoji else (f if f is not None else dfg)) for c, f in zip(rc, rf)]
                    for rc, rf in zip(chars, fgs)], dtype=np.int64)
    bgi = np.array([[b if b is not None else dbg for b in r] for r in bgs], dtype=np.int64)

    def rgb(a):
        return np.stack([(a >> 16) & 255, (a >> 8) & 255, a & 255], axis=-1) / 255.0
    F, B = rgb(fgi), rgb(bgi)
    mm = M[idx][..., None]  # rows, cols, fh, fw, 1
    out = mm * F[:, :, None, None, :] + (1 - mm) * B[:, :, None, None, :]
    return out.transpose(0, 2, 1, 3, 4).reshape(rows * fh, cols * fw, 3)


def _ssim(a, b):
    c1, c2 = 0.01 ** 2, 0.03 ** 2
    mu_a, mu_b = blur(a, 1.5), blur(b, 1.5)
    va = blur(a * a, 1.5) - mu_a ** 2
    vb = blur(b * b, 1.5) - mu_b ** 2
    cov = blur(a * b, 1.5) - mu_a * mu_b
    s = ((2 * mu_a * mu_b + c1) * (2 * cov + c2)) / ((mu_a ** 2 + mu_b ** 2 + c1) * (va + vb + c2))
    return float(s.mean())


def quality_metrics(reference_rgb, rec_rgb, size_bytes: int) -> dict:
    """Compare a reconstruction with the reference at the same resolution (both blurred: viewing distance)."""
    ra, rb = blur(reference_rgb, 1.0), blur(rec_rgb, 1.0)
    la, lb = luminance(ra), luminance(rb)
    rmse = float(np.sqrt(((la - lb) ** 2).mean()))
    ssim = _ssim(la, lb)
    ga = np.hypot(*sobel(la)); gb = np.hypot(*sobel(lb))
    sa, sb = ga - ga.mean(), gb - gb.mean()
    den = float(np.sqrt((sa * sa).sum() * (sb * sb).sum()))
    edge = float((sa * sb).sum() / den) if den > 1e-12 else 0.0
    de = float(np.sqrt(((rgb_to_lab(ra) - rgb_to_lab(rb)) ** 2).sum(axis=-1)).mean())
    return {"lum_rmse": round(rmse, 4), "ssim": round(ssim, 4), "edge_corr": round(edge, 4),
            "color_de": round(de, 2), "bytes": int(size_bytes)}


def evaluate(src: RasterImage, art: Art, p: dict) -> dict:
    p = sanitize_params(p)
    work, g = prepare(src, p)
    fw, fh = 4, 8
    rows, cols = art.height, art.width
    ref = resample_area(work, cols * fw, rows * fh)
    bg = np.array([0.05, 0.05, 0.05]) if p["light_on_dark"] else np.array([0.97, 0.97, 0.97])
    ref_rgb = ref.rgb * ref.a[:, :, None] + bg * (1 - ref.a[:, :, None])
    rec = reconstruct(art, p, fw, fh)  # the reference already contains every adjustment
    from .export import to_ansi
    size = len(to_ansi(art, "truecolor").encode("utf-8")) if art.has_color() else len(art.to_text().encode("utf-8"))
    return quality_metrics(ref_rgb, rec, size)


# ---------------------------------------------------------------------- Smart Optimize
COMPAT_SCORE = {"ascii": 1.0, "cp437": 0.9, "unicode": 0.8, "braille": 0.7, "sextant": 0.45, "katakana": 0.4, "emoji": 0.3}

OPT_PRESETS = {
    "detail": {"label": "Maximum detail", "w": {"ssim": .45, "edge": .45, "lum": .1},
               "cands": [{"mode": "sextant", "color": "original"}, {"mode": "braille", "dither": "floyd"},
                         {"mode": "braille", "adaptive": True}, {"mode": "dense"}, {"mode": "quadrant", "color": "original"},
                         {"mode": "typographic"}, {"mode": "truecolor"}]},
    "similarity": {"label": "Maximum visual similarity", "w": {"ssim": .35, "lum": .3, "color": .35},
                   "cands": [{"mode": "truecolor"}, {"mode": "dense"}, {"mode": "mosaic"},
                             {"mode": "sextant", "color": "original"}, {"mode": "quadrant", "color": "original"},
                             {"mode": "ansi256"}, {"mode": "multilayer"}]},
    "readability": {"label": "Maximum text readability", "w": {"ssim": .35, "edge": .3, "compat": .35},
                    "cands": [{"mode": "classic"}, {"mode": "classic", "dither": "floyd"}, {"mode": "typographic"},
                              {"mode": "adaptive"}, {"mode": "hybrid"}, {"mode": "extended"}]},
    "small": {"label": "Minimum output size", "w": {"size": .55, "ssim": .45},
              "cands": [{"mode": "classic", "cols": 60}, {"mode": "blocks", "cols": 60}, {"mode": "braille", "cols": 50},
                        {"mode": "mono", "cols": 60}, {"mode": "binary", "cols": 60}, {"mode": "classic", "cols": 80}]},
    "terminal": {"label": "Terminal compatibility", "w": {"ssim": .45, "compat": .4, "color": .15},
                 "cands": [{"mode": "ansi256", "cols": 80}, {"mode": "ansi16", "cols": 80}, {"mode": "half", "cols": 80},
                           {"mode": "classic", "cols": 80}, {"mode": "mono", "cols": 80}, {"mode": "truecolor", "cols": 80}]},
    "portrait": {"label": "Portrait mode", "w": {"ssim": .5, "edge": .3, "lum": .2},
                 "cands": [{"mode": "braille", "dither": "floyd", "local_contrast": 0.6},
                           {"mode": "typographic", "equalize": "clahe"}, {"mode": "adaptive", "local_contrast": 0.5},
                           {"mode": "truecolor"}, {"mode": "classic", "dither": "floyd", "equalize": "clahe"}]},
    "landscape": {"label": "Landscape mode", "w": {"ssim": .35, "color": .4, "lum": .25},
                  "cands": [{"mode": "truecolor", "cols": 160}, {"mode": "sextant", "color": "original", "cols": 160},
                            {"mode": "mosaic", "cols": 140}, {"mode": "ansi256", "cols": 160}, {"mode": "dense", "cols": 140}]},
    "logo": {"label": "Logo mode", "w": {"edge": .5, "ssim": .5},
             "cands": [{"mode": "silhouette"}, {"mode": "quadrant"}, {"mode": "sextant"}, {"mode": "quadrant", "color": "original"},
                       {"mode": "sextant", "color": "original"}, {"mode": "edge"}, {"mode": "contour"}]},
    "braille": {"label": "Braille mode", "w": {"ssim": .6, "edge": .4},
                "cands": [{"mode": "braille", "threshold": t} for t in (0.35, 0.5, 0.65)]
                + [{"mode": "braille", "adaptive": True}, {"mode": "braille", "dither": "floyd"},
                   {"mode": "braille", "dither": "atkinson"}, {"mode": "braille", "dither": "bayer"}]},
}

METRIC_NOTE = ("Scores are automated approximations of visual quality (luminance RMSE, SSIM, edge correlation, "
               "CIELAB colour error, output size and terminal compatibility); they do not replace looking at the result.")


def optimize(src: RasterImage, base: dict, preset: str = "similarity", top: int = 6, cancel=None, progress=None) -> dict:
    """Render the preset's candidates, score them and return the best ones (with metrics)."""
    require_numpy()
    spec = OPT_PRESETS[preset]
    base = sanitize_params(base)
    results = []
    t0 = time.perf_counter()
    cands = spec["cands"]
    for i, ov in enumerate(cands):
        if cancel is not None and cancel():
            raise RenderCancelled()
        p = dict(base)
        p.update({"dither": "none", "adaptive": False, "color": "none"})
        p.update(ov)
        p = sanitize_params(p)
        art, st = render_image_art(src, p)
        q = evaluate(src, art, p)
        results.append({"params": p, "art": art, "stats": st, "metrics": q})
        if progress:
            progress(i + 1, len(cands))
    max_bytes = max(r["metrics"]["bytes"] for r in results) or 1
    w = spec["w"]
    for r in results:
        q = r["metrics"]
        parts = {"ssim": max(0.0, q["ssim"]), "lum": max(0.0, 1 - q["lum_rmse"] * 2), "edge": (q["edge_corr"] + 1) / 2,
                 "color": max(0.0, 1 - q["color_de"] / 50), "size": 1 - q["bytes"] / max_bytes,
                 "compat": COMPAT_SCORE[MODES[r["params"]["mode"]][5]]}
        r["score"] = round(sum(w.get(k, 0) * v for k, v in parts.items()), 4)
        r["parts"] = {k: round(v, 3) for k, v in parts.items() if k in w}
    results.sort(key=lambda r: -r["score"])
    return {"preset": preset, "label": spec["label"], "note": METRIC_NOTE, "ms": round((time.perf_counter() - t0) * 1000),
            "results": results[:top], "evaluated": len(results)}
