"""Image Studio core: safe decoding, geometry, resampling, adjustments and image filters.

All processing is local. Pixels are held as NumPy float64 arrays (``rgb``: H×W×3 sRGB 0–1,
``a``: H×W alpha 0–1). Every operation here has a line-by-line counterpart in
web/src/engine/72_imgcore.js; both editions use the same formulas and summation order so the
generated art matches (see tests/test_image_studio.py, cross-edition fixtures).
"""
from __future__ import annotations

import io
import math
import re
import zlib
from dataclasses import dataclass, field

try:
    import numpy as np
except ImportError:  # the Image Studio needs NumPy; the rest of the app does not
    np = None

MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_SOURCE_PIXELS = 50_000_000      # decompression-bomb limit (decoded pixels)
MAX_WORK_SIDE = 2048                # decoded images are reduced to this for processing; the original is kept
MAX_FRAMES = 600
MAX_FRAME_PIXELS_TOTAL = 400_000_000
SVG_MAX_BYTES = 5 * 1024 * 1024
SVG_MAX_ELEMENTS = 20_000


def require_numpy() -> None:
    if np is None:
        raise RuntimeError("The Image Studio requires NumPy (pip install numpy).")


@dataclass
class RasterImage:
    rgb: "np.ndarray"
    a: "np.ndarray"
    info: dict = field(default_factory=dict)

    @property
    def width(self) -> int:
        return int(self.rgb.shape[1])

    @property
    def height(self) -> int:
        return int(self.rgb.shape[0])

    def copy(self) -> "RasterImage":
        return RasterImage(self.rgb.copy(), self.a.copy(), dict(self.info))

    @classmethod
    def from_rgba_bytes(cls, w: int, h: int, data: bytes, info: dict | None = None) -> "RasterImage":
        require_numpy()
        arr = np.frombuffer(data, dtype=np.uint8).reshape(h, w, 4).astype(np.float64) / 255.0
        return cls(np.ascontiguousarray(arr[:, :, :3]), np.ascontiguousarray(arr[:, :, 3]), info or {})

    def to_rgba_bytes(self) -> bytes:
        arr = np.concatenate([self.rgb, self.a[:, :, None]], axis=2)
        return np.floor(np.clip(arr, 0, 1) * 255 + 0.5).astype(np.uint8).tobytes()


# ====================================================================== decoding
FORMAT_SIGNATURES = [
    (b"\x89PNG\r\n\x1a\n", "PNG"), (b"\xff\xd8\xff", "JPEG"), (b"GIF87a", "GIF"), (b"GIF89a", "GIF"),
    (b"BM", "BMP"), (b"II*\x00", "TIFF"), (b"MM\x00*", "TIFF"), (b"\x00\x00\x01\x00", "ICO"),
]


