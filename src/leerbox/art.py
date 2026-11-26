"""Cell-grid model shared by every renderer, effect and exporter.

An :class:`Art` is a rectangle of cells. Each cell holds one grapheme cluster
(display width 1) plus optional foreground/background colours stored as
0xRRGGBB integers (``None`` = default colour). Graphical-only attributes (glow)
live in ``Art.meta`` and are honoured only by HTML/SVG/raster exporters.
"""
from __future__ import annotations

from dataclasses import dataclass, field


def rgb_to_hex(c: int) -> str:
    return f"#{c:06x}"


def hex_to_rgb(s: str) -> int:
    s = s.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    if len(s) != 6 or any(ch not in "0123456789abcdefABCDEF" for ch in s):
        raise ValueError(f"invalid colour {s!r}")
    return int(s, 16)


def split_rgb(c: int) -> tuple[int, int, int]:
    return (c >> 16) & 255, (c >> 8) & 255, c & 255


def join_rgb(r: float, g: float, b: float) -> int:
    def clamp(v: float) -> int:
        v = int(v + 0.5) if v >= 0 else 0  # round-half-up, identical to JS Math.round for v >= 0
        return 255 if v > 255 else v
    return (clamp(r) << 16) | (clamp(g) << 8) | clamp(b)


@dataclass
class Art:
    chars: list[list[str]]
    fg: list[list[int | None]] = field(default_factory=list)
    bg: list[list[int | None]] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.normalize()

    # ------------------------------------------------------------------
    @classmethod
    def from_text(cls, text: str) -> "Art":
        from .figlet import graphemes, char_width
        rows = []
        # never let control characters (ESC, BEL, C1 ...) from user text or imported fonts reach exports
        text = "".join(c if c == "\n" or (ord(c) >= 32 and not 0x7F <= ord(c) < 0xA0) else (" " if c == "\t" else "")
                       for c in text)
        for line in text.split("\n"):
            cells = []
            for g in graphemes(line):
                w = char_width(g)
                if w == 0 and cells and g not in (" ",):
                    cells[-1] += g  # attach stray combining mark
                    continue
                cells.append(g)
                if w == 2:
                    cells.append("")  # continuation cell for wide characters
            rows.append(cells)
        return cls(rows)

    @classmethod
    def blank(cls, w: int, h: int) -> "Art":
        return cls([[" "] * w for _ in range(h)])

    def normalize(self) -> None:
        w = max((len(r) for r in self.chars), default=0)
        for r in self.chars:
            if len(r) < w:
                r.extend([" "] * (w - len(r)))
        h = len(self.chars)
        if len(self.fg) != h or any(len(r) != w for r in self.fg):
            old = self.fg
            self.fg = [[(old[y][x] if y < len(old) and x < len(old[y]) else None) for x in range(w)] for y in range(h)]
        if len(self.bg) != h or any(len(r) != w for r in self.bg):
            old = self.bg
            self.bg = [[(old[y][x] if y < len(old) and x < len(old[y]) else None) for x in range(w)] for y in range(h)]

    @property
    def width(self) -> int:
        return len(self.chars[0]) if self.chars else 0

    @property
    def height(self) -> int:
        return len(self.chars)

    def copy(self) -> "Art":
        return Art([list(r) for r in self.chars], [list(r) for r in self.fg],
                   [list(r) for r in self.bg], dict(self.meta))

    def is_ink(self, x: int, y: int) -> bool:
        c = self.chars[y][x]
        return c not in (" ", "")

    def to_text(self, strip: bool = True) -> str:
        lines = ["".join(r) for r in self.chars]
        if strip:
            lines = [ln.rstrip() for ln in lines]
        return "\n".join(lines)

    def has_color(self) -> bool:
        return any(c is not None for r in self.fg for c in r) or any(c is not None for r in self.bg for c in r)

    def trim_vertical(self) -> None:
        while len(self.chars) > 1 and not "".join(self.chars[0]).strip():
            self.chars.pop(0); self.fg.pop(0); self.bg.pop(0)
        while len(self.chars) > 1 and not "".join(self.chars[-1]).strip():
            self.chars.pop(); self.fg.pop(); self.bg.pop()

    def trim_right(self) -> None:
        w = 0
        for y, r in enumerate(self.chars):
            for x in range(len(r) - 1, -1, -1):
                if r[x] not in (" ", "") or self.bg[y][x] is not None:
                    w = max(w, x + 1)
                    break
        for rows in (self.chars, self.fg, self.bg):
            for i, r in enumerate(rows):
                del r[w:]
