"""Build bundled monospace resources from DejaVu Sans Mono (Bitstream Vera license).

Outputs (src/leerbox/data/):
  mono_atlas.json   8×16 1-bit glyph atlas used for PNG/BMP export without Pillow
  DejaVuSansMono.ttf.z / DejaVuSans.ttf.z  zlib-compressed TTFs for Pillow raster export
  dejavu_mono.woff.b64 is not produced; the HTML build embeds the TTF directly.
"""
from __future__ import annotations

import json
import zlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "third_party" / "mono_font"
OUT = ROOT / "src" / "leerbox" / "data"

CHARS = (
    [chr(c) for c in range(32, 127)] + [chr(c) for c in range(0xA0, 0x180)]
    + [chr(c) for c in range(0x2500, 0x2580)] + [chr(c) for c in range(0x2190, 0x2200)]
    + [chr(c) for c in range(0x370, 0x400)] + [chr(c) for c in range(0x400, 0x460)]
    + list("•·●○◆◇■□▪▫★☆♥♦♣♠✓✗‾¯—–‘’“”…′″‹›«»€™©®°±×÷≈≠≤≥∞√∑∏∫ΩµπΔ☺☻♪♫☼►◄▲▼◀▶◢◣◤◥⌐¬")
)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype(str(SRC / "DejaVuSansMono.ttf"), 13)
    notdef = font.getmask("")
    atlas = {}
    for ch in dict.fromkeys(CHARS):
        if 0x2580 <= ord(ch) <= 0x259F:
            continue  # block elements are drawn procedurally
        m = font.getmask(ch)
        if ch != " " and bytes(m) == bytes(notdef) and m.size == notdef.size:
            continue
        im = Image.new("L", (8, 16), 0)
        ImageDraw.Draw(im).text((0, 12), ch, font=font, fill=255, anchor="ls")
        px = im.load()
        rows = []
        for y in range(16):
            v = 0
            for x in range(8):
                if px[x, y] >= 100:
                    v |= 1 << x
            rows.append(f"{v:02x}")
        atlas[ch] = "".join(rows)
    (OUT / "mono_atlas.json").write_text(json.dumps({"w": 8, "h": 16, "g": atlas}, ensure_ascii=False,
                                                     separators=(",", ":")), encoding="utf-8")
    for name in ("DejaVuSansMono.ttf", "DejaVuSans.ttf"):
        (OUT / (name + ".z")).write_bytes(zlib.compress((SRC / name).read_bytes(), 9))
    print(f"atlas glyphs: {len(atlas)}")


if __name__ == "__main__":
    main()
