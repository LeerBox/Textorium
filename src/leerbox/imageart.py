"""ImageArtEngine: local image → ASCII / Unicode / Braille / ANSI art.

Images never leave the machine. Decoding uses Pillow when installed; the Tk
UI falls back to Tk's native PNG/GIF/PPM decoder otherwise.
"""
from __future__ import annotations

from dataclasses import dataclass

from .art import Art, join_rgb, split_rgb

MAX_IMAGE_PIXELS = 40_000_000
MAX_IMAGE_BYTES = 60 * 1024 * 1024
MAX_COLS = 1000

RAMPS = {
    "standard": " .:-=+*#%@",
    "detailed": " .'`^\",:;Il!i><~+_-?][}{1)(|\\/tfjrxnuvczXYUJCLQ0OZmwqpdbkhao*#MW&8%B@$",
    "blocks": " ░▒▓█",
    "simple": " .oO@",
    "dots": " ·•●",
    "binary": " 01",
    "lines": " -=≡",
}

BAYER4 = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]


@dataclass
class ImageData:
    width: int
    height: int
    pixels: list[int]  # 0xRRGGBB, alpha already composited


@dataclass
class ImageOptions:
    cols: int = 100
    mode: str = "ascii"          # ascii | blocks | half | quarter | braille
    ramp: str = "standard"       # key of RAMPS or a literal custom ramp
    brightness: float = 0.0      # -1 … 1
    contrast: float = 1.0        # 0 … 3
    gamma: float = 1.0           # 0.2 … 5
    invert: bool = False
    dither: str = "none"         # none | floyd | atkinson | ordered
    color: str = "none"          # none | truecolor | 256 | 16 (colour quantisation happens at ANSI export)
    aspect: float = 0.5          # character cell width / height
    threshold: float = 0.5       # for 1-bit modes (braille, quarter)


def load_image(data: bytes) -> ImageData:
    """Decode an image with Pillow (raises RuntimeError when Pillow is unavailable)."""
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("image file too large")
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Pillow is not installed") from exc
    import io
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    with Image.open(io.BytesIO(data)) as im:
        im.draft("RGB", (2000, 2000))
        if im.width * im.height > MAX_IMAGE_PIXELS:
            raise ValueError("image has too many pixels")
        im = im.convert("RGBA")
        if im.width > 1600 or im.height > 1600:
            im.thumbnail((1600, 1600))
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        bg.alpha_composite(im)
        rgb = bg.convert("RGB")
        raw = rgb.tobytes()
    px = [(raw[i] << 16) | (raw[i + 1] << 8) | raw[i + 2] for i in range(0, len(raw), 3)]
    return ImageData(rgb.width, rgb.height, px)