def sniff_format(data: bytes) -> str:
    """Identify the container from magic bytes (never from the file name)."""
    head = data[:64]
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "WEBP"
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"avif", b"avis"):
            return "AVIF"
        if brand in (b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1", b"heim", b"heis"):
            return "HEIF"
    for sig, name in FORMAT_SIGNATURES:
        if head.startswith(sig):
            return name
    txt = head.lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if txt.startswith(b"<?xml") or txt.startswith(b"<svg") or txt.startswith(b"<!--") or             (txt.startswith(b"<!doctype") and b"<svg" in data[:4096].lower()):
        return "SVG"
    return "UNKNOWN"


def decoder_capabilities() -> dict:
    """Which formats can be decoded on this machine (reported in the UI)."""
    caps = {"PNG": False, "JPEG": False, "GIF": False, "BMP": False, "TIFF": False, "ICO": False,
            "WEBP": False, "AVIF": False, "HEIF": False, "SVG": True, "VIDEO": False}
    notes = {"SVG": "safe built-in rasterizer (shapes, paths, solid fills/strokes; no text, filters or images)",
             "VIDEO": "no local video decoder in the Python edition (the HTML edition decodes video in the browser)"}
    try:
        from PIL import Image, features
        Image.init()
        ext = set(Image.OPEN)
        for k, plug in (("PNG", "PNG"), ("JPEG", "JPEG"), ("GIF", "GIF"), ("BMP", "BMP"), ("TIFF", "TIFF"),
                        ("ICO", "ICO"), ("WEBP", "WEBP"), ("AVIF", "AVIF")):
            caps[k] = plug in ext
        caps["WEBP"] = caps["WEBP"] and bool(features.check("webp"))
        try:
            caps["AVIF"] = caps["AVIF"] and bool(features.check("avif"))
        except Exception:  # older Pillow without the feature flag
            caps["AVIF"] = False
        try:
            import pillow_heif  # noqa: F401  optional plugin
            caps["HEIF"] = True
        except ImportError:
            notes["HEIF"] = "install the optional pillow-heif package to decode HEIC/HEIF"
    except ImportError:
        for k in caps:
            if k not in ("SVG", "VIDEO"):
                notes[k] = "Pillow is not installed"
    if not caps["AVIF"] and "AVIF" not in notes:
        notes["AVIF"] = "this Pillow build has no AVIF decoder"
    return {"formats": caps, "notes": notes}


class ImageDecodeError(ValueError):
    pass


def _pil_open(data: bytes):
    from PIL import Image
    import warnings
    Image.MAX_IMAGE_PIXELS = MAX_SOURCE_PIXELS
    fmt = sniff_format(data)
    if fmt == "HEIF":
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except ImportError as exc:
            raise ImageDecodeError("HEIC/HEIF needs the optional pillow-heif package (not installed)") from exc
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        try:
            im = Image.open(io.BytesIO(data))
            im.size  # noqa: B018 — header parsed
        except Image.DecompressionBombWarning as exc:
            raise ImageDecodeError("image exceeds the pixel limit (possible decompression bomb)") from exc
        except Image.DecompressionBombError as exc:
            raise ImageDecodeError("image exceeds the pixel limit (possible decompression bomb)") from exc
    if im.width * im.height > MAX_SOURCE_PIXELS or im.width < 1 or im.height < 1:
        raise ImageDecodeError(f"image dimensions {im.width}×{im.height} exceed the limit")
    return im


def _pil_to_raster(im, info: dict, max_side: int = MAX_WORK_SIDE) -> RasterImage:
    from PIL import Image, ImageOps
    try:
        im = ImageOps.exif_transpose(im)
        info["exif_oriented"] = True
    except Exception:
        info["exif_oriented"] = False
    im = im.convert("RGBA")
    if max(im.size) > max_side:
        f = max_side / max(im.size)
        im = im.resize((max(1, round(im.width * f)), max(1, round(im.height * f))), Image.Resampling.BOX)
        info["reduced_to"] = list(im.size)
    return RasterImage.from_rgba_bytes(im.width, im.height, im.tobytes(), info)


def decode_image(data: bytes, name: str = "", max_side: int = MAX_WORK_SIDE) -> RasterImage:
    """Decode any supported still image (first frame of animations) into a RasterImage."""
    require_numpy()
    if len(data) > MAX_FILE_BYTES:
        raise ImageDecodeError("file is larger than 100 MB")
    if not data:
        raise ImageDecodeError("empty file")
    fmt = sniff_format(data)
    info = {"name": name, "format": fmt, "bytes": len(data)}
    if fmt == "SVG":
        img = rasterize_svg(data, max_side=min(max_side, 1600))
        img.info.update(info)
        return img
    try:
        from PIL import UnidentifiedImageError
    except ImportError as exc:
        raise ImageDecodeError(f"{fmt} decoding needs Pillow (pip install pillow)") from exc
    try:
        im = _pil_open(data)
        info["source_size"] = [im.width, im.height]
        info["frames"] = int(getattr(im, "n_frames", 1) or 1)
        info["has_alpha"] = im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info
        im.seek(0)
        return _pil_to_raster(im, info, max_side)
    except ImageDecodeError:
        raise
    except UnidentifiedImageError as exc:
        caps = decoder_capabilities()
        note = caps["notes"].get(fmt, "")
        raise ImageDecodeError(f"unsupported or unrecognised image format ({fmt}) {note}".strip()) from exc
    except (OSError, ValueError, SyntaxError, EOFError) as exc:
        raise ImageDecodeError(f"malformed {fmt} file: {exc}") from exc


def decode_frames(data: bytes, max_side: int = 800, max_frames: int = MAX_FRAMES):
    """Decode every frame of an animated image (GIF/WebP/APNG). Returns (frames, durations_ms, info)."""
    require_numpy()
    fmt = sniff_format(data)
    if fmt == "SVG":
        img = decode_image(data)
        return [img], [100], {"format": fmt, "frames": 1, "loop": 0}
    try:
        im = _pil_open(data)
    except ImageDecodeError:
        raise
    except Exception as exc:
        raise ImageDecodeError(f"cannot decode animation: {exc}") from exc
    n = int(getattr(im, "n_frames", 1) or 1)
    if n * im.width * im.height > MAX_FRAME_PIXELS_TOTAL:
        raise ImageDecodeError("animation too large (frames × pixels limit)")
    frames, durs = [], []
    info = {"format": fmt, "frames": n, "loop": int(im.info.get("loop", 0) or 0), "source_size": [im.width, im.height]}
    for i in range(min(n, max_frames)):
        im.seek(i)
        durs.append(int(im.info.get("duration", 100) or 100))
        frames.append(_pil_to_raster(im.copy(), {"frame": i}, max_side))
    info["decoded"] = len(frames)
    return frames, durs, info


def clipboard_image() -> RasterImage | None:
    """Image currently on the OS clipboard (Windows/macOS via Pillow ImageGrab), or None."""
    try:
        from PIL import ImageGrab, Image
        got = ImageGrab.grabclipboard()
    except Exception:
        return None
    if got is None:
        return None
    if isinstance(got, list):  # file paths copied in Explorer
        for p in got:
            try:
                with open(p, "rb") as fh:
                    return decode_image(fh.read(), str(p))
            except Exception:
                continue
        return None
    if isinstance(got, Image.Image):
        return _pil_to_raster(got, {"name": "clipboard", "format": "CLIPBOARD"})
    return None


# ====================================================================== safe SVG rasterizer
_SVG_FORBIDDEN = re.compile(
    rb"<!DOCTYPE|<!ENTITY|<script|<foreignObject|\son[a-z]+\s*=|javascript:|<iframe|<object|<embed|<image\b|"
    rb"<use\b[^>]*href\s*=\s*[\"'](?!#)|xlink:href\s*=\s*[\"'](?!#)|<style|@import|url\(\s*[\"']?(?!#)",
    re.IGNORECASE)

NAMED_COLORS = {
    "black": 0x000000, "white": 0xFFFFFF, "red": 0xFF0000, "green": 0x008000, "lime": 0x00FF00, "blue": 0x0000FF,
    "yellow": 0xFFFF00, "cyan": 0x00FFFF, "aqua": 0x00FFFF, "magenta": 0xFF00FF, "fuchsia": 0xFF00FF,
    "gray": 0x808080, "grey": 0x808080, "silver": 0xC0C0C0, "maroon": 0x800000, "olive": 0x808000,
    "navy": 0x000080, "purple": 0x800080, "teal": 0x008080, "orange": 0xFFA500, "pink": 0xFFC0CB,
    "brown": 0xA52A2A, "gold": 0xFFD700, "indigo": 0x4B0082, "violet": 0xEE82EE, "darkgray": 0xA9A9A9,
    "lightgray": 0xD3D3D3, "darkred": 0x8B0000, "darkgreen": 0x006400, "darkblue": 0x00008B,
    "skyblue": 0x87CEEB, "steelblue": 0x4682B4, "tomato": 0xFF6347, "coral": 0xFF7F50, "salmon": 0xFA8072,
    "crimson": 0xDC143C, "khaki": 0xF0E68C, "beige": 0xF5F5DC, "tan": 0xD2B48C, "chocolate": 0xD2691E,
}


def svg_is_safe(data: bytes) -> tuple[bool, str]:
    """Reject SVG with scripts, event handlers, entities, external references or embedded documents."""
    if len(data) > SVG_MAX_BYTES:
        return False, "SVG larger than 5 MB"
    m = _SVG_FORBIDDEN.search(data)
    if m:
        return False, f"unsafe SVG construct rejected: {m.group(0)[:40].decode('latin-1')!r}"
    return True, ""


def _svg_color(v: str | None, inherit):
    if v is None:
        return inherit
    v = v.strip().lower()
    if v in ("", "inherit"):
        return inherit
    if v in ("none", "transparent"):
        return None
    if v.startswith("url("):
        return 0x808080  # gradients/patterns are approximated by a neutral grey
    if v.startswith("#"):
        h = v[1:]
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h[:3])
        if len(h) >= 6 and all(c in "0123456789abcdef" for c in h[:6]):
            return int(h[:6], 16)
        return inherit
    m = re.match(r"rgba?\(\s*([\d.]+%?)\s*[, ]\s*([\d.]+%?)\s*[, ]\s*([\d.]+%?)", v)
    if m:
        vals = []
        for s in m.groups():
            f = float(s.rstrip("%")) * (2.55 if s.endswith("%") else 1)
            vals.append(max(0, min(255, int(f + 0.5))))
        return (vals[0] << 16) | (vals[1] << 8) | vals[2]
    return NAMED_COLORS.get(v, inherit)


