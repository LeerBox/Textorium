"""Animation-to-Art, typographic compositions, comparison exports and Image Studio projects."""
from __future__ import annotations

import base64
import html
import io
import json
import math
import time
import zipfile

from .art import Art, hex_to_rgb, split_rgb
from .export import ExportSettings, render_image, to_ansi, to_html_fragment, to_txt
from .imgcore import RasterImage, composite, decode_image, luminance, np, require_numpy, resample_area
from .imgmodes import MODES, RenderCancelled, render_image_art, sanitize_params, plan_grid

MAX_ANIM_FRAMES_OUT = 600


# ---------------------------------------------------------------------- animation conversion
def select_frames(n: int, start: int = 0, end: int = -1, step: int = 1) -> list[int]:
    end = n - 1 if end < 0 or end >= n else end
    start = max(0, min(start, end))
    step = max(1, step)
    return list(range(start, end + 1, step))[:MAX_ANIM_FRAMES_OUT]


def convert_animation(frames: list[RasterImage], durations: list[int], params: dict, start: int = 0, end: int = -1,
                      step: int = 1, fps: float = 0.0, cancel=None, progress=None):
    """Convert selected frames with the Image Studio settings. Returns (arts, durations_ms, stats)."""
    require_numpy()
    idx = select_frames(len(frames), start, end, step)
    p = sanitize_params(params)
    arts, durs = [], []
    t0 = time.perf_counter()
    for k, i in enumerate(idx):
        if cancel is not None and cancel():
            raise RenderCancelled()
        art, _ = render_image_art(frames[i], p)
        arts.append(art)
        if fps > 0:
            durs.append(int(round(1000 / fps)))
        else:  # frame skipping keeps the original timing by summing skipped durations
            durs.append(sum(durations[j] for j in range(i, min(len(frames), i + max(1, step)))))
        if progress:
            progress(k + 1, len(idx))
    return arts, durs, {"frames": len(arts), "ms": round((time.perf_counter() - t0) * 1000), "mode": p["mode"]}


def to_animated_html(arts: list[Art], durs: list[int], s: ExportSettings | None = None, loop: bool = True,
                     title: str = "LeerBox Animation") -> str:
    """Self-contained HTML page with an inline player (no network access, no external files)."""
    s = s or ExportSettings()
    frames = [to_html_fragment(a, s) for a in arts]
    data = json.dumps({"frames": frames, "durations": [max(10, int(d)) for d in durs], "loop": bool(loop)})
    data = data.replace("</", "<\\/").replace("<!--", "<\\!--")
    bg = "transparent" if s.transparent else html.escape(s.background)
    return ("<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; script-src 'unsafe-inline'; "
            "style-src 'unsafe-inline'\">"
            f"<title>{html.escape(title)}</title><style>body{{margin:0;background:{bg};color:#ccc;font:13px system-ui}}"
            "#bar{position:fixed;bottom:8px;right:8px;opacity:.8}button{font:inherit}</style></head><body>"
            "<div id=\"stage\"></div><div id=\"bar\"><button id=\"pp\">Pause</button> <span id=\"fi\"></span></div>"
            f"<script>var D={data};var i=0,playing=true,t=null,st=document.getElementById('stage'),fi=document.getElementById('fi');"
            "function show(){st.innerHTML=D.frames[i];fi.textContent=(i+1)+'/'+D.frames.length;}"
            "function step(){show();t=setTimeout(function(){i++;if(i>=D.frames.length){if(!D.loop){i=D.frames.length-1;return;}i=0;}"
            "if(playing)step();},D.durations[i]);}"
            "document.getElementById('pp').onclick=function(){playing=!playing;this.textContent=playing?'Pause':'Play';"
            "if(playing){clearTimeout(t);step();}};step();</script></body></html>\n")


def to_gif(arts: list[Art], durs: list[int], s: ExportSettings | None = None, loop: bool = True) -> bytes:
    """Animated GIF of the rendered text art (Pillow)."""
    from PIL import Image
    s = s or ExportSettings()
    imgs = [render_image(a, s) for a in arts]
    W = max(i.width for i in imgs); H = max(i.height for i in imgs)
    bg = split_rgb(hex_to_rgb(s.background))
    out = []
    for im in imgs:
        base = Image.new("RGBA", (W, H), (*bg, 255))
        base.alpha_composite(im)
        out.append(base.convert("RGB").quantize(colors=255, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE))
    buf = io.BytesIO()
    out[0].save(buf, "GIF", save_all=True, append_images=out[1:], duration=[max(20, int(d)) for d in durs],
                loop=0 if loop else 1, disposal=1, optimize=False)
    return buf.getvalue()