def _resample(img: ImageData, tw: int, th: int) -> list[list[int]]:
    """Area-average downscale (box filter) to tw × th colours."""
    tw, th = max(1, tw), max(1, th)
    sr = [[0] * tw for _ in range(th)]
    sg = [[0] * tw for _ in range(th)]
    sb = [[0] * tw for _ in range(th)]
    cnt = [[0] * tw for _ in range(th)]
    W, H = img.width, img.height
    xs = [min(tw - 1, x * tw // W) for x in range(W)]
    for y in range(H):
        ty = min(th - 1, y * th // H)
        row = img.pixels[y * W:(y + 1) * W]
        r_, g_, b_, c_ = sr[ty], sg[ty], sb[ty], cnt[ty]
        for x, p in enumerate(row):
            tx = xs[x]
            r_[tx] += p >> 16
            g_[tx] += (p >> 8) & 255
            b_[tx] += p & 255
            c_[tx] += 1
    out = []
    for y in range(th):
        out.append([join_rgb(sr[y][x] / max(1, cnt[y][x]), sg[y][x] / max(1, cnt[y][x]), sb[y][x] / max(1, cnt[y][x]))
                    for x in range(tw)])
    return out


def _luma(c: int) -> float:
    r, g, b = split_rgb(c)
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255


def _adjust(v: float, o: ImageOptions) -> float:
    v = (v - 0.5) * o.contrast + 0.5 + o.brightness
    v = 0.0 if v < 0 else 1.0 if v > 1 else v
    if o.gamma != 1.0 and v > 0:
        v = v ** o.gamma
    return 1.0 - v if o.invert else v


def _quantize(gray: list[list[float]], levels: int, dither: str) -> list[list[int]]:
    """Map 0..1 values to 0..levels-1 with optional dithering."""
    h = len(gray)
    w = len(gray[0]) if h else 0
    g = [list(r) for r in gray]
    out = [[0] * w for _ in range(h)]
    n = levels - 1
    for y in range(h):
        for x in range(w):
            v = g[y][x]
            if dither == "ordered":
                v = v + (BAYER4[y % 4][x % 4] / 16 - 0.5) / max(1, n)
            q = int(v * n + 0.5)
            q = 0 if q < 0 else n if q > n else q
            out[y][x] = q
            if dither in ("floyd", "atkinson"):
                err = v - q / max(1, n)
                if dither == "floyd":
                    for dx, dy, f in ((1, 0, 7 / 16), (-1, 1, 3 / 16), (0, 1, 5 / 16), (1, 1, 1 / 16)):
                        xx, yy = x + dx, y + dy
                        if 0 <= xx < w and yy < h:
                            g[yy][xx] += err * f
                else:
                    for dx, dy in ((1, 0), (2, 0), (-1, 1), (0, 1), (1, 1), (0, 2)):
                        xx, yy = x + dx, y + dy
                        if 0 <= xx < w and yy < h:
                            g[yy][xx] += err / 8
    return out


def image_to_art(img: ImageData, o: ImageOptions) -> Art:
    cols = max(4, min(MAX_COLS, int(o.cols)))
    aspect = max(0.2, min(2.0, o.aspect))
    rows = max(1, int(img.height / img.width * cols * aspect + 0.5))
    colored = o.color != "none"
    if o.mode == "half":
        grid = _resample(img, cols, rows * 2)
        art = Art.blank(cols, rows)
        for y in range(rows):
            for x in range(cols):
                top, bot = grid[2 * y][x], grid[2 * y + 1][x] if 2 * y + 1 < len(grid) else 0xFFFFFF
                if colored:
                    art.chars[y][x] = "▀"
                    art.fg[y][x], art.bg[y][x] = top, bot
                else:
                    a = _adjust(_luma(top), o) < o.threshold
                    b = _adjust(_luma(bot), o) < o.threshold
                    art.chars[y][x] = " ▀▄█"[a | b << 1]
        return art
    if o.mode in ("braille", "quarter"):
        sx, sy = (2, 4) if o.mode == "braille" else (2, 2)
        grid = _resample(img, cols * sx, rows * sy)
        gray = [[_adjust(_luma(c), o) for c in r] for r in grid]
        if o.dither != "none":
            q = _quantize(gray, 2, o.dither)
            bits = [[1 - v for v in r] for r in q]
        else:
            bits = [[1 if v < o.threshold else 0 for v in r] for r in gray]
        art = Art.blank(cols, rows)
        quad = " ▘▝▀▖▌▞▛▗▚▐▜▄▙▟█"
        for y in range(rows):
            for x in range(cols):
                def b(dx, dy):
                    yy, xx = y * sy + dy, x * sx + dx
                    return bits[yy][xx] if yy < len(bits) and xx < len(bits[0]) else 0
                if o.mode == "braille":
                    v = (b(0, 0) | b(0, 1) << 1 | b(0, 2) << 2 | b(1, 0) << 3 | b(1, 1) << 4 | b(1, 2) << 5
                         | b(0, 3) << 6 | b(1, 3) << 7)
                    art.chars[y][x] = chr(0x2800 + v) if v else "⠀"
                else:
                    art.chars[y][x] = quad[b(0, 0) | b(1, 0) << 1 | b(0, 1) << 2 | b(1, 1) << 3]
                if colored:
                    cells = [grid[y * sy + dy][x * sx + dx] for dy in range(sy) for dx in range(sx)
                             if y * sy + dy < len(grid) and x * sx + dx < len(grid[0])]
                    rs = sum(c >> 16 for c in cells); gs = sum((c >> 8) & 255 for c in cells); bs = sum(c & 255 for c in cells)
                    n = max(1, len(cells))
                    art.fg[y][x] = join_rgb(rs / n, gs / n, bs / n)
        return art
    ramp = RAMPS.get(o.ramp, o.ramp) if o.mode == "ascii" else RAMPS["blocks"]
    from .figlet import graphemes
    chars = graphemes(ramp) or list(" .:-=+*#%@")
    if len(chars) < 2:
        chars = [" "] + chars
    grid = _resample(img, cols, rows)
    # darker pixels → denser characters (dark-on-light convention); invert flips it
    gray = [[1.0 - _adjust(_luma(c), o) for c in r] for r in grid]
    q = _quantize(gray, len(chars), o.dither)
    art = Art.blank(cols, rows)
    for y in range(rows):
        for x in range(cols):
            art.chars[y][x] = chars[q[y][x]]
            if colored:
                art.fg[y][x] = grid[y][x]
    return art
