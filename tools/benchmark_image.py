"""Image Studio benchmarks (Python + JavaScript). Writes dist/perf_image.json.

Usage: python tools/benchmark_image.py
"""
from __future__ import annotations

import io
import json
import platform
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import numpy as np  # noqa: E402
import image_fixtures as F  # noqa: E402
from leerbox.imgcore import RasterImage, decode_image  # noqa: E402
from leerbox.imgmodes import MODES, render_image_art, sanitize_params, estimate_cost  # noqa: E402
from leerbox.imganalysis import analyze, optimize  # noqa: E402
from leerbox.imgglyphs import GlyphMatcher, resolve_palette  # noqa: E402


def t(fn, n=1):
    best = float("inf")
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - t0)
    return round(best * 1000, 1)


def main():
    w, h, data = F.large_photo()
    img = RasterImage.from_rgba_bytes(w, h, data)
    from PIL import Image
    buf = io.BytesIO()
    Image.frombytes("RGBA", (w, h), data).save(buf, "PNG")
    png = buf.getvalue()
    big = Image.frombytes("RGBA", (w, h), data).resize((4000, 2667))
    b2 = io.BytesIO()
    big.convert("RGB").save(b2, "JPEG", quality=90)
    res = {"python": {}, "env": {"python": platform.python_version(), "numpy": np.__version__, "cpu": platform.processor()}}
    P = res["python"]
    P["decode_png_1200x800_ms"] = t(lambda: decode_image(png), 3)
    P["decode_jpeg_4000x2667_ms"] = t(lambda: decode_image(b2.getvalue()), 2)
    fresh = lambda: RasterImage(img.rgb, img.a, {})  # noqa: E731 — no cached geometry: cold render
    P["modes_80_cols_ms"] = {m: t(lambda m=m: render_image_art(fresh(), {"mode": m, "cols": 80}), 2) for m in MODES}
    warm = fresh()
    render_image_art(warm, {"mode": "classic", "cols": 80})
    P["rerender_after_adjustment_classic_80_ms"] = t(lambda: render_image_art(warm, {"mode": "classic", "cols": 80, "contrast": 1.3}), 3)
    P["modes_200_cols_ms"] = {m: t(lambda m=m: render_image_art(fresh(), {"mode": m, "cols": 200})) for m in
                              ("classic", "braille", "sextant", "truecolor", "typographic", "dense", "mosaic", "ansi16")}
    P["braille_floyd_500_cols_ms"] = t(lambda: render_image_art(fresh(), {"mode": "braille", "cols": 500, "dither": "floyd"}))
    P["classic_1000_cols_ms"] = t(lambda: render_image_art(fresh(), {"mode": "classic", "cols": 1000}))
    P["typographic_300_cols_ms"] = t(lambda: render_image_art(fresh(), {"mode": "typographic", "cols": 300}))
    est = estimate_cost(w, h, sanitize_params({"mode": "classic", "cols": 1000}))
    P["classic_1000_cols_estimate_ms"] = est["est_ms"]
    P["analyze_ms"] = t(lambda: analyze(img), 2)
    P["optimize_similarity_80_cols_ms"] = t(lambda: optimize(img, {"cols": 80}, "similarity"))
    # glyph matching throughput (the most compute-heavy kernel; candidate for GPU acceleration)
    m = GlyphMatcher(resolve_palette("ascii_high"), 4, 8, 24)
    rng = np.random.default_rng(1)
    cells = rng.random((200_000, 32))
    t0 = time.perf_counter()
    m.match(cells)
    dt = time.perf_counter() - t0
    P["glyph_match_200k_random_cells_ms"] = round(dt * 1000, 1)
    P["glyph_match_comparisons_per_s"] = int(200_000 * 24 / dt)
    js = subprocess.run(["node", str(ROOT / "tools" / "benchmark_image.js")], capture_output=True, text=True, encoding="utf-8", timeout=900)
    try:
        res["javascript"] = json.loads(js.stdout)
    except ValueError:
        res["javascript"] = {"error": js.stdout[-500:] + js.stderr[-500:]}
    try:
        import cupy  # noqa: F401
        res["gpu"] = {"cupy": "installed"}
    except ImportError:
        res["gpu"] = {"cupy": "not installed", "note": "CUDA path not evaluated at runtime; see PERFORMANCE_REPORT.md"}
    out = ROOT / "dist" / "perf_image.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