def to_frame_zip(arts: list[Art], fmt: str = "txt", s: ExportSettings | None = None, durs: list[int] | None = None) -> bytes:
    """ZIP with one file per frame (txt, ans or png) plus a JSON timing manifest."""
    from .export import export_bytes
    s = s or ExportSettings()
    buf = io.BytesIO()
    ext = {"txt": "txt", "ansi": "ans", "png": "png", "svg": "svg", "html": "html"}[fmt]
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for i, a in enumerate(arts):
            z.writestr(f"frame_{i + 1:04d}.{ext}", export_bytes(a, fmt, s))
        z.writestr("frames.json", json.dumps({"frames": len(arts), "durations_ms": list(durs or [100] * len(arts)),
                                             "format": ext}, indent=1))
    return buf.getvalue()


def to_ansi_script(arts: list[Art], durs: list[int], shell: str = "bash", mode: str = "truecolor", loop: bool = True) -> str:
    """Terminal player script. Frames contain only SGR colour codes (sanitised); the script adds cursor-home."""
    frames = [to_ansi(a, mode) for a in arts]
    if shell == "powershell":
        lines = ["# LeerBox ANSI animation (PowerShell 7+). Ctrl+C to stop.", "$e = [char]27", "$frames = @("]
        for f in frames:
            body = f.replace("'", "''").replace("\x1b", "' + $e + '")
            lines.append(f"  ('{body}'),")
        lines[-1] = lines[-1].rstrip(",")
        lines += [")", f"$delays = @({', '.join(str(max(10, int(d))) for d in durs)})",
                  "[Console]::Write(\"$e[2J$e[?25l\")", "try {", "  do {",
                  "    for ($i = 0; $i -lt $frames.Count; $i++) {",
                  "      [Console]::Write(\"$e[H\" + $frames[$i]); Start-Sleep -Milliseconds $delays[$i]", "    }",
                  f"  }} while (${'true' if loop else 'false'})", "} finally { [Console]::Write(\"$e[0m$e[?25h\") }", ""]
        return "\n".join(lines)
    out = ["#!/usr/bin/env bash", "# LeerBox ANSI animation. Ctrl+C to stop.", "frames=()"]
    for f in frames:
        out.append("frames+=(" + "$'" + f.replace("\\", "\\\\").replace("'", "\\'").replace("\x1b", "\\e")
                   .replace("\n", "\\n") + "')")
    out.append("delays=(" + " ".join(f"{max(10, int(d)) / 1000:.3f}" for d in durs) + ")")
    body = ["for i in \"${!frames[@]}\"; do", "  printf '\\e[H%s' \"${frames[$i]}\"", "  sleep \"${delays[$i]}\"", "done"]
    out += ["trap 'printf \"\\e[0m\\e[?25h\\n\"; exit' INT TERM", "printf '\\e[2J\\e[?25l'"]
    out += (["while :; do"] + ["  " + b for b in body] + ["done"]) if loop else body
    out += ["printf '\\e[0m\\e[?25h\\n'", ""]
    return "\n".join(out)


