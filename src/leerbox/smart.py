"""Deterministic local "smart" features (no cloud, no randomness unless seeded).

How recommendations are produced
--------------------------------
1. Every candidate font renders the current text (cached by the engine).
2. Fonts that cannot draw every character (after Unicode fallbacks) are dropped.
3. The rendered size (columns × rows) is scored against the chosen target:

   =========  ===============  ==============================================
   target     ideal size       score
   =========  ===============  ==============================================
   terminal   ≤ 80 cols        100 − 3·|h − 6| ; −200 if wider than 80 cols
   wide       ≤ 120 cols       100 − 2·|h − 8| ; −200 if wider than 120 cols
   compact    ≤ 60 cols, h ≤ 4 100 − 25·max(0, h − 3) − 0.5·w
   banner     ≤ 160 cols       60 + 4·min(h, 12) ; −200 if wider than 160 cols
   =========  ===============  ==============================================

   Text length adjusts the target: inputs longer than 24 characters receive a
   bonus for compact heights (≤ 5 rows), inputs of 8 characters or fewer a
   bonus for tall fonts (≥ 8 rows).
4. Ties are broken by font name, so results are reproducible.
"""
from __future__ import annotations

from .effects import Rng, new_effect

TARGETS = {"terminal": 80, "wide": 120, "compact": 60, "banner": 160}

CURATED = [
    ("Neon nights", "fig:ansi_shadow", [{"type": "gradient", "mode": "horizontal", "stops": ["#00e5ff", "#b14cff", "#ff3ea5"]}, {"type": "glow", "color": "#b14cff", "radius": 8}]),
    ("Retro terminal", "fig:big", [{"type": "color", "fg": "#33ff66"}, {"type": "frame", "style": "terminal", "title": "tty1"}, {"type": "glow", "color": "#33ff66", "radius": 5}]),
    ("Sunset slant", "fig:slant", [{"type": "gradient", "mode": "vertical", "stops": ["#ffcf5c", "#ff7a59", "#e04e8a"]}]),
    ("Matrix rain", "fig:banner3", [{"type": "matrix", "density": 0.6}]),
    ("Blueprint", "fig:doom", [{"type": "outline", "char": "·", "color": "#4f7dd1"}, {"type": "color", "fg": "#cfe3ff"}, {"type": "frame", "style": "single", "color": "#4f7dd1"}]),
    ("Gold 3D", "fig:colossal", [{"type": "extrude", "depth": 2, "direction": "se", "char": "▒", "color": "#7a5a12"}, {"type": "gradient", "mode": "vertical", "stops": ["#fff1a8", "#e0a526"]}]),
    ("Vaporwave", "fig:ansi_regular", [{"type": "double_shadow"}, {"type": "rainbow", "mode": "diagonal", "saturation": 0.6, "lightness": 0.7}]),
    ("Gothic manuscript", "fig:gothic", [{"type": "color", "fg": "#d8c7a0"}, {"type": "frame", "style": "double", "color": "#8a6d3b"}]),
    ("Cyber glitch", "fig:electronic", [{"type": "glitch", "amount": 0.3, "shift": 2}, {"type": "gradient", "mode": "horizontal", "stops": ["#00ffd5", "#ff2bd6"]}]),
    ("Bloody horror", "fig:bloody", [{"type": "gradient", "mode": "vertical", "stops": ["#ff4d4d", "#6e0000"]}]),
    ("Isometric ice", "fig:isometric1", [{"type": "gradient", "mode": "diagonal", "stops": ["#e0fbff", "#5ac8fa", "#2f6fed"]}]),
    ("Minimal box", "fig:small", [{"type": "frame", "style": "rounded", "padding": 1}]),
    ("Pixel block", "tlf:pagga", [{"type": "rainbow", "mode": "horizontal", "lightness": 0.6}]),
    ("Shadow pop", "fig:standard", [{"type": "shadow", "dx": 1, "dy": 1, "char": "░", "color": "#4c566a"}, {"type": "color", "fg": "#ffd166"}]),
]


def curated_designs(fonts) -> list[dict]:
    out = []
    for name, fid, effects in CURATED:
        if fid not in fonts.entries:
            fid = "fig:standard"
        out.append({"name": name, "font": fid, "effects": [new_effect(e["type"], **{k: v for k, v in e.items() if k != "type"}) for e in effects]})
    return out


