"""Image Studio tests: decoding, security, geometry, glyph mapping, modes, colour, analysis, animation, exports."""
from __future__ import annotations

import io
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).parent))

import image_fixtures as F  # noqa: E402
from leerbox import imgcore as C  # noqa: E402
from leerbox import imgglyphs as G  # noqa: E402
from leerbox import imgmodes as M  # noqa: E402
from leerbox.imganalysis import analyze, optimize, OPT_PRESETS, recommended_params  # noqa: E402
from leerbox import imganim as A  # noqa: E402
from leerbox.export import FORMATS, ExportSettings, export_bytes, to_ansi  # noqa: E402


def raster(name):
    w, h, data = F.ALL[name]()
    return C.RasterImage.from_rgba_bytes(w, h, data)


def png_bytes(im, fmt="PNG", **kw):
    buf = io.BytesIO()
    im.save(buf, fmt, **kw)
    return buf.getvalue()


# ---------------------------------------------------------------- decoding
@pytest.mark.parametrize("fmt,kw", [("PNG", {}), ("JPEG", {"quality": 95}), ("WEBP", {"lossless": True}), ("BMP", {}),
                                    ("GIF", {}), ("TIFF", {"compression": "tiff_lzw"}), ("ICO", {"sizes": [(64, 64)]}),
                                    ("AVIF", {"quality": 90})])
def test_decode_formats(fmt, kw):
    caps = C.decoder_capabilities()["formats"]
    if not caps.get(fmt if fmt != "WEBP" else "WEBP"):
        pytest.skip(f"{fmt} decoder not available in this Pillow build")
    im = Image.new("RGB", (64, 48), (200, 30, 30))
    ImageDraw.Draw(im).rectangle([10, 10, 40, 30], fill=(20, 200, 40))
    data = png_bytes(im if fmt != "ICO" else im.resize((64, 64)), fmt, **kw)
    assert C.sniff_format(data) == fmt
    img = C.decode_image(data, "x")
    assert img.width > 0 and img.height > 0
    px = img.rgb[20, 20] if fmt != "ICO" else img.rgb[25, 25]
    assert px[1] > 0.6 and px[0] < 0.3  # green rectangle survived decoding


def test_exif_orientation_applied():
    im = Image.new("RGB", (40, 20), (255, 0, 0))
    ImageDraw.Draw(im).rectangle([0, 0, 9, 19], fill=(0, 0, 255))
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90° CW on display
    data = png_bytes(im, "JPEG", quality=95, exif=exif.tobytes())
    img = C.decode_image(data)
    assert (img.width, img.height) == (20, 40)
    assert img.rgb[2, 10][2] > 0.6  # the blue band is now at the top
    assert img.info["exif_oriented"]