# ---------------------------------------------------------------------- typographic composition (graphical)
def compose_typographic(src: RasterImage, params: dict, font_size: float = 12.0, vary: str = "opacity",
                        rotate: int = 0, max_side: int = 2400) -> dict:
    """Graphical composition: the phrase is set as lines of real text whose colour, opacity, size or weight
    follow the image. This is a *graphic* (PNG/SVG), not monospaced text art."""
    require_numpy()
    from .figlet import char_width
    from .imgmodes import _text_stream
    p = sanitize_params(params)
    fs = max(4.0, min(64.0, float(font_size)))
    cw, lh = fs * 0.6021, fs * 1.15
    img = src
    if rotate == 90:
        from .imgcore import rotate90
        img = rotate90(src, 270)
    scale = min(1.0, max_side / max(img.width, img.height))
    W, H = img.width * scale, img.height * scale
    cols, rows = max(4, int(W / cw)), max(2, int(H / lh))
    smp = resample_area(img, cols, rows)
    rgb = composite(smp, 0xFFFFFF if not p["light_on_dark"] else 0x000000)
    L = luminance(rgb)
    stream, rtl = _text_stream(p["text"], p["text_dir"])
    runs, k = [], 0
    for y in range(rows):
        xs = range(cols - 1, -1, -1) if rtl else range(cols)
        for x in xs:
            if p["transparent_bg"] and smp.a[y, x] < 0.5:
                continue
            g, w = stream[k % len(stream)]
            k += 1
            if not g.strip():
                continue
            v = float(L[y, x])
            ink = v if p["light_on_dark"] else 1 - v
            r8 = [int(round(c * 255)) for c in rgb[y, x]]
            color = "#%02x%02x%02x" % tuple(r8) if p["color"] != "none" else ("#ffffff" if p["light_on_dark"] else "#000000")
            run = {"x": round(x * cw, 2), "y": round(y * lh + fs, 2), "ch": g, "color": color, "alpha": 1.0,
                   "size": fs, "bold": False}
            if vary == "opacity":
                run["alpha"] = round(max(0.06, ink), 3)
            elif vary == "size":
                run["size"] = round(fs * (0.35 + 0.9 * ink), 2)
            elif vary == "weight":
                run["bold"] = ink > 0.5
                run["alpha"] = round(max(0.15, ink), 3)
            runs.append(run)
    return {"kind": "typographic-composition", "width": round(cols * cw, 2), "height": round(rows * lh, 2),
            "background": "#000000" if p["light_on_dark"] else "#ffffff", "font_size": fs, "rotate": rotate,
            "rtl": rtl, "runs": runs}


def composition_svg(comp: dict) -> str:
    W, H = comp["width"], comp["height"]
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
           f'<rect width="100%" height="100%" fill="{comp["background"]}"/>',
           '<g font-family="DejaVu Sans Mono, Consolas, monospace">']
    for r in comp["runs"]:
        out.append(f'<text x="{r["x"]}" y="{r["y"]}" font-size="{r["size"]}" fill="{r["color"]}"'
                   + (f' fill-opacity="{r["alpha"]}"' if r["alpha"] < 1 else "")
                   + (' font-weight="bold"' if r["bold"] else "") + f'>{html.escape(r["ch"], quote=False)}</text>')
    out.append("</g></svg>\n")
    svg = "".join(out)
    if comp.get("rotate") == 90:
        svg = svg.replace('<g font-family', f'<g transform="rotate(90 {W / 2} {H / 2})" font-family', 1)
    return svg


def composition_png(comp: dict, scale: float = 1.0) -> bytes:
    from PIL import Image, ImageDraw, ImageFont
    import zlib
    from .resources import load_resource
    W, H = int(comp["width"] * scale + 0.5), int(comp["height"] * scale + 0.5)
    img = Image.new("RGBA", (W, H), (*split_rgb(hex_to_rgb(comp["background"])), 255))
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    data = zlib.decompress(load_resource("DejaVuSans.ttf.z"))
    fonts = {}
    for r in comp["runs"]:
        sz = max(3, int(r["size"] * scale + 0.5))
        f = fonts.get(sz)
        if f is None:
            f = fonts[sz] = ImageFont.truetype(io.BytesIO(data), sz)
        col = split_rgb(hex_to_rgb(r["color"]))
        a = int(255 * r["alpha"])
        pos = (r["x"] * scale, r["y"] * scale)
        d.text(pos, r["ch"], font=f, fill=(*col, a), anchor="ls",
               stroke_width=1 if r["bold"] else 0, stroke_fill=(*col, a))
    img.alpha_composite(layer)
    if comp.get("rotate") == 90:
        img = img.rotate(-90, expand=True)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------- comparison export
