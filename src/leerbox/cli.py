"""Command-line interface (headless rendering and export).

Examples
  python LeerBox_Text_Art_Studio_V3.py                       # start the GUI
  python LeerBox_Text_Art_Studio_V3.py --text "Hello" --font slant
  python LeerBox_Text_Art_Studio_V3.py --text "Hi" --font big --effect gradient --format png -o hi.png
  python LeerBox_Text_Art_Studio_V3.py --list-fonts --search 3d
  python LeerBox_Text_Art_Studio_V3.py --style fraktur --text "Gothic"
  python LeerBox_Text_Art_Studio_V3.py --image photo.jpg --image-mode braille --cols 120
  python LeerBox_Text_Art_Studio_V3.py --image logo.png --set color=original --set mode=sextant --format png -o out.png
  python LeerBox_Text_Art_Studio_V3.py --image photo.jpg --analyze
  python LeerBox_Text_Art_Studio_V3.py --image photo.jpg --optimize portrait
  python LeerBox_Text_Art_Studio_V3.py --image anim.gif --animate html -o anim.html
"""
from __future__ import annotations

import argparse
import json
import sys

from .effects import DEFAULTS as CLI_FX_DEFAULTS, new_effect
from .export import FORMATS, ExportSettings, export_bytes
from .fontdb import FontManager
from .textart import RenderingEngine, TextOptions
from .unicode_styles import ENCODINGS, STYLE_NAMES, encode, stylize


def resolve_font(fm: FontManager, name: str) -> str:
    if name in fm.entries:
        return name
    for prefix in ("fig:", "tlf:", "ras:", ""):
        if prefix + name in fm.entries:
            return prefix + name
    low = name.lower()
    for fid, e in fm.entries.items():
        if e.name.lower() == low:
            return fid
    hits = fm.search(name)
    if hits:
        return hits[0]
    raise SystemExit(f"font not found: {name}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="leerbox", description="LeerBox Text Art Studio 3.0 — headless mode")
    p.add_argument("--text", "-t", help="text to render (use '-' to read stdin)")
    p.add_argument("--font", "-f", default="standard")
    p.add_argument("--list-fonts", action="store_true")
    p.add_argument("--search", default="")
    p.add_argument("--format", default="txt", choices=sorted(FORMATS))
    p.add_argument("--output", "-o", help="output file (default: stdout for text formats)")
    p.add_argument("--effect", action="append", default=[], help=f"effect name ({', '.join(CLI_FX_DEFAULTS)}) or JSON object")
    p.add_argument("--layout", default="default", choices=["default", "full", "fitted", "smush", "universal"])
    p.add_argument("--width", type=int, default=0)
    p.add_argument("--align", default="left", choices=["left", "center", "right"])
    p.add_argument("--raster-mode", default="block")
    p.add_argument("--style", choices=sorted(STYLE_NAMES), help="apply a Unicode style instead of a font")
    p.add_argument("--encode", choices=sorted(ENCODINGS))
    p.add_argument("--ansi", default="truecolor", choices=["truecolor", "256", "16", "none"])
    p.add_argument("--scale", type=float, default=1.0)
    g = p.add_argument_group("Image Studio (needs NumPy; Pillow for most formats)")
    g.add_argument("--image", help="image file to convert to text art")
    g.add_argument("--image-mode", help="conversion mode (see --list-image-modes)")
    g.add_argument("--cols", type=int, help="output width in characters")
    g.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="any Image Studio parameter")
    g.add_argument("--analyze", action="store_true", help="print the image analysis and recommendations as JSON")
    g.add_argument("--optimize", metavar="PRESET", help="Smart Optimize preset (detail, similarity, readability, small, "
                                                       "terminal, portrait, landscape, logo, braille)")
    g.add_argument("--animate", choices=["html", "gif", "zip", "sh", "ps1"], help="convert every frame of an animation")
    g.add_argument("--list-image-modes", action="store_true")
    g.add_argument("--formats", action="store_true", help="show which image formats can be decoded here")
    return p