def test_transparency_preserved():
    w, h, data = F.transparent()
    data = png_bytes(Image.frombytes("RGBA", (w, h), data))
    img = C.decode_image(data)
    assert img.a[0, 0] == 0 and img.a[h // 2, w // 2] == 1
    art, _ = M.render_image_art(img, {"mode": "braille", "cols": 30, "transparent_bg": True})
    assert art.chars[0][0] == "\u2800"


def test_decompression_bomb_and_limits(monkeypatch):
    monkeypatch.setattr(C, "MAX_SOURCE_PIXELS", 1000)
    data = png_bytes(Image.new("L", (100, 100)))
    with pytest.raises(C.ImageDecodeError):
        C.decode_image(data)


@pytest.mark.parametrize("data", [b"", b"\x89PNG\r\n\x1a\nbroken", b"GIF89a\x01", b"not an image at all", b"\xff\xd8\xff\xe0garbage"])
def test_malformed_images_rejected(data):
    with pytest.raises(C.ImageDecodeError):
        C.decode_image(data)


def test_heif_reports_missing_decoder():
    data = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 40
    assert C.sniff_format(data) == "HEIF"
    with pytest.raises(C.ImageDecodeError, match="pillow-heif|HEIF|malformed"):
        C.decode_image(data)


@pytest.mark.parametrize("svg", [
    b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>',
    b'<!DOCTYPE svg [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;">]><svg>&b;</svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><image href="https://example.com/x.png"/></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><foreignObject><div/></foreignObject></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><rect fill="url(https://x/y#a)"/></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><style>@import url(x.css);</style></svg>',
])
def test_unsafe_svg_rejected(svg):
    with pytest.raises(C.ImageDecodeError, match="unsafe"):
        C.decode_image(svg)


def test_safe_svg_rasterized():
    svg = (b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50" viewBox="0 0 100 50">'
           b'<rect x="0" y="0" width="50" height="50" fill="#ff0000"/><circle cx="75" cy="25" r="20" fill="blue"/>'
           b'<path d="M0 0 L100 50" stroke="black" stroke-width="2" fill="none"/></svg>')
    img = C.decode_image(svg)
    h, w = img.a.shape
    assert img.rgb[h // 4, w // 8][0] > 0.9 and img.rgb[h // 2, int(w * 0.75)][2] > 0.9
    assert img.a[2, int(w * 0.98)] == 0  # outside every shape → transparent


def test_animated_gif_frames():
    frames = [Image.new("RGB", (30, 20), (i * 50, 0, 0)) for i in range(4)]
    data = png_bytes(frames[0], "GIF", save_all=True, append_images=frames[1:], duration=[50, 60, 70, 80], loop=0)
    fr, durs, info = C.decode_frames(data)
    assert len(fr) == 4 and durs == [50, 60, 70, 80] and info["frames"] == 4
    assert fr[3].rgb[5, 5][0] > fr[1].rgb[5, 5][0]
    arts, d2, st = A.convert_animation(fr, durs, {"mode": "classic", "cols": 20}, step=2)
    assert len(arts) == 2 and d2 == [110, 150]  # skipped frames' time is kept
    arts, d3, _ = A.convert_animation(fr, durs, {"mode": "classic", "cols": 20}, fps=10)
    assert d3 == [100] * 4


# ---------------------------------------------------------------- geometry & processing
def test_aspect_ratio_compensation():
    img = C.RasterImage(np.zeros((100, 100, 3)), np.ones((100, 100)))
    g = M.plan_grid(100, 100, M.sanitize_params({"cols": 80, "cell_aspect": 0.5}))
    assert (g["cols"], g["rows"]) == (80, 40)  # square image, cells twice as tall as wide
    g = M.plan_grid(200, 100, M.sanitize_params({"cols": 80, "cell_aspect": 0.5}))
    assert g["rows"] == 20
    g = M.plan_grid(100, 100, M.sanitize_params({"cols": 80, "mode": "braille"}))
    assert (g["sw"], g["sh"]) == (160, 160)  # braille samples are square again
    g = M.plan_grid(100, 100, M.sanitize_params({"cols": 80, "mode": "emoji"}))
    assert g["gcols"] == 40 and g["rows"] == 40  # double-width emoji cells
    g = M.plan_grid(100, 100, M.sanitize_params({"cols": 200, "rows": 30, "lock_aspect": True}))
    assert g["rows"] == 30 and g["cols"] == 60  # automatic fit inside the box
    art, _ = M.render_image_art(img, {"cols": 80})
    assert (art.width, art.height) == (80, 40)


def test_transforms():
    img = raster("portrait")
    r4 = img
    for _ in range(4):
        r4 = C.rotate90(r4, 90)
    assert np.array_equal(r4.rgb, img.rgb)
    r = C.rotate90(img, 90)
    assert (r.width, r.height) == (img.height, img.width)
    assert np.array_equal(r.rgb[0, -1], img.rgb[0, 0])  # top-left moves to top-right
    f = C.flip(C.flip(img, True, True), True, True)
    assert np.array_equal(f.rgb, img.rgb)
    c = C.crop(img, 0.25, 0.25, 0.75, 0.75)
    assert c.width == img.width // 2
    rf = C.rotate_free(img, 30)
    assert rf.width > img.width and rf.a[0, 0] == 0
    p = C.pad(img, 3, 4, 5, 6)
    assert (p.width, p.height) == (img.width + 8, img.height + 10) and p.a[0, 0] == 0


def test_resample_area_preserves_mean():
    img = raster("large_photo")
    small = C.resample_area(img, 97, 61)
    assert abs(small.rgb.mean() - img.rgb.mean()) < 0.003


def test_adjustments_non_destructive_and_effective():
    img = raster("portrait")
    before = img.rgb.copy()
    for k, v in [("brightness", 0.3), ("contrast", 2.0), ("exposure", 1.0), ("gamma", 2.0), ("saturation", 0.0),
                 ("vibrance", 0.8), ("hue", 90), ("sharpness", 2), ("blur", 2), ("denoise", 1), ("black", 0.3),
                 ("white", 0.7), ("highlights", -1), ("shadows", 1), ("posterize", 4), ("grayscale", True),
                 ("invert", True), ("equalize", "clahe"), ("equalize", "global"), ("local_contrast", 1.0)]:
        out = C.adjust(img, {k: v})
        assert not np.allclose(out.rgb, img.rgb), k
        assert out.rgb.min() >= 0 and out.rgb.max() <= 1, k
    assert np.array_equal(img.rgb, before)
    g = C.adjust(img, {"saturation": 0.0})
    assert np.allclose(g.rgb[..., 0], g.rgb[..., 1], atol=1e-9)
    inv = C.adjust(img, {"invert": True})
    assert np.allclose(inv.rgb, 1 - img.rgb)
    p = C.adjust(img, {"posterize": 3})
    assert len(np.unique(np.round(p.rgb, 6))) <= 3


def test_background_removal():
    out = C.remove_background(raster("logo"), 0.1)
    assert out.a[0, 0] == 0 and out.a[50, int(160 * 0.68)] == 1


def test_edge_detection():
    L = np.zeros((40, 40)); L[:, 20:] = 1.0
    gx, gy = C.sobel(L)
    assert np.abs(gx).max() > 0 and np.abs(gy).max() == 0
    e, _, _ = C.canny(L, 0.05, 0.1)
    cols = np.where(e.any(axis=0))[0]
    assert set(cols) <= {18, 19, 20, 21} and e[:, 19:21].any()
    img = C.RasterImage(np.repeat(L[:, :, None], 3, axis=2), np.ones((40, 40)))
    art, _ = M.render_image_art(img, {"mode": "edge", "cols": 20})
    assert "|" in "".join("".join(r) for r in art.chars) and "-" not in "".join("".join(r) for r in art.chars)
    Lh = L.T
    img = C.RasterImage(np.repeat(Lh[:, :, None], 3, axis=2), np.ones((40, 40)))
    art, _ = M.render_image_art(img, {"mode": "edge", "cols": 20})
    assert "-" in "".join("".join(r) for r in art.chars)


def test_dithering_preserves_average():
    v = np.full((40, 40), 0.3)
    for method in ("floyd", "atkinson", "bayer"):
        q = M.quantize_levels(v, [0.0, 1.0], method)
        # Atkinson diffuses only 6/8 of the error by design, so it may drift darker
        assert abs(q.mean() - 0.3) < (0.08 if method == "atkinson" else 0.03), method
    assert M.quantize_levels(v, [0.0, 1.0], "none").mean() == 0


def test_otsu_and_equalize():
    vals = np.concatenate([np.full(500, 0.2), np.full(500, 0.8)])
    t = C.otsu(vals)
    assert 0.2 < t < 0.8
    L = np.linspace(0.4, 0.6, 400).reshape(20, 20)
    e = C.equalize(L)
    assert e.max() - e.min() > 0.9


# ---------------------------------------------------------------- glyphs & palettes
def test_density_ordering_is_measured():
    order = G.sort_by_density(list(" .:-=+*#%@"))
    assert order[0] == " " and order[1] == "."
    sums = [G.glyph_coverage_sum(c) for c in order]
    assert sums == sorted(sums)
    assert G.glyph_coverage_sum("@") > G.glyph_coverage_sum("+") > G.glyph_coverage_sum(".")
    assert G.glyph_coverage_sum("█") == 255 * 128


def test_braille_bit_mapping():
    # ISO 11548-1: dots 1-2-3 left column, 4-5-6 right column, 7 bottom-left, 8 bottom-right
    assert G.BRAILLE_DOTS == [(0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2), (0, 3), (1, 3)]
    for bit, (dx, dy) in enumerate(G.BRAILLE_DOTS):
        rgb = np.zeros((4, 16, 3)); a = np.ones((4, 16))  # 8 cells of 2×4 dots; dot only in cell 0
        rgb[dy, dx] = 1.0
        img = C.RasterImage(rgb, a)
        art, _ = M.render_image_art(img, {"mode": "braille", "cols": 8, "rows": 1, "lock_aspect": False, "cell_aspect": 0.5})
        assert ord(art.chars[0][0]) == 0x2800 + (1 << bit), bit
    m = G.glyph_mask("\u28ff")
    assert m is not None and sum(m) > 0


def test_unicode_block_mapping():
    assert G.QUADRANT_CHARS[1] == "▘" and G.QUADRANT_CHARS[2] == "▝" and G.QUADRANT_CHARS[4] == "▖" and G.QUADRANT_CHARS[8] == "▗"
    assert G.sextant_char(0) == " " and G.sextant_char(63) == "█" and G.sextant_char(21) == "▌" and G.sextant_char(42) == "▐"
    seen = {G.sextant_char(b) for b in range(64)}
    assert len(seen) == 64
    assert G.sextant_char(1) == "\U0001FB00" and G.sextant_char(62) == "\U0001FB3B"
    # sextant masks agree with the bit pattern (bit0 = top-left)
    m = np.frombuffer(G.glyph_mask(G.sextant_char(1)), dtype=np.uint8).reshape(16, 8)
    assert m[0, 0] == 255 and m[15, 7] == 0
    # two-colour optimisation: a left/right split cell becomes ▌ with exact colours
    rgb = np.zeros((3, 16, 3)); rgb[:, 0::2] = [1, 0, 0]; rgb[:, 1::2] = [0, 0, 1]
    art, _ = M.render_image_art(C.RasterImage(rgb, np.ones((3, 16))),
                                {"mode": "sextant", "color": "original", "cols": 8, "rows": 1, "lock_aspect": False})
    assert art.chars[0][0] in ("▌", "▐")
    assert {art.fg[0][0], art.bg[0][0]} == {0xFF0000, 0x0000FF}


def test_palettes_library_and_io():
    for key in G.PALETTES:
        assert G.resolve_palette(key), key
    assert G.resolve_palette("ascii_basic", reverse=True)[0] == "@"
    custom = G.resolve_palette("@ .")
    assert custom == [" ", ".", "@"]
    txt = G.export_palettes([{"name": "Mine", "chars": "01\x1b"}])
    back = G.import_palettes(txt)
    assert back == [{"name": "Mine", "chars": "01"}]
    with pytest.raises(ValueError):
        G.import_palettes("{}")
    from leerbox.fontdb import FontManager
    fm = FontManager()
    pal = G.palette_from_figlet(fm.font("fig:standard"))
    assert "_" in pal and "|" in pal and pal[0] == " "


def test_glyph_matcher_exact_and_cached():
    chars = G.resolve_palette("ascii_high")
    m = G.GlyphMatcher(chars, 4, 8, 24)
    full = np.ones((3, 32))
    idx = m.match(full)
    assert len(set(idx)) == 1 and m.chars[idx[0]] != " "
    assert m.chars[m.match(np.zeros((1, 32)))[0]] == " "
    # a vertical bar of ink should match a vertical glyph
    bar = np.zeros((8, 4)); bar[:, 1:3] = 1
    got = m.chars[m.match(bar.reshape(1, 32))[0]]
    assert got in "|!lI1[]"


# ---------------------------------------------------------------- modes on every representative image
@pytest.mark.parametrize("name", list(F.ALL))
def test_all_modes_on_representative_images(name):
    img = raster(name)
    for mode in M.MODES:
        art, st = M.render_image_art(img, {"mode": mode, "cols": 48})
        assert art.height >= 1 and art.width == (48 if M.MODES[mode][4] == 1 else 48 // 2 * 2), mode
        assert st["mode"] == mode
        ink = sum(1 for r in art.chars for c in r if c not in (" ", "", "\u2800"))
        if name not in ("low_res",) or mode not in ("edge", "line", "contour"):
            assert ink > 0 or mode in ("edge", "line", "contour", "silhouette"), (name, mode)


def test_modes_are_distinct():
    img = raster("portrait")
    outs = {m: M.render_image_art(img, {"mode": m, "cols": 40})[0] for m in M.MODES}
    sigs = {m: (tuple("".join(r) for r in a.chars), tuple(tuple(r) for r in a.fg), tuple(tuple(r) for r in a.bg))
            for m, a in outs.items()}
    assert len(set(sigs.values())) == len(sigs)


def test_color_engine_and_ansi():
    img = raster("landscape")
    for c in M.P_CHOICES["color"]:
        art, _ = M.render_image_art(img, {"mode": "classic", "color": c, "cols": 40})
        if c == "none":
            assert not art.has_color()
        else:
            assert art.has_color(), c
    art, _ = M.render_image_art(img, {"mode": "ansi16", "cols": 40})
    used = {v for r in art.fg for v in r if v is not None} | {v for r in art.bg for v in r if v is not None}
    assert used <= set(M.ANSI16_RGB)
    art, _ = M.render_image_art(img, {"mode": "ansi256", "cols": 40})
    xt = set(M.xterm256())
    assert {v for r in art.fg for v in r if v is not None} <= xt
    s = to_ansi(art, "256")
    assert re.fullmatch(r"(?:[^\x1b]|\x1b\[[0-9;]*m)*", s)
    assert all(line.endswith("\x1b[0m") for line in s.splitlines() if "\x1b" in line)
    art, _ = M.render_image_art(img, {"mode": "grayscale", "cols": 40})
    assert all(((v >> 16) & 255) == (v & 255) for r in art.fg for v in r if v is not None)


def test_custom_words_and_rtl():
    img = raster("logo")
    art, _ = M.render_image_art(img, {"mode": "words", "text": "LeerBox", "cols": 60, "light_on_dark": False})
    txt = "".join("".join(r) for r in art.chars)
    assert "LeerBox" in txt
    art, _ = M.render_image_art(img, {"mode": "words", "text": "Leer Box Art", "text_mode": "words", "cols": 60,
                                      "light_on_dark": False})
    assert "Leer" in "".join("".join(r) for r in art.chars)
    art, _ = M.render_image_art(img, {"mode": "words", "text": "سلام", "cols": 60, "light_on_dark": False})
    txt = "".join("".join(r) for r in art.chars)
    assert any(0xFE70 <= ord(c) <= 0xFEFF for c in txt)  # shaped presentation forms
    art, _ = M.render_image_art(img, {"mode": "words", "text": "世界", "cols": 60, "light_on_dark": False})
    assert any(r[x] == "" for r in art.chars for x in range(len(r)))  # wide chars use continuation cells


def test_cost_estimate_for_extreme_resolution():
    est = M.estimate_cost(4000, 3000, M.sanitize_params({"cols": 1000, "mode": "sextant", "color": "original", "rows": 1000,
                                                       "lock_aspect": False}))
    assert est["heavy"] and est["samples"] == 2000 * 3000
    small = M.estimate_cost(400, 300, M.sanitize_params({"cols": 80}))
    assert not small["heavy"] and small["est_ms"] < 500


# ---------------------------------------------------------------- analysis & optimisation
def test_analysis_and_recommendations():
    a = analyze(raster("logo"))
    m = a["metrics"]
    assert m["fg_bg_separation"] > 0.5 and m["colorfulness"] > 20 and len(m["dominant_colors"]) >= 3
    rec = {r["key"]: r["value"] for r in a["recommendations"]}
    assert rec["mode"] in ("sextant", "quadrant") and all(r["reason"] for r in a["recommendations"])
    p = recommended_params(a, {"cols": 50})
    assert p["mode"] == rec["mode"]
    t = analyze(raster("transparent"))
    assert t["metrics"]["transparent_fraction"] > 0.3
    d = analyze(raster("drawing"))
    assert d["metrics"]["colorfulness"] < 5


@pytest.mark.parametrize("preset", list(OPT_PRESETS))
def test_optimize_presets(preset):
    res = optimize(raster("portrait"), {"cols": 40}, preset, top=3)
    assert 1 <= len(res["results"]) <= 3 and "approximations" in res["note"]
    scores = [r["score"] for r in res["results"]]
    assert scores == sorted(scores, reverse=True)
    for r in res["results"]:
        assert 0 <= r["metrics"]["ssim"] <= 1.0001


def test_similarity_metric_prefers_colour_blocks():
    res = optimize(raster("landscape"), {"cols": 40}, "similarity", top=7)
    best = res["results"][0]["params"]["mode"]
    assert best in ("dense", "sextant", "truecolor", "quadrant", "mosaic")


# ---------------------------------------------------------------- exports & projects
def test_image_art_exports_all_formats():
    art, _ = M.render_image_art(raster("portrait"), {"mode": "sextant", "color": "original", "cols": 30})
    s = ExportSettings(letter_spacing=0.1, line_height=1.0)
    for fmt in FORMATS:
        data = export_bytes(art, fmt, s)
        assert data, fmt
        if fmt in ("png", "jpeg", "webp", "bmp"):
            Image.open(io.BytesIO(data)).verify()
    txt = export_bytes(art, "txt").decode("utf-8")
    assert "\U0001FB00" <= max(txt) or any(0x1FB00 <= ord(c) <= 0x1FB3B or c in "▌▐█" for c in txt)
    svg = export_bytes(art, "svg").decode("utf-8")
    import xml.dom.minidom
    xml.dom.minidom.parseString(svg)
    assert "<rect" in svg  # sextants drawn as exact rectangles
    html_ = export_bytes(art, "html", s).decode("utf-8")
    assert "letter-spacing" in html_


def test_animation_exports():
    fr = [raster("portrait"), C.adjust(raster("portrait"), {"invert": True})]
    arts, durs, _ = A.convert_animation(fr, [100, 100], {"mode": "braille", "cols": 24})
    html_ = A.to_animated_html(arts, durs)
    assert "Content-Security-Policy" in html_ and "<script" in html_ and "http" not in html_.split("<body>")[1]
    gif = A.to_gif(arts, durs)
    with Image.open(io.BytesIO(gif)) as im:
        assert im.n_frames == 2
    z = zipfile.ZipFile(io.BytesIO(A.to_frame_zip(arts, "txt", durs=durs)))
    assert sorted(z.namelist()) == ["frame_0001.txt", "frame_0002.txt", "frames.json"]
    sh = A.to_ansi_script(arts, durs, "bash")
    escs = set(re.findall(r"\\e\[[0-9;?]*[A-Za-z]", sh))
    assert escs <= {"\\e[H", "\\e[2J", "\\e[?25l", "\\e[?25h", "\\e[0m"} | {e for e in escs if e.endswith("m")}
    ps = A.to_ansi_script(arts, durs, "powershell")
    assert "$frames" in ps and "Start-Sleep" in ps


def test_typographic_composition_and_comparison():
    comp = A.compose_typographic(raster("portrait"), {"text": "LeerBox", "color": "original"}, 10, "size")
    assert comp["kind"] == "typographic-composition" and comp["runs"]
    assert {r["ch"] for r in comp["runs"]} <= set("LeerBox")
    png = A.composition_png(comp)
    Image.open(io.BytesIO(png)).verify()
    import xml.dom.minidom
    xml.dom.minidom.parseString(A.composition_svg(comp))
    art, _ = M.render_image_art(raster("portrait"), {"cols": 30})
    cmp_ = Image.open(io.BytesIO(A.comparison_png(raster("portrait"), art)))
    assert cmp_.width > cmp_.height


def test_image_project_roundtrip_and_validation():
    from leerbox.project import ProjectError
    data = png_bytes(Image.new("RGB", (8, 8)))
    pj = A.make_image_project({"mode": "mosaic", "cols": 66, "evil": 1}, data, "a.png")
    back = A.parse_image_project(pj)
    assert back["params"]["mode"] == "mosaic" and back["params"]["cols"] == 66 and back["image"] == data
    assert "evil" not in back["params"]
    with pytest.raises(ProjectError):
        A.parse_image_project('{"format":"leerbox-image-project","image":{"data":"!!!"}}')
    with pytest.raises(ProjectError):
        A.parse_image_project("[]")
    p = M.sanitize_params({"cols": "abc", "angle": float("nan"), "palette": "\x1b[31m", "mode": "../etc"})
    assert p["cols"] == 100 and p["angle"] == 0.0 and "\x1b" not in p["palette"] and p["mode"] == "classic"


def test_batch_convert_reports_failures():
    good = png_bytes(Image.new("RGB", (20, 10), (255, 255, 255)))
    z, rep = A.batch_convert([("a.png", good), ("bad.png", b"nope")], {"cols": 20}, "txt")
    assert [r["ok"] for r in rep] == [True, False]
    names = zipfile.ZipFile(io.BytesIO(z)).namelist()
    assert "001_a.txt" in names and "batch_report.json" in names


def test_cli_image_paths(tmp_path):
    p = tmp_path / "in.png"
    w, h, data = F.logo()
    Image.frombytes("RGBA", (w, h), data).save(p)
    run = lambda *a: subprocess.run([sys.executable, "-m", "leerbox", *a], cwd=ROOT / "src", capture_output=True,  # noqa: E731
                                    text=True, encoding="utf-8", timeout=120)
    r = run("--image", str(p), "--image-mode", "quadrant", "--cols", "30")
    assert r.returncode == 0 and "▀" in r.stdout or "▄" in r.stdout or "█" in r.stdout
    r = run("--image", str(p), "--analyze")
    assert json.loads(r.stdout)["recommendations"]
    out = tmp_path / "o.png"
    r = run("--image", str(p), "--set", "color=original", "--set", "mode=sextant", "--format", "png", "-o", str(out))
    assert r.returncode == 0 and out.stat().st_size > 100


# ---------------------------------------------------------------- offline & cross-edition
def test_image_modules_have_no_network_or_eval():
    for name in ("imgcore", "imgglyphs", "imgmodes", "imganalysis", "imganim"):
        src = (ROOT / "src" / "leerbox" / f"{name}.py").read_text(encoding="utf-8")
        assert not re.search(r"^\s*(import|from)\s+(urllib|http|socket|requests|ftplib|smtplib)", src, re.M), name
        assert not re.search(r"\b(eval|exec)\s*\(", src), name
    for name in ("72_imgcore", "73_imgglyphs", "74_imgmodes", "75_imganalysis", "76_imganim"):
        src = (ROOT / "web" / "src" / "engine" / f"{name}.js").read_text(encoding="utf-8")
        assert not re.search(r"\b(fetch|XMLHttpRequest|WebSocket|eval)\s*\(|new\s+Function", src), name


def test_js_image_engine_matches_python():
    r = subprocess.run(["node", str(ROOT / "tests" / "js" / "image_tests.js")], capture_output=True, text=True,
                       encoding="utf-8", timeout=600)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-2000:]
    assert "206/206" in r.stdout