RANDOM_EFFECTS = [
    ("gradient", lambda r: {"mode": ["horizontal", "vertical", "diagonal"][r.int(3)],
                            "stops": [_rand_color(r), _rand_color(r), _rand_color(r)][: 2 + r.int(2)]}),
    ("rainbow", lambda r: {"mode": ["horizontal", "vertical", "diagonal"][r.int(3)], "offset": round(r.next(), 2)}),
    ("shadow", lambda r: {"char": "░▒.:"[r.int(4)]}),
    ("frame", lambda r: {"style": ["rounded", "double", "single", "heavy", "ascii"][r.int(5)]}),
    ("outline", lambda r: {"char": "·.:+"[r.int(4)]}),
    ("extrude", lambda r: {"depth": 1 + r.int(3), "direction": ["se", "sw", "ne", "nw"][r.int(4)]}),
]


def _rand_color(r: Rng) -> str:
    from .effects import hsl
    return f"#{hsl(r.next(), 0.55 + 0.4 * r.next(), 0.5 + 0.2 * r.next()):06x}"


def random_design(fonts, seed: int, pool: list[str] | None = None) -> dict:
    r = Rng(seed)
    ids = pool or [fid for fid, e in fonts.entries.items() if e.type in ("figlet", "toilet")]
    fid = ids[r.int(len(ids))] if ids else "fig:standard"
    effects = []
    color_done = False
    for _ in range(1 + r.int(3)):
        kind, gen = RANDOM_EFFECTS[r.int(len(RANDOM_EFFECTS))]
        if kind in ("gradient", "rainbow"):
            if color_done:
                continue
            color_done = True
        if any(e["type"] == kind for e in effects):
            continue
        effects.append(new_effect(kind, **gen(r)))
    # colour effects last so they also tint shadows/frames
    effects.sort(key=lambda e: e["type"] in ("gradient", "rainbow"))
    return {"font": fid, "effects": effects, "seed": seed}


def score(w: int, h: int, target: str, text_len: int) -> float:
    if w == 0 or h == 0:
        return -1000
    if target == "terminal":
        s = 100 - 3 * abs(h - 6) - (200 if w > 80 else 0)
    elif target == "wide":
        s = 100 - 2 * abs(h - 8) - (200 if w > 120 else 0)
    elif target == "compact":
        s = 100 - 25 * max(0, h - 3) - 0.5 * w - (200 if w > 60 else 0)
    else:  # banner
        s = 60 + 4 * min(h, 12) - (200 if w > 160 else 0)
    if text_len > 24 and h <= 5:
        s += 15
    if text_len <= 8 and h >= 8:
        s += 15
    return s


def recommend(engine, text: str, target: str = "terminal", candidates: list[str] | None = None,
              limit: int = 12, cancel=None) -> list[dict]:
    from .textart import TextOptions
    fonts = engine.fonts
    ids = candidates or [fid for fid, e in fonts.entries.items() if e.type in ("figlet", "toilet")]
    text = text.strip() or "LeerBox"
    out = []
    o = TextOptions()
    for fid in ids:
        if cancel and cancel():
            break
        try:
            if engine.unsupported_chars(fid, text):
                continue
            art = engine.render(fid, text, o)
        except Exception:  # noqa: BLE001 - a broken font must not stop recommendations
            continue
        w, h = art.width, art.height
        out.append({"id": fid, "width": w, "height": h, "score": score(w, h, target, len(text))})
    out.sort(key=lambda r: (-r["score"], fonts.entries[r["id"]].name.lower()))
    return out[:limit]


def compatible_fonts(engine, text: str, ids: list[str]) -> list[str]:
    return [fid for fid in ids if not engine.unsupported_chars(fid, text)]


def preview_scale(art_w: int, art_h: int, avail_w: int, avail_h: int, cell_w: float = 8.4, cell_h: float = 17.0) -> float:
    """Largest zoom (≤ 1.6) that fits the art into the available preview area."""
    if art_w <= 0 or art_h <= 0:
        return 1.0
    z = min(avail_w / (art_w * cell_w), avail_h / (art_h * cell_h), 1.6)
    return max(0.25, round(z, 2))


def width_warning(art_w: int) -> str | None:
    if art_w > 200:
        return f"Output is {art_w} columns wide — it will wrap in most terminals. Try a compact font or a wrap width."
    if art_w > 120:
        return f"Output is {art_w} columns — wider than a 120-column terminal."
    if art_w > 80:
        return f"Output is {art_w} columns — wider than a standard 80-column terminal."
    return None