def _svg_num(v, default=0.0) -> float:
    if v is None:
        return default
    m = re.match(r"\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)", str(v))
    return float(m.group(1)) if m else default


def _mat_mul(a, b):
    return (a[0] * b[0] + a[2] * b[1], a[1] * b[0] + a[3] * b[1], a[0] * b[2] + a[2] * b[3],
            a[1] * b[2] + a[3] * b[3], a[0] * b[4] + a[2] * b[5] + a[4], a[1] * b[4] + a[3] * b[5] + a[5])


def _svg_transform(s: str | None):
    m = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    if not s:
        return m
    for name, args in re.findall(r"(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)", s):
        v = [float(x) for x in re.findall(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", args)]
        if name == "matrix" and len(v) == 6:
            t = tuple(v)
        elif name == "translate" and v:
            t = (1, 0, 0, 1, v[0], v[1] if len(v) > 1 else 0)
        elif name == "scale" and v:
            t = (v[0], 0, 0, v[1] if len(v) > 1 else v[0], 0, 0)
        elif name == "rotate" and v:
            r = math.radians(v[0]); c, s_ = math.cos(r), math.sin(r)
            t = (c, s_, -s_, c, 0, 0)
            if len(v) == 3:
                t = _mat_mul(_mat_mul((1, 0, 0, 1, v[1], v[2]), t), (1, 0, 0, 1, -v[1], -v[2]))
        elif name == "skewX" and v:
            t = (1, 0, math.tan(math.radians(v[0])), 1, 0, 0)
        elif name == "skewY" and v:
            t = (1, math.tan(math.radians(v[0])), 0, 1, 0, 0)
        else:
            continue
        m = _mat_mul(m, t)
    return m


def _path_subpaths(d: str) -> list[list[tuple[float, float]]]:
    """Flatten SVG path data (M L H V C S Q T A Z, absolute and relative) into polylines."""
    toks = re.findall(r"[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", d)
    subs, cur = [], []
    x = y = sx = sy = 0.0
    lastc = None
    cmd = None
    i = 0

    def nums(k):
        nonlocal i
        out = []
        for _ in range(k):
            if i >= len(toks) or toks[i].isalpha():
                raise ValueError("bad path")
            out.append(float(toks[i])); i += 1
        return out
    while i < len(toks):
        if toks[i].isalpha():
            cmd = toks[i]; i += 1
        elif cmd is None:
            break
        c, rel = cmd.upper(), cmd.islower()
        try:
            if c == "Z":
                if cur:
                    cur.append((sx, sy)); subs.append(cur); cur = []
                x, y = sx, sy; lastc = None
                continue
            if c == "M":
                px, py = nums(2)
                if rel: px += x; py += y
                if cur: subs.append(cur)
                cur = [(px, py)]; x, y = sx, sy = px, py
                cmd = "l" if rel else "L"; lastc = None
            elif c == "L":
                px, py = nums(2)
                if rel: px += x; py += y
                cur.append((px, py)); x, y = px, py; lastc = None
            elif c == "H":
                px = nums(1)[0] + (x if rel else 0); cur.append((px, y)); x = px; lastc = None
            elif c == "V":
                py = nums(1)[0] + (y if rel else 0); cur.append((x, py)); y = py; lastc = None
            elif c in "CS":
                if c == "C":
                    x1, y1, x2, y2, px, py = nums(6)
                    if rel: x1 += x; y1 += y; x2 += x; y2 += y; px += x; py += y
                else:
                    x2, y2, px, py = nums(4)
                    if rel: x2 += x; y2 += y; px += x; py += y
                    x1, y1 = (2 * x - lastc[0], 2 * y - lastc[1]) if lastc and lastc[2] == "C" else (x, y)
                for k in range(1, 17):
                    t = k / 16; u = 1 - t
                    cur.append((u ** 3 * x + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t ** 3 * px,
                                u ** 3 * y + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t ** 3 * py))
                lastc = (x2, y2, "C"); x, y = px, py
            elif c in "QT":
                if c == "Q":
                    x1, y1, px, py = nums(4)
                    if rel: x1 += x; y1 += y; px += x; py += y
                else:
                    px, py = nums(2)
                    if rel: px += x; py += y
                    x1, y1 = (2 * x - lastc[0], 2 * y - lastc[1]) if lastc and lastc[2] == "Q" else (x, y)
                for k in range(1, 13):
                    t = k / 12; u = 1 - t
                    cur.append((u * u * x + 2 * u * t * x1 + t * t * px, u * u * y + 2 * u * t * y1 + t * t * py))
                lastc = (x1, y1, "Q"); x, y = px, py
            elif c == "A":
                rx, ry, rot, large, sweep, px, py = nums(7)
                if rel: px += x; py += y
                cur.extend(_arc_points(x, y, rx, ry, rot, large != 0, sweep != 0, px, py))
                x, y = px, py; lastc = None
            else:
                i += 1
        except (ValueError, IndexError):
            break
    if cur:
        subs.append(cur)
    return subs


def _arc_points(x1, y1, rx, ry, phi, large, sweep, x2, y2):
    if rx == 0 or ry == 0:
        return [(x2, y2)]
    rx, ry = abs(rx), abs(ry)
    p = math.radians(phi); cp, sp = math.cos(p), math.sin(p)
    dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
    xp, yp = cp * dx + sp * dy, -sp * dx + cp * dy
    lam = xp * xp / (rx * rx) + yp * yp / (ry * ry)
    if lam > 1:
        rx *= math.sqrt(lam); ry *= math.sqrt(lam)
    num = rx * rx * ry * ry - rx * rx * yp * yp - ry * ry * xp * xp
    den = rx * rx * yp * yp + ry * ry * xp * xp
    co = math.sqrt(max(0.0, num / den)) if den else 0.0
    if large == sweep:
        co = -co
    cxp, cyp = co * rx * yp / ry, -co * ry * xp / rx
    cx, cy = cp * cxp - sp * cyp + (x1 + x2) / 2, sp * cxp + cp * cyp + (y1 + y2) / 2

    def ang(ux, uy, vx, vy):
        a = math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
        return a
    t1 = ang(1, 0, (xp - cxp) / rx, (yp - cyp) / ry)
    dt = ang((xp - cxp) / rx, (yp - cyp) / ry, (-xp - cxp) / rx, (-yp - cyp) / ry)
    if not sweep and dt > 0:
        dt -= 2 * math.pi
    elif sweep and dt < 0:
        dt += 2 * math.pi
    n = max(4, int(abs(dt) / (math.pi / 16)))
    pts = []
    for k in range(1, n + 1):
        t = t1 + dt * k / n
        pts.append((cx + rx * math.cos(t) * cp - ry * math.sin(t) * sp, cy + rx * math.cos(t) * sp + ry * math.sin(t) * cp))
    return pts


def rasterize_svg(data: bytes, max_side: int = 1024) -> RasterImage:
    """Rasterize a *sanitized* SVG subset with Pillow (4× supersampled). Never fetches anything."""
    require_numpy()
    ok, why = svg_is_safe(data)
    if not ok:
        raise ImageDecodeError(why)
    import xml.etree.ElementTree as ET
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise ImageDecodeError("SVG rasterization needs Pillow") from exc
    try:
        root = ET.fromstring(data.decode("utf-8", "replace"))
    except ET.ParseError as exc:
        raise ImageDecodeError(f"malformed SVG: {exc}") from exc
    if not root.tag.endswith("svg"):
        raise ImageDecodeError("not an SVG document")
    vb = [float(v) for v in re.findall(r"[-+]?(?:\d+\.?\d*|\.\d+)", root.get("viewBox", ""))]
    w = _svg_num(root.get("width"), 0) or (vb[2] if len(vb) == 4 else 300)
    h = _svg_num(root.get("height"), 0) or (vb[3] if len(vb) == 4 else 150)
    if len(vb) != 4 or vb[2] <= 0 or vb[3] <= 0:
        vb = [0, 0, w, h]
    scale = min(max_side / max(w, h), 8.0)
    ow, oh = max(1, round(w * scale)), max(1, round(h * scale))
    ss = 4
    base = (ow * ss / vb[2], 0, 0, oh * ss / vb[3], -vb[0] * ow * ss / vb[2], -vb[1] * oh * ss / vb[3])
    canvas = Image.new("RGBA", (ow * ss, oh * ss), (0, 0, 0, 0))
    count = 0

    def tag(el):
        return el.tag.rsplit("}", 1)[-1]

    def style_of(el, parent):
        st = dict(parent)
        for k in ("fill", "stroke", "stroke-width", "opacity", "fill-opacity", "stroke-opacity", "fill-rule"):
            if el.get(k) is not None:
                st[k] = el.get(k)
        for decl in (el.get("style") or "").split(";"):
            if ":" in decl:
                k, v = decl.split(":", 1)
                st[k.strip()] = v.strip()
        return st

    def paint(layer_pts, color, alpha, width=None, evenodd=False):
        if color is None or alpha <= 0:
            return
        layer = Image.new("L", canvas.size, 0)
        dr = ImageDraw.Draw(layer)
        for pts in layer_pts:
            if len(pts) < 2:
                continue
            if width is None:
                if len(pts) >= 3:
                    # XOR composition of sub-paths implements the even-odd rule (also used for nonzero; documented)
                    tmp = Image.new("L", canvas.size, 0)
                    ImageDraw.Draw(tmp).polygon(pts, fill=255)
                    from PIL import ImageChops
                    layer = ImageChops.logical_xor(layer.convert("1"), tmp.convert("1")).convert("L")
                    dr = ImageDraw.Draw(layer)
            else:
                dr.line(pts, fill=255, width=max(1, int(width + 0.5)), joint="curve")
        col = Image.new("RGBA", canvas.size, ((color >> 16) & 255, (color >> 8) & 255, color & 255, 0))
        col.putalpha(layer.point(lambda v: int(v * alpha)))
        canvas.alpha_composite(col)

    def walk(el, mat, st):
        nonlocal count
        count += 1
        if count > SVG_MAX_ELEMENTS:
            raise ImageDecodeError("SVG has too many elements")
        t = tag(el)
        if t in ("defs", "title", "desc", "metadata", "clipPath", "mask", "symbol", "linearGradient",
                 "radialGradient", "pattern", "filter", "text", "style"):
            return
        mat = _mat_mul(mat, _svg_transform(el.get("transform")))
        st = style_of(el, st)
        polys = []
        if t == "rect":
            x, y = _svg_num(el.get("x")), _svg_num(el.get("y"))
            rw, rh = _svg_num(el.get("width")), _svg_num(el.get("height"))
            if rw > 0 and rh > 0:
                polys = [[(x, y), (x + rw, y), (x + rw, y + rh), (x, y + rh), (x, y)]]
        elif t in ("circle", "ellipse"):
            cx, cy = _svg_num(el.get("cx")), _svg_num(el.get("cy"))
            rx = _svg_num(el.get("r")) if t == "circle" else _svg_num(el.get("rx"))
            ry = _svg_num(el.get("r")) if t == "circle" else _svg_num(el.get("ry"))
            if rx > 0 and ry > 0:
                polys = [[(cx + rx * math.cos(k * math.pi / 32), cy + ry * math.sin(k * math.pi / 32)) for k in range(65)]]
        elif t == "line":
            polys = [[(_svg_num(el.get("x1")), _svg_num(el.get("y1"))), (_svg_num(el.get("x2")), _svg_num(el.get("y2")))]]
            st = dict(st); st["fill"] = "none"
        elif t in ("polyline", "polygon"):
            v = [float(n) for n in re.findall(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", el.get("points", ""))]
            pts = list(zip(v[0::2], v[1::2]))
            if t == "polygon" and pts:
                pts.append(pts[0])
            polys = [pts] if pts else []
            if t == "polyline":
                st = dict(st); st["fill"] = "none"
        elif t == "path":
            polys = _path_subpaths(el.get("d", ""))
        if polys:
            m2 = _mat_mul(base, mat)
            tp = [[(m2[0] * px + m2[2] * py + m2[4], m2[1] * px + m2[3] * py + m2[5]) for px, py in pts] for pts in polys]
            op = max(0.0, min(1.0, _svg_num(st.get("opacity"), 1.0)))
            fill = _svg_color(st.get("fill"), 0x000000) if st.get("fill") is not None else 0x000000
            paint(tp, fill, op * max(0.0, min(1.0, _svg_num(st.get("fill-opacity"), 1.0))))
            stroke = _svg_color(st.get("stroke"), None)
            if stroke is not None:
                sw = _svg_num(st.get("stroke-width"), 1.0) * math.sqrt(abs(m2[0] * m2[3] - m2[1] * m2[2]))
                paint(tp, stroke, op * max(0.0, min(1.0, _svg_num(st.get("stroke-opacity"), 1.0))), width=sw)
        for ch in list(el):
            walk(ch, mat, st)
    walk(root, (1.0, 0.0, 0.0, 1.0, 0.0, 0.0), {})
    out = canvas.resize((ow, oh), Image.Resampling.BOX)
    return RasterImage.from_rgba_bytes(ow, oh, out.tobytes(), {"format": "SVG", "svg_elements": count,
                                                                "source_size": [ow, oh]})


# ====================================================================== resampling & geometry
def _axis_area(arr, n_out: int, axis: int):
    """Exact area-average resampling along one axis via a sequential prefix sum (portable to JS)."""
    n_in = arr.shape[axis]
    arr = np.moveaxis(arr, axis, 0)
    c = np.concatenate([np.zeros((1,) + arr.shape[1:]), np.cumsum(arr, axis=0)], axis=0)
    edges = np.arange(n_out + 1, dtype=np.float64) * n_in / n_out
    fl = np.minimum(np.floor(edges).astype(np.int64), n_in)
    fr = edges - fl
    nxt = np.minimum(fl + 1, n_in)
    shape = (-1,) + (1,) * (arr.ndim - 1)
    F = c[fl] + fr.reshape(shape) * (c[nxt] - c[fl])
    out = (F[1:] - F[:-1]) / (edges[1:] - edges[:-1]).reshape(shape)
    return np.moveaxis(out, 0, axis)


def resample_area(img: RasterImage, w: int, h: int) -> RasterImage:
    """Premultiplied-alpha area resampling to w×h."""
    w, h = max(1, int(w)), max(1, int(h))
    pre = img.rgb * img.a[:, :, None]
    stack = np.concatenate([pre, img.a[:, :, None]], axis=2)
    if stack.shape[1] != w:
        stack = _axis_area(stack, w, 1)
    if stack.shape[0] != h:
        stack = _axis_area(stack, h, 0)
    a = stack[:, :, 3]
    safe = np.where(a > 1e-9, a, 1.0)
    rgb = np.where(a[:, :, None] > 1e-9, stack[:, :, :3] / safe[:, :, None], 0.0)
    return RasterImage(np.clip(rgb, 0, 1), np.clip(a, 0, 1), dict(img.info))


def resample_plane(p, w: int, h: int):
    if p.shape[1] != w:
        p = _axis_area(p, w, 1)
    if p.shape[0] != h:
        p = _axis_area(p, h, 0)
    return p


def crop(img: RasterImage, x0: float, y0: float, x1: float, y1: float) -> RasterImage:
    W, H = img.width, img.height
    x0, x1 = sorted((max(0.0, min(1.0, x0)), max(0.0, min(1.0, x1))))
    y0, y1 = sorted((max(0.0, min(1.0, y0)), max(0.0, min(1.0, y1))))
    a, b = int(math.floor(x0 * W)), max(int(math.floor(x0 * W)) + 1, int(math.ceil(x1 * W)))
    c, d = int(math.floor(y0 * H)), max(int(math.floor(y0 * H)) + 1, int(math.ceil(y1 * H)))
    b, d = min(b, W), min(d, H)
    a, c = min(a, b - 1), min(c, d - 1)
    return RasterImage(img.rgb[c:d, a:b].copy(), img.a[c:d, a:b].copy(), dict(img.info))


def rotate90(img: RasterImage, deg: int) -> RasterImage:
    k = (-(int(deg) // 90)) % 4  # clockwise
    if k == 0:
        return img
    return RasterImage(np.ascontiguousarray(np.rot90(img.rgb, k)), np.ascontiguousarray(np.rot90(img.a, k)), dict(img.info))


def flip(img: RasterImage, h: bool, v: bool) -> RasterImage:
    rgb, a = img.rgb, img.a
    if h:
        rgb, a = rgb[:, ::-1], a[:, ::-1]
    if v:
        rgb, a = rgb[::-1], a[::-1]
    return RasterImage(np.ascontiguousarray(rgb), np.ascontiguousarray(a), dict(img.info))


def rotate_free(img: RasterImage, angle: float) -> RasterImage:
    """Rotate clockwise by any angle with bilinear sampling; the canvas grows, corners are transparent."""
    if abs(angle) < 1e-9:
        return img
    t = math.radians(angle)
    c, s = math.cos(t), math.sin(t)
    W, H = img.width, img.height
    nw = int(math.ceil(abs(W * c) + abs(H * s)))
    nh = int(math.ceil(abs(W * s) + abs(H * c)))
    ys, xs = np.mgrid[0:nh, 0:nw].astype(np.float64)
    dx, dy = xs + 0.5 - nw / 2, ys + 0.5 - nh / 2
    sx = c * dx + s * dy + W / 2 - 0.5
    sy = -s * dx + c * dy + H / 2 - 0.5
    pre = np.concatenate([img.rgb * img.a[:, :, None], img.a[:, :, None]], axis=2)
    x0, y0 = np.floor(sx).astype(np.int64), np.floor(sy).astype(np.int64)
    fx, fy = sx - x0, sy - y0
    out = np.zeros((nh, nw, 4))
    for oy, ox, wgt in ((0, 0, (1 - fx) * (1 - fy)), (0, 1, fx * (1 - fy)), (1, 0, (1 - fx) * fy), (1, 1, fx * fy)):
        xx, yy = x0 + ox, y0 + oy
        ok = (xx >= 0) & (xx < W) & (yy >= 0) & (yy < H)
        v = pre[np.clip(yy, 0, H - 1), np.clip(xx, 0, W - 1)]
        out += np.where(ok[:, :, None], v * wgt[:, :, None], 0.0)
    a = out[:, :, 3]
    rgb = np.where(a[:, :, None] > 1e-9, out[:, :, :3] / np.where(a > 1e-9, a, 1)[:, :, None], 0.0)
    return RasterImage(np.clip(rgb, 0, 1), np.clip(a, 0, 1), dict(img.info))


def pad(img: RasterImage, left: int, top: int, right: int, bottom: int) -> RasterImage:
    if not (left or top or right or bottom):
        return img
    rgb = np.pad(img.rgb, ((top, bottom), (left, right), (0, 0)))
    a = np.pad(img.a, ((top, bottom), (left, right)))
    return RasterImage(rgb, a, dict(img.info))


# ====================================================================== colour helpers
def srgb_to_linear(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(c):
    c = np.clip(c, 0, None)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


def luminance(rgb, method: str = "rec709"):
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    if method == "average":
        return (r + g + b) / 3
    if method == "rec601":
        return 0.299 * r + 0.587 * g + 0.114 * b
    if method in ("linear", "perceptual"):
        y = 0.2126 * srgb_to_linear(r) + 0.7152 * srgb_to_linear(g) + 0.0722 * srgb_to_linear(b)
        if method == "linear":
            return y
        return np.where(y > 216 / 24389, 116 * np.cbrt(y) - 16, y * 24389 / 27) / 100
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def rgb_to_lab(rgb):
    """sRGB (…×3, 0–1) → CIE L*a*b* (D65)."""
    lin = srgb_to_linear(rgb)
    x = (0.4124564 * lin[..., 0] + 0.3575761 * lin[..., 1] + 0.1804375 * lin[..., 2]) / 0.95047
    y = 0.2126729 * lin[..., 0] + 0.7151522 * lin[..., 1] + 0.0721750 * lin[..., 2]
    z = (0.0193339 * lin[..., 0] + 0.1191920 * lin[..., 1] + 0.9503041 * lin[..., 2]) / 1.08883

    def f(t):
        return np.where(t > 216 / 24389, np.cbrt(t), (24389 / 27 * t + 16) / 116)
    fx, fy, fz = f(x), f(y), f(z)
    return np.stack([116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)], axis=-1)


def int_to_rgb01(c: int):
    return ((c >> 16) & 255) / 255.0, ((c >> 8) & 255) / 255.0, (c & 255) / 255.0


def rgb01_to_int(rgb):
    """Vectorised 0–1 RGB → 0xRRGGBB ints (round half up, like join_rgb)."""
    q = np.clip(np.floor(np.clip(rgb, 0, 1) * 255 + 0.5), 0, 255).astype(np.int64)
    return (q[..., 0] << 16) | (q[..., 1] << 8) | q[..., 2]


def parse_color_list(s: str) -> list[int]:
    out = []
    for part in re.split(r"[\s,;]+", s or ""):
        p = part.strip().lstrip("#")
        if len(p) == 3:
            p = "".join(ch * 2 for ch in p)
        if len(p) == 6 and all(ch in "0123456789abcdefABCDEF" for ch in p):
            out.append(int(p, 16))
    return out[:256]


# ====================================================================== filters
def gaussian_kernel(sigma: float) -> list[float]:
    r = max(1, int(math.ceil(sigma * 3)))
    k = [math.exp(-(i * i) / (2 * sigma * sigma)) for i in range(-r, r + 1)]
    s = sum(k)
    return [v / s for v in k]


def _conv_axis(p, k: list[float], axis: int):
    r = len(k) // 2
    n = p.shape[axis]
    idx = np.arange(n)
    out = np.zeros_like(p)
    for j, w in enumerate(k):
        src = np.clip(idx + j - r, 0, n - 1)
        out = out + w * np.take(p, src, axis=axis)
    return out


def blur(p, sigma: float):
    """Separable Gaussian blur with clamped edges (works on H×W or H×W×C)."""
    if sigma <= 0.05:
        return p
    k = gaussian_kernel(sigma)
    return _conv_axis(_conv_axis(p, k, 1), k, 0)


def box_mean(p, r: int):
    """Mean over a (2r+1)² window with clamped edges via prefix sums."""
    H, W = p.shape
    ip = np.zeros((H + 1, W + 1))
    ip[1:, 1:] = np.cumsum(np.cumsum(p, axis=0), axis=1)
    ys, xs = np.arange(H), np.arange(W)
    y0, y1 = np.clip(ys - r, 0, H), np.clip(ys + r + 1, 0, H)
    x0, x1 = np.clip(xs - r, 0, W), np.clip(xs + r + 1, 0, W)
    s = ip[y1][:, x1] - ip[y0][:, x1] - ip[y1][:, x0] + ip[y0][:, x0]
    area = (y1 - y0)[:, None] * (x1 - x0)[None, :]
    return s / area


def median3(p):
    """3×3 median with clamped edges (per channel)."""
    H, W = p.shape[:2]
    ys, xs = np.arange(H), np.arange(W)
    stack = []
    for dy in (-1, 0, 1):
        yy = np.clip(ys + dy, 0, H - 1)
        for dx in (-1, 0, 1):
            xx = np.clip(xs + dx, 0, W - 1)
            stack.append(p[yy][:, xx])
    return np.sort(np.stack(stack, axis=0), axis=0)[4]


def sobel(L):
    """Sobel gradients (gx, gy) with clamped edges."""
    H, W = L.shape
    ys, xs = np.arange(H), np.arange(W)
    ym, yp = np.clip(ys - 1, 0, H - 1), np.clip(ys + 1, 0, H - 1)
    xm, xp = np.clip(xs - 1, 0, W - 1), np.clip(xs + 1, 0, W - 1)

    def at(yi, xi):
        return L[yi][:, xi]
    gx = (at(ym, xp) + 2 * at(ys, xp) + at(yp, xp)) - (at(ym, xm) + 2 * at(ys, xm) + at(yp, xm))
    gy = (at(yp, xm) + 2 * at(yp, xs) + at(yp, xp)) - (at(ym, xm) + 2 * at(ym, xs) + at(ym, xp))
    return gx, gy


def _dilate8(m):
    H, W = m.shape
    out = m.copy()
    pm = np.pad(m, 1)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy or dx:
                out |= pm[1 + dy:1 + dy + H, 1 + dx:1 + dx + W]
    return out


def canny(L, low: float, high: float, sigma: float = 1.0):
    """Canny edges: Gaussian → Sobel → non-maximum suppression → hysteresis (8-connected)."""
    g = blur(L, sigma)
    gx, gy = sobel(g)
    mag = np.sqrt(gx * gx + gy * gy) / 4.0
    ang = (np.degrees(np.arctan2(gy, gx)) + 180.0) % 180.0
    H, W = L.shape
    pm = np.pad(mag, 1)
    sector = np.where((ang < 22.5) | (ang >= 157.5), 0, np.where(ang < 67.5, 1, np.where(ang < 112.5, 2, 3)))
    offs = {0: ((0, 1), (0, -1)), 1: ((1, 1), (-1, -1)), 2: ((1, 0), (-1, 0)), 3: ((1, -1), (-1, 1))}
    keep = np.zeros_like(mag, dtype=bool)
    for s, ((ay, ax), (by, bx)) in offs.items():
        n1 = pm[1 + ay:1 + ay + H, 1 + ax:1 + ax + W]
        n2 = pm[1 + by:1 + by + H, 1 + bx:1 + bx + W]
        keep |= (sector == s) & (mag >= n1) & (mag >= n2)
    nms = np.where(keep, mag, 0.0)
    strong = nms >= high
    weak = nms >= low
    edges = strong.copy()
    while True:
        grown = _dilate8(edges) & weak
        if (grown == edges).all():
            break
        edges = grown
    return edges, mag, ang


def otsu(values) -> float:
    """Otsu threshold (0–1) over a 256-bin histogram."""
    h = np.bincount(np.clip(np.floor(values.ravel() * 255 + 0.5), 0, 255).astype(np.int64), minlength=256).astype(np.float64)
    total = h.sum()
    if total == 0:
        return 0.5
    best, bt = -1.0, 127
    sum_all = float((np.arange(256) * h).sum())
    wb = sb = 0.0
    for t in range(256):
        wb += h[t]
        if wb == 0:
            continue
        wf = total - wb
        if wf == 0:
            break
        sb += t * h[t]
        mb, mf = sb / wb, (sum_all - sb) / wf
        between = wb * wf * (mb - mf) ** 2
        if between > best:
            best, bt = between, t
    return (bt + 0.5) / 255.0


def equalize(L, clahe: bool = False, tiles: int = 8, clip: float = 2.0):
    """Global histogram equalization or CLAHE (contrast-limited adaptive) on a 0–1 plane."""
    H, W = L.shape
    q = np.clip(np.floor(L * 255 + 0.5), 0, 255).astype(np.int64)

    def mapping(block):
        h = np.bincount(block.ravel(), minlength=256).astype(np.float64)
        if clahe:
            limit = max(1.0, clip * block.size / 256)
            excess = np.maximum(h - limit, 0).sum()
            h = np.minimum(h, limit) + excess / 256
        c = np.cumsum(h)
        return (c - c[0]) / max(1e-9, c[-1] - c[0])
    if not clahe:
        return mapping(q)[q]
    ty, tx = max(1, min(tiles, H)), max(1, min(tiles, W))
    ys = [int(i * H / ty + 0.5) for i in range(ty + 1)]
    xs = [int(i * W / tx + 0.5) for i in range(tx + 1)]
    maps = np.zeros((ty, tx, 256))
    for i in range(ty):
        for j in range(tx):
            maps[i, j] = mapping(q[ys[i]:ys[i + 1], xs[j]:xs[j + 1]])
    cy = (np.arange(H) + 0.5) * ty / H - 0.5
    cx = (np.arange(W) + 0.5) * tx / W - 0.5
    y0 = np.clip(np.floor(cy).astype(np.int64), 0, ty - 1); y1 = np.clip(y0 + 1, 0, ty - 1)
    x0 = np.clip(np.floor(cx).astype(np.int64), 0, tx - 1); x1 = np.clip(x0 + 1, 0, tx - 1)
    fy = np.clip(cy - y0, 0, 1)[:, None]; fx = np.clip(cx - x0, 0, 1)[None, :]
    Y0, X0, Y1, X1 = y0[:, None], x0[None, :], y1[:, None], x1[None, :]
    v00, v01 = maps[Y0, X0, q], maps[Y0, X1, q]
    v10, v11 = maps[Y1, X0, q], maps[Y1, X1, q]
    return (v00 * (1 - fx) + v01 * fx) * (1 - fy) + (v10 * (1 - fx) + v11 * fx) * fy


def remove_background(img: RasterImage, tolerance: float) -> RasterImage:
    """Make the border-connected region similar to the border colour transparent (4-connected flood)."""
    H, W = img.a.shape
    rgb = img.rgb
    border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]], axis=0)
    bg = np.median(border, axis=0)
    dist = np.sqrt(((rgb - bg) ** 2).sum(axis=2)) / math.sqrt(3)
    cand = (dist <= tolerance) & (img.a > 0.01)
    region = np.zeros_like(cand)
    region[0, :] = cand[0, :]; region[-1, :] = cand[-1, :]; region[:, 0] |= cand[:, 0]; region[:, -1] |= cand[:, -1]
    for _ in range(H + W + 4):
        p = np.pad(region, 1)
        grown = (p[:-2, 1:-1] | p[2:, 1:-1] | p[1:-1, :-2] | p[1:-1, 2:] | region) & cand
        if (grown == region).all():
            break
        region = grown
    a = np.where(region, 0.0, img.a)
    return RasterImage(img.rgb, a, dict(img.info))


# ====================================================================== adjustment pipeline
ADJUST_DEFAULTS = {
    "exposure": 0.0, "brightness": 0.0, "contrast": 1.0, "gamma": 1.0, "saturation": 1.0, "vibrance": 0.0,
    "hue": 0.0, "sharpness": 0.0, "blur": 0.0, "denoise": 0.0, "black": 0.0, "white": 1.0, "highlights": 0.0,
    "shadows": 0.0, "posterize": 0, "grayscale": False, "invert": False, "remove_bg": 0.0,
    "equalize": "none", "local_contrast": 0.0,
}


def adjust(img: RasterImage, p: dict) -> RasterImage:
    """Non-destructive adjustment pipeline; returns a new image (the input is never modified)."""
    g = lambda k: p.get(k, ADJUST_DEFAULTS[k])  # noqa: E731
    out = img
    if g("remove_bg") > 0:
        out = remove_background(out, float(g("remove_bg")))
    rgb = out.rgb.copy()
    if g("exposure") != 0:
        rgb = linear_to_srgb(srgb_to_linear(rgb) * (2.0 ** float(g("exposure"))))
    b0, w0 = float(g("black")), float(g("white"))
    if b0 != 0 or w0 != 1:
        rgb = (rgb - b0) / max(1e-3, w0 - b0)
    rgb = np.clip(rgb, 0, 1)
    sh, hi = float(g("shadows")), float(g("highlights"))
    if sh:
        rgb = rgb + 0.9 * sh * rgb * (1 - rgb) ** 2
    if hi:
        rgb = rgb + 0.9 * hi * rgb * rgb * (1 - rgb)
    if g("brightness") != 0 or g("contrast") != 1:
        rgb = (rgb - 0.5) * float(g("contrast")) + 0.5 + float(g("brightness"))
    rgb = np.clip(rgb, 0, 1)
    if g("gamma") != 1:
        rgb = rgb ** (1.0 / max(0.05, float(g("gamma"))))
    sat, vib, hue = float(g("saturation")), float(g("vibrance")), float(g("hue"))
    if sat != 1 or vib != 0:
        y = luminance(rgb)[..., None]
        f = sat
        if vib:
            cur = rgb.max(axis=2, keepdims=True) - rgb.min(axis=2, keepdims=True)
            f = f * (1 + vib * (1 - cur))
        rgb = np.clip(y + (rgb - y) * f, 0, 1)
    if hue:
        t = math.radians(hue); c, s = math.cos(t), math.sin(t)
        r_, g_, b_ = rgb[..., 0], rgb[..., 1], rgb[..., 2]
        y_ = r_ * 0.299 + g_ * 0.587 + b_ * 0.114
        i_ = r_ * 0.595716 + g_ * -0.274453 + b_ * -0.321263
        q_ = r_ * 0.211456 + g_ * -0.522591 + b_ * 0.311135
        i2 = i_ * c - q_ * s
        q2 = i_ * s + q_ * c
        rgb = np.clip(np.stack([y_ + 0.9563 * i2 + 0.6210 * q2, y_ - 0.2721 * i2 - 0.6474 * q2,
                                y_ - 1.1070 * i2 + 1.7046 * q2], axis=-1), 0, 1)
    if g("grayscale"):
        rgb = np.repeat(luminance(rgb)[..., None], 3, axis=2)
    eq, lc = g("equalize"), float(g("local_contrast"))
    if eq in ("global", "clahe") or lc > 0:
        L = luminance(rgb)
        L2 = L
        if eq in ("global", "clahe"):
            L2 = equalize(L2, clahe=(eq == "clahe"))
        if lc > 0:
            L2 = L2 + lc * (L2 - blur(L2, max(1.0, max(L.shape) / 40)))
        rgb = np.clip(rgb + (L2 - L)[..., None], 0, 1)
    if g("denoise") > 0:
        d = float(g("denoise"))
        rgb = rgb * (1 - d) + median3(rgb) * d
    if g("blur") > 0:
        rgb = blur(rgb, float(g("blur")))
    if g("sharpness") > 0:
        rgb = np.clip(rgb + float(g("sharpness")) * (rgb - blur(rgb, 1.0)), 0, 1)
    n = int(g("posterize"))
    if n >= 2:
        rgb = np.floor(rgb * (n - 1) + 0.5) / (n - 1)
    if g("invert"):
        rgb = 1 - rgb
    return RasterImage(np.clip(rgb, 0, 1), out.a, dict(out.info))


def composite(img: RasterImage, bg: int):
    """Composite over a solid colour; returns H×W×3."""
    br, bgc, bb = int_to_rgb01(bg)
    base = np.array([br, bgc, bb])
    return img.rgb * img.a[:, :, None] + base * (1 - img.a[:, :, None])


def median_cut(rgb, k: int, max_samples: int = 20000):
    """Deterministic median-cut palette (k colours, 0–1 floats) from an H×W×3 array."""
    px = rgb.reshape(-1, 3)
    step = max(1, len(px) // max_samples)
    px = px[::step]
    boxes = [px]
    while len(boxes) < k:
        best, bi, bc = -1.0, -1, 0
        for i, b in enumerate(boxes):
            if len(b) < 2:
                continue
            rng = b.max(axis=0) - b.min(axis=0)
            c = int(np.argmax(rng))
            if rng[c] > best:
                best, bi, bc = float(rng[c]), i, c
        if bi < 0 or best <= 0:
            break
        b = boxes.pop(bi)
        order = np.argsort(b[:, bc], kind="stable")
        mid = len(b) // 2
        boxes.insert(bi, b[order[mid:]])
        boxes.insert(bi, b[order[:mid]])
    return [tuple(float(v) for v in b.mean(axis=0)) for b in boxes if len(b)]


def zlib_crc(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF
