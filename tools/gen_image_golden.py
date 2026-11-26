"""Generate tests/golden/image_cross_edition.json: Python Image Studio output for the JS cross-edition test.

Each case stores the raw RGBA test image, the parameters and the Python result (characters and colours).
The JS suite renders the same pixels with the same parameters and compares cell by cell.
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from leerbox.imgcore import RasterImage  # noqa: E402
from leerbox.imgmodes import MODES, render_image_art  # noqa: E402
from leerbox.imganalysis import analyze  # noqa: E402
import image_fixtures as F  # noqa: E402

OUT = ROOT / "tests" / "golden" / "image_cross_edition.json"
IMAGES = ["portrait", "logo", "transparent", "drawing", "landscape", "low_res"]
EXTRA = [  # parameter variations exercising adjustments, geometry, dithering and colour engines
    ("portrait", {"mode": "classic", "dither": "floyd", "equalize": "clahe"}),
    ("portrait", {"mode": "classic", "dither": "atkinson", "light_on_dark": False, "luma": "perceptual"}),
    ("portrait", {"mode": "braille", "dither": "bayer", "color": "original"}),
    ("portrait", {"mode": "braille", "adaptive": True, "invert": True}),
    ("portrait", {"mode": "typographic", "color": "ansi256", "color_target": "bg"}),
    ("portrait", {"mode": "half", "color": "gradient", "saturation": 1.6, "hue": 40, "vibrance": 0.4}),
    ("portrait", {"mode": "quadrant", "color": "dominant", "dominant_k": 5}),
    ("portrait", {"mode": "classic", "rotate": 90, "flip_h": True, "crop_x0": 0.1, "crop_y1": 0.9}),
    ("portrait", {"mode": "classic", "angle": 12, "pad": 0.05, "exposure": 0.5, "gamma": 1.4}),
    ("portrait", {"mode": "edge", "edge_method": "canny", "edge_threshold": 0.15}),
    ("portrait", {"mode": "edge", "edge_method": "dog"}),
    ("portrait", {"mode": "classic", "blur": 1.5, "sharpness": 1.0, "denoise": 0.5, "posterize": 6}),
    ("portrait", {"mode": "classic", "shadows": 0.5, "highlights": -0.5, "black": 0.1, "white": 0.9, "local_contrast": 0.7}),
    ("logo", {"mode": "silhouette", "remove_bg": 0.2}),
    ("logo", {"mode": "sextant", "color": "custom", "colors": "#000000,#ffffff,#ff0000,#0000ff,#ffff00"}),
    ("logo", {"mode": "classic", "target_aspect": 1.0, "fit": "contain"}),
    ("logo", {"mode": "classic", "target_aspect": 1.0, "fit": "cover"}),
    ("logo", {"mode": "words", "text": "LeerBox Studio", "text_mode": "words", "light_on_dark": False}),
    ("logo", {"mode": "words", "text": "مرحبا بالعالم", "text_mode": "flow", "light_on_dark": False}),
    ("logo", {"mode": "words", "text": "Hello 世界", "text_mode": "fill"}),
    ("landscape", {"mode": "ansi16", "dither": "atkinson"}),
    ("landscape", {"mode": "grayscale", "dither": "none"}),
    ("landscape", {"mode": "pixel", "color": "original", "cols": 60}),
    ("landscape", {"mode": "contour", "color": "gradient", "levels": 8}),
    ("transparent", {"mode": "half", "color": "original"}),
    ("transparent", {"mode": "braille", "color": "original", "transparent_bg": True}),
]


def art_record(art):
    chars = ["\u0000".join(r) for r in art.chars]
    fg = [[-1 if c is None else c for c in r] for r in art.fg]
    bg = [[-1 if c is None else c for c in r] for r in art.bg]
    return {"chars": chars, "fg": fg, "bg": bg}


def main() -> None:
    images = {}
    for name in set(IMAGES) | {e[0] for e in EXTRA}:
        w, h, data = F.ALL[name]()
        images[name] = {"w": w, "h": h, "rgba": base64.b64encode(data).decode("ascii")}
    cases = []
    for name in IMAGES:
        w, h, data = F.ALL[name]()
        img = RasterImage.from_rgba_bytes(w, h, data)
        for mode in MODES:
            p = {"mode": mode, "cols": 40}
            art, _ = render_image_art(img, p)
            cases.append({"image": name, "params": p, **art_record(art)})
    for name, ov in EXTRA:
        w, h, data = F.ALL[name]()
        img = RasterImage.from_rgba_bytes(w, h, data)
        p = {"cols": 48, **ov}
        art, _ = render_image_art(img, p)
        cases.append({"image": name, "params": p, **art_record(art)})
    analyses = {}
    for name in ("portrait", "logo", "transparent", "landscape"):
        w, h, data = F.ALL[name]()
        a = analyze(RasterImage.from_rgba_bytes(w, h, data))
        analyses[name] = {"recommendations": a["recommendations"],
                          "metrics": {k: a["metrics"][k] for k in ("mean_luminance", "dynamic_range", "colorfulness",
                                                                    "edge_density", "otsu_threshold", "transparent_fraction")}}
    OUT.write_text(json.dumps({"images": images, "cases": cases, "analyses": analyses}, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {OUT.name}: {len(cases)} cases, {OUT.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()


def codec_fixtures() -> None:
    """GIF and TIFF files written by Pillow, plus Pillow's decoded pixels, for the JS codec tests."""
    from PIL import Image, ImageDraw
    g = ROOT / "tests" / "golden"
    frames = []
    for i in range(5):
        im = Image.new("RGBA", (48, 32), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rectangle([2 + i * 6, 4, 14 + i * 6, 20], fill=(250, 200, 30, 255))
        d.ellipse([20, 10 + i * 2, 40, 28], fill=(30, 120, 240, 255))
        frames.append(im)
    frames[0].save(g / "anim_test.gif", save_all=True, append_images=frames[1:], duration=[80, 90, 100, 110, 120],
                   loop=0, disposal=2, transparency=0, interlace=True)
    ref = []
    with Image.open(g / "anim_test.gif") as im:
        for i in range(im.n_frames):
            im.seek(i)
            ref.append(base64.b64encode(im.convert("RGBA").tobytes()).decode("ascii"))
    (g / "anim_test_frames.json").write_text(json.dumps({"frames": ref}), encoding="utf-8")
    w, h, data = F.portrait()
    rgb = Image.frombytes("RGBA", (w, h), data).convert("RGB")
    for name, comp in (("raw", None), ("lzw", "tiff_lzw"), ("packbits", "packbits")):
        rgb.save(g / f"tiff_{name}.tif", compression=comp)
    (g / "tiff_ref.rgba").write_bytes(rgb.convert("RGBA").tobytes())
    print("codec fixtures written")


if __name__ == "__main__" and "--codecs" in sys.argv:
    codec_fixtures()