def run_image_cli(a) -> int:
    from .imgcore import decode_image, decode_frames, decoder_capabilities
    from .imgmodes import MODES, IMG_PARAMS, render_image_art
    if a.list_image_modes:
        for k, m in MODES.items():
            print(f"{k}	{m[0]}	{m[6]}")
        return 0
    if a.formats:
        print(json.dumps(decoder_capabilities(), indent=1))
        return 0
    params = {}
    for kv in a.set:
        k, _, v = kv.partition("=")
        if k not in IMG_PARAMS:
            raise SystemExit(f"unknown image parameter: {k}")
        params[k] = v
    if a.image_mode:
        params["mode"] = a.image_mode
    if a.cols:
        params["cols"] = a.cols
    with open(a.image, "rb") as fh:
        data = fh.read()
    s = ExportSettings(ansi_mode=a.ansi, scale=a.scale)
    out = None
    if a.animate:
        from .imganim import convert_animation, to_animated_html, to_gif, to_frame_zip, to_ansi_script
        frames, durs, _ = decode_frames(data)
        arts, d2, _ = convert_animation(frames, durs, params)
        out = {"html": lambda: to_animated_html(arts, d2, s).encode("utf-8"), "gif": lambda: to_gif(arts, d2, s),
               "zip": lambda: to_frame_zip(arts, "txt", s, d2),
               "sh": lambda: to_ansi_script(arts, d2, "bash", a.ansi).encode("utf-8"),
               "ps1": lambda: to_ansi_script(arts, d2, "powershell", a.ansi).encode("utf-8")}[a.animate]()
    else:
        img = decode_image(data, a.image)
        if a.analyze:
            from .imganalysis import analyze
            print(json.dumps(analyze(img), indent=1, ensure_ascii=False))
            return 0
        if a.optimize:
            from .imganalysis import optimize, OPT_PRESETS
            if a.optimize not in OPT_PRESETS:
                raise SystemExit(f"unknown preset; choose from {', '.join(OPT_PRESETS)}")
            res = optimize(img, params, a.optimize)
            print(res["note"])
            for r in res["results"]:
                print(f"{r['score']:.3f}  {r['params']['mode']:<12} {r['metrics']}")
            return 0
        art, _ = render_image_art(img, params)
        out = export_bytes(art, a.format, s)
    if a.output:
        with open(a.output, "wb") as fh:
            fh.write(out)
        if sys.stderr is not None:
            print(f"wrote {a.output} ({len(out)} bytes)", file=sys.stderr)
        return 0
    if sys.stdout is None:
        raise SystemExit("no console available: use --output FILE")
    if a.format in ("png", "jpeg", "webp", "bmp") or a.animate in ("gif", "zip"):
        raise SystemExit("binary formats need --output")
    sys.stdout.write(out.decode("utf-8"))
    return 0


def run_cli(argv: list[str]) -> int:
    a = build_parser().parse_args(argv)
    if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass
    if a.image or a.list_image_modes or a.formats:
        return run_image_cli(a)
    if a.list_fonts:
        fm = FontManager()
        for fid in fm.search(a.search):
            e = fm.entries[fid]
            print(f"{fid}\t{e.category}\th{e.height}\t{e.meta.get('licenseTier')}")
        return 0
    text = sys.stdin.read() if a.text == "-" else (a.text if a.text is not None else "LeerBox")
    if a.style:
        print(stylize(text, a.style))
        return 0
    if a.encode:
        print(encode(text, a.encode))
        return 0
    fm = FontManager()
    eng = RenderingEngine(fm)
    fid = resolve_font(fm, a.font)
    effects = []
    for spec in a.effect:
        if spec.strip().startswith("{"):
            obj = json.loads(spec)
            effects.append(new_effect(obj.pop("type"), **obj))
        else:
            effects.append(new_effect(spec))
    o = TextOptions(h_layout=a.layout, width=a.width, align=a.align, raster_mode=a.raster_mode)
    art = eng.render(fid, text, o, effects)
    data = export_bytes(art, a.format, ExportSettings(ansi_mode=a.ansi, scale=a.scale))
    if a.output:
        with open(a.output, "wb") as fh:
            fh.write(data)
        if sys.stderr is not None:  # windowed EXE builds have no console streams
            print(f"wrote {a.output} ({len(data)} bytes)", file=sys.stderr)
    else:
        if sys.stdout is None:
            raise SystemExit("no console available: use --output FILE")
        if a.format in ("png", "jpeg", "webp", "bmp"):
            raise SystemExit("binary formats need --output")
        sys.stdout.write(data.decode("utf-8"))
    return 0


def entry() -> None:
    if len(sys.argv) > 1:
        raise SystemExit(run_cli(sys.argv[1:]))
    from .ui.app import main as gui_main
    gui_main()