def comparison_png(src: RasterImage, art: Art, s: ExportSettings | None = None, layout: str = "side") -> bytes:
    """Original image and the rendered text art side by side (or stacked)."""
    from PIL import Image
    s = s or ExportSettings()
    art_img = render_image(art, s)
    h = art_img.height
    w = max(1, int(src.width * h / src.height + 0.5))
    if layout == "stack":
        w = art_img.width
        h = max(1, int(src.height * w / src.width + 0.5))
    rgba = Image.frombytes("RGBA", (src.width, src.height), src.to_rgba_bytes()).resize((w, h), Image.Resampling.LANCZOS)
    bg = (*split_rgb(hex_to_rgb(s.background)), 255)
    gap = max(8, int(16 * s.scale))
    if layout == "stack":
        out = Image.new("RGBA", (art_img.width, h + gap + art_img.height), bg)
        out.alpha_composite(rgba, (0, 0)); out.alpha_composite(art_img, (0, h + gap))
    else:
        out = Image.new("RGBA", (w + gap + art_img.width, max(h, art_img.height)), bg)
        out.alpha_composite(rgba, (0, 0)); out.alpha_composite(art_img, (w + gap, 0))
    buf = io.BytesIO()
    out.save(buf, "PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------- Image Studio projects
MAX_PROJECT_IMAGE = 25 * 1024 * 1024


def make_image_project(params: dict, image_bytes: bytes | None, image_name: str = "", effects: list | None = None,
                       export: dict | None = None, workspace: str = "image") -> str:
    if image_bytes is not None and len(image_bytes) > MAX_PROJECT_IMAGE:
        image_bytes = None  # too large to embed; the project then stores settings only
    d = {"format": "leerbox-image-project", "version": 1, "workspace": workspace,
         "params": sanitize_params(params), "effects": effects or [], "export": export or {},
         "image": ({"name": image_name[:200], "data": base64.b64encode(image_bytes).decode("ascii")}
                   if image_bytes is not None else None)}
    return json.dumps(d, ensure_ascii=False)


def parse_image_project(text: str | bytes) -> dict:
    from .project import ProjectError, sanitize_effects
    if isinstance(text, bytes):
        if len(text) > 40 * 1024 * 1024:
            raise ProjectError("project file too large")
        text = text.decode("utf-8", "replace")
    try:
        d = json.loads(text)
    except ValueError as exc:
        raise ProjectError(f"invalid project: {exc}") from exc
    if not isinstance(d, dict) or d.get("format") != "leerbox-image-project":
        raise ProjectError("not a LeerBox image project")
    out = {"workspace": d.get("workspace") if d.get("workspace") in ("image", "animation") else "image",
           "params": sanitize_params(d.get("params") if isinstance(d.get("params"), dict) else {}),
           "effects": sanitize_effects(d.get("effects", [])),
           "export": d.get("export") if isinstance(d.get("export"), dict) else {}, "image": None, "image_name": ""}
    im = d.get("image")
    if isinstance(im, dict) and isinstance(im.get("data"), str):
        try:
            raw = base64.b64decode(im["data"], validate=True)
        except ValueError as exc:
            raise ProjectError("embedded image is not valid base64") from exc
        if len(raw) > MAX_PROJECT_IMAGE:
            raise ProjectError("embedded image too large")
        out["image"] = raw
        out["image_name"] = str(im.get("name", ""))[:200]
    return out


# ---------------------------------------------------------------------- batch
def batch_convert(items: list[tuple[str, bytes]], params: dict, fmt: str, s: ExportSettings | None = None,
                  cancel=None, progress=None) -> tuple[bytes, list[dict]]:
    """Convert several images with the same settings into one ZIP. Returns (zip bytes, per-file report)."""
    from .export import export_bytes, FORMATS
    s = s or ExportSettings()
    buf = io.BytesIO()
    report = []
    ext = FORMATS[fmt][1]
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for i, (name, data) in enumerate(items):
            if cancel is not None and cancel():
                raise RenderCancelled()
            base = (name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].rsplit(".", 1)[0] or f"image{i + 1}")[:80]
            try:
                img = decode_image(data, name)
                art, st = render_image_art(img, params)
                z.writestr(f"{i + 1:03d}_{base}{ext}", export_bytes(art, fmt, s))
                report.append({"name": name, "ok": True, "cols": st["cols"], "rows": st["rows"], "ms": st["ms"]})
            except Exception as exc:  # report and continue with the next file
                report.append({"name": name, "ok": False, "error": str(exc)})
            if progress:
                progress(i + 1, len(items))
        z.writestr("batch_report.json", json.dumps(report, indent=1))
    return buf.getvalue(), report
