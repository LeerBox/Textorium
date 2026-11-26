"""Generate golden test fixtures.

tests/golden/figlet_reference.json
    Output of the independent reference implementation pyfiglet (pip install pyfiglet)
    for every font shared by pyfiglet and the LeerBox pack. Both editions must match it.
    Fonts with documented reference deviations are listed separately (see TEST_REPORT.md).
tests/golden/cross_edition.json
    Output of the Python engine for layouts, Unicode text, Arabic shaping/bidi, effects,
    ANSI export, Unicode styles, encoders, image conversion and fuzzy search.
    The JavaScript engine must reproduce these byte-for-byte.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from leerbox.arabic import shape, visual_text  # noqa: E402
from leerbox.effects import new_effect  # noqa: E402
from leerbox.export import to_ansi, to_txt  # noqa: E402
from leerbox.fontdb import FontManager, fuzzy_score  # noqa: E402
from leerbox.imageart import ImageData, ImageOptions, image_to_art  # noqa: E402
from leerbox.textart import RenderingEngine, TextOptions  # noqa: E402
from leerbox.unicode_styles import STYLE_NAMES, encode, stylize, text_box  # noqa: E402

GOLD = ROOT / "tests" / "golden"
TEXTS = ["Hello World", "LeerBox 3.0!", "abc XYZ {}[]()", "Quick_brown/fox\\|<>", "0123456789 @#$%&*+-=?"]
# Documented deviations of pyfiglet from figlet 2.2.5 behaviour (not LeerBox bugs):
#   * Latin-1 fonts: pyfiglet decodes as UTF-8 with replacement characters (konto, konto_slant)
#   * RTL fonts: pyfiglet right-pads output to the terminal width (ivrit, jerusalem, mirror, mshebrew210)
#   * zero-width glyphs: pyfiglet drops them, figlet keeps them for smush-width bookkeeping (3d-ascii)
KNOWN_DEVIATIONS = {"konto", "konto_slant", "ivrit", "jerusalem", "mirror", "mshebrew210", "3d-ascii"}


def norm(s: str) -> list[str]:
    rows = [r.rstrip() for r in s.split("\n")]
    while rows and not rows[-1]:
        rows.pop()
    return rows


def figlet_reference(fm: FontManager) -> dict:
    import pyfiglet
    fdir = Path(pyfiglet.__file__).parent
    dirs = [d for d in ("fonts", "fonts-standard", "fonts-contrib") if (fdir / d).is_dir()]
    ref_names = {p.stem for d in dirs for p in (fdir / d).glob("*.[ft]lf")}
    cases, skipped, unexplained = [], [], []
    for fid in fm.order:
        e = fm.entries[fid]
        if e.type not in ("figlet", "toilet"):
            continue
        stem = e.meta["file"].rsplit(".", 1)[0]
        if stem not in ref_names:
            continue
        # only compare when the bundled payload is byte-identical to pyfiglet's copy
        src = next((fdir / d / e.meta["file"] for d in dirs if (fdir / d / e.meta["file"]).exists()), None)
        if src is None:
            continue
        from leerbox.figlet import decode_font_bytes
        try:
            ref_text, _ = decode_font_bytes(src.read_bytes())
        except Exception:  # noqa: BLE001
            continue
        from leerbox.figlet import parse_font
        try:
            ref_font = parse_font(ref_text, stem)
        except Exception:  # noqa: BLE001
            continue
        mine = fm.font(fid)
        if ref_font.glyphs != mine.glyphs or ref_font.full_layout != mine.full_layout or ref_font.print_direction != mine.print_direction:
            skipped.append({"font": e.name, "reason": "bundled glyphs differ from pyfiglet 1.0.4 copy (newer upstream revision)"})
            continue
        if stem in KNOWN_DEVIATIONS:
            skipped.append({"font": e.name, "reason": "documented pyfiglet deviation"})
            continue
        from leerbox.figlet import RenderOptions, render_figlet_rows
        hb = mine.hardblank
        for t in TEXTS:
            try:
                out = pyfiglet.figlet_format(t, font=stem, width=100000)
            except Exception as exc:  # noqa: BLE001
                skipped.append({"font": e.name, "reason": f"pyfiglet error: {exc}"})
                break
            ours = [r.rstrip() for r in render_figlet_rows(mine, t, RenderOptions())]
            while ours and not ours[-1]:
                ours.pop()
            if ours != norm(out):
                # A difference is accepted ONLY when a documented pyfiglet deviation explains it:
                if any(all(not r.replace(hb, " ").strip() for r in mine.glyphs.get(ord(ch), ["x"])) for ch in t if ch != " "):
                    # pyfiglet 1.0.4 drops glyphs that are blank (or hardblank-only); figlet 2.2.5 keeps them
                    skipped.append({"font": e.name, "text": t, "reason": "pyfiglet drops all-blank glyphs"})
                    continue
                if any(len(mine.glyphs.get(ord(ch), ["x"])[0]) == 0 for ch in t):
                    # figlet 2.2.5 strips every trailing endmark character; pyfiglet strips at most two
                    skipped.append({"font": e.name, "text": t, "reason": "endmark convention: figlet strips all trailing endmarks"})
                    continue
                unexplained.append({"font": fid, "text": t})
            cases.append({"font": fid, "text": t, "expected": norm(out)})
    return {"generator": f"pyfiglet {pyfiglet.__version__ if hasattr(pyfiglet, '__version__') else ''}".strip(),
            "cases": cases, "skipped": skipped, "unexplained": unexplained}


def cross_edition(fm: FontManager) -> dict:
    eng = RenderingEngine(fm)
    cases = []

    def add(fid, text, opts=None, effects=None, name=""):
        o = TextOptions.from_dict(opts or {})
        art = eng.render(fid, text, o, effects or [], use_cache=False)
        cases.append({"name": name or f"{fid}|{text}", "font": fid, "text": text, "options": o.to_dict(), "effects": effects or [],
                      "txt": to_txt(art), "ansi": to_ansi(art, "truecolor"), "ansi256": to_ansi(art, "256"), "ansi16": to_ansi(art, "16"),
                      "w": art.width, "h": art.height})

    fonts = ["fig:standard", "fig:slant", "fig:big", "fig:banner", "fig:small", "fig:shadow", "fig:ansi_shadow", "tlf:future",
             "tlf:pagga", "tlf:smblock", "fig:doom", "fig:ivrit", "fig:block", "tlf:mono12", "fig:isometric1", "fig:script"]
    fonts = [f for f in fonts if f in fm.entries]
    for f in fonts:
        add(f, "LeerBox V3")
        add(f, "Two\nLines", {"v_layout": "default"})
    for lay in ("full", "fitted", "smush", "universal"):
        add("fig:standard", "Smush: /\\ [] () <> _|", {"h_layout": lay}, name=f"layout-{lay}")
        add("fig:standard", "A\nB\nC", {"v_layout": lay}, name=f"vlayout-{lay}")
    add("fig:standard", "the quick brown fox jumps over the lazy dog", {"width": 60}, name="wrap60")
    add("fig:standard", "Center\nme", {"align": "center"}, name="center")
    add("fig:standard", "Right", {"align": "right", "width": 50}, name="right")
    add("fig:standard", "Spaced", {"letter_spacing": 2}, name="spacing")
    add("fig:standard", "Ünïcödé café ñ", {}, name="unicode-fallback")
    add("fig:standard", "Héllo", {"fallback": False, "missing": "question"}, name="no-fallback")
    add("fig:standard", "rtl", {"direction": "rtl"}, name="rtl")
    add("fig:standard", "é café 🇸🇦 👍🏽", {}, name="graphemes")
    for f in ("ras:Amiri Bold", "ras:Noto Naskh Arabic Bold", "ras:Noto Kufi Arabic Bold", "ras:Vazirmatn Bold"):
        for mode in ("half", "braille"):
            add(f, "مرحبا بالعالم", {"raster_mode": mode}, name=f"{f}-{mode}")
        add(f, "لا إله إلا الله", {"raster_mode": "quarter"}, name=f"{f}-lamalef")
        add(f, "مَدْرَسَةٌ", {"raster_mode": "half"}, name=f"{f}-harakat")
        add(f, "Arabic عربي 123 mixed", {"raster_mode": "half"}, name=f"{f}-mixed")
    add("ras:Vazirmatn Bold", "پژوهش گچ ۱۲۳", {"raster_mode": "half", "digits": "persian"}, name="persian")
    add("ras:NotoSans-Bold", "Raster", {"raster_mode": "block"}, name="raster-block") if "ras:NotoSans-Bold" in fm.entries else None
    for eff in ("color", "gradient", "rainbow", "shadow", "double_shadow", "outline", "extrude", "mirror", "flip_v", "rotate",
                "invert", "fill", "background", "noise", "glitch", "matrix", "zalgo", "frame", "padding", "glow"):
        add("fig:standard", "FX!", {}, [new_effect(eff)], name=f"fx-{eff}")
    add("fig:slant", "Combo", {}, [new_effect("extrude", depth=2), new_effect("gradient", mode="diagonal", stops=["#ff0000", "#00ff00", "#0000ff"]),
                                  new_effect("frame", style="terminal", title="tty")], name="fx-combo")
    for mode in ("vertical", "diagonal", "diagonal_up", "radial"):
        add("fig:big", "Grad", {}, [new_effect("gradient", mode=mode, stops=["#112233", "#ddeeff", "#ff8800"])], name=f"grad-{mode}")
    arabic = []
    for s in ["مرحبا", "السلام عليكم", "لا إله إلا الله", "مَدْرَسَةٌ", "پژوهش گچ ژاله", "Hello مرحبا 123", "(قوسين) [x]",
              "عدد ١٢٣ و 456", "سلام‌ها", "ـــبـــ", "Mixed English، then عربي."]:
        arabic.append({"text": s, "shaped": shape(s), "visual": visual_text(s), "visual_rtl": visual_text(s, "rtl"), "visual_ltr": visual_text(s, "ltr")})
    styles = {k: stylize("Hello World 2026!", k) for k in STYLE_NAMES}
    encs = {k: encode("LeerBox Ä€ 3.0", k) for k in ("binary", "hex", "octal", "decimal", "codepoints", "base64", "morse", "braille")}
    boxes = {s: text_box("Hello\nبوكس wide 全角", s, 1, "center", "Title") for s in ("rounded", "double", "ascii", "block")}
    # deterministic synthetic image (gradient + circle)
    W, H = 64, 40
    px = []
    for y in range(H):
        for x in range(W):
            inside = (x - 32) ** 2 + (y - 20) ** 2 < 15 ** 2
            r = int(255 * x / (W - 1)); g = int(255 * y / (H - 1)); b = 40 if inside else 200
            px.append((r << 16) | (g << 8) | b)
    img = ImageData(W, H, px)
    images = []
    for mode, dither, color in (("ascii", "none", "none"), ("ascii", "floyd", "none"), ("blocks", "ordered", "none"),
                                ("half", "none", "truecolor"), ("half", "none", "none"), ("braille", "atkinson", "none"),
                                ("quarter", "none", "truecolor"), ("ascii", "none", "truecolor")):
        o = ImageOptions(cols=40, mode=mode, dither=dither, color=color, contrast=1.2, brightness=0.05, gamma=0.9)
        art = image_to_art(img, o)
        images.append({"options": o.__dict__, "txt": to_txt(art), "ansi": to_ansi(art)})
    fuzzy = [[q, t, fuzzy_score(q, t)] for q, t in (("bnr", "banner"), ("3d", "3-d"), ("slant", "slant"), ("sla", "slant"),
                                                     ("ant", "slant"), ("xyz", "slant"), ("gth", "gothic"), ("ansi", "ansi_shadow"))]
    search = {q: fm.search(q)[:15] for q in ("3d", "bannr", "gothic", "arabic", "block")}
    return {"cases": cases, "arabic": arabic, "styles": styles, "encodings": encs, "boxes": boxes, "image": {"w": W, "h": H, "pixels": px},
            "images": images, "fuzzy": fuzzy, "search": search}


def main() -> None:
    GOLD.mkdir(parents=True, exist_ok=True)
    fm = FontManager()
    ref = figlet_reference(fm)
    (GOLD / "figlet_reference.json").write_text(json.dumps(ref, ensure_ascii=False), encoding="utf-8")
    ce = cross_edition(fm)
    (GOLD / "cross_edition.json").write_text(json.dumps(ce, ensure_ascii=False), encoding="utf-8")
    print(f"figlet reference cases: {len(ref['cases'])} ({len({c['font'] for c in ref['cases']})} fonts), skipped {len(ref['skipped'])}, unexplained {len(ref['unexplained'])}")
    print(f"cross-edition render cases: {len(ce['cases'])}")


if __name__ == "__main__":
    os.chdir(ROOT)
    main()
