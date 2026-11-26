"""Performance measurements for both editions' engines. Usage: python tools/benchmark.py > perf.json"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def t(fn, n=1):
    t0 = time.perf_counter()
    for _ in range(n):
        r = fn()
    return (time.perf_counter() - t0) / n * 1000, r


def main() -> None:
    res = {"platform": platform.platform(), "python": sys.version.split()[0], "cpu": platform.processor()}
    from leerbox import fontdb
    from leerbox.effects import new_effect
    from leerbox.export import ExportSettings, export_bytes
    from leerbox.imageart import ImageData, ImageOptions, image_to_art
    from leerbox.textart import RenderingEngine, TextOptions
    res["pack_load_ms"], fm = t(lambda: fontdb.FontManager())
    ids = list(fm.order)
    res["fonts"] = len(ids)
    res["parse_all_fonts_ms"], _ = t(lambda: [fm.font(i) for i in ids])
    eng = RenderingEngine(fm)
    o = TextOptions()
    ms, _ = t(lambda: [eng.render(i, "LeerBox", o, use_cache=False) for i in ids])
    res["render_all_fonts_ms"] = ms
    res["render_per_font_avg_ms"] = ms / len(ids)
    res["render_cached_all_fonts_ms"], _ = t(lambda: [eng.render(i, "LeerBox", o) for i in ids])
    long_text = "The quick brown fox jumps over the lazy dog " * 4
    res["render_long_text_standard_ms"], _ = t(lambda: eng.render("fig:standard", long_text, o, use_cache=False), 5)
    res["render_wrapped_80_ms"], _ = t(lambda: eng.render("fig:standard", long_text, TextOptions(width=80), use_cache=False), 3)
    res["render_arabic_raster_ms"], _ = t(lambda: eng.render("ras:Amiri Bold", "السلام عليكم ورحمة الله", TextOptions(raster_mode="half"), use_cache=False), 5)
    fx = [new_effect("extrude"), new_effect("gradient"), new_effect("frame"), new_effect("glow")]
    res["effects_pipeline_ms"], art = t(lambda: eng.render("fig:big", "Effects", o, fx, use_cache=False), 5)
    for fmt in ("txt", "ansi", "svg", "html", "png", "jpeg", "webp"):
        res[f"export_{fmt}_ms"], _ = t(lambda: export_bytes(art, fmt, ExportSettings()), 3)
    res["export_png_scale4_ms"], _ = t(lambda: export_bytes(art, "png", ExportSettings(scale=4)))
    W, H = 800, 600
    img = ImageData(W, H, [((x * 255 // W) << 16) | ((y * 255 // H) << 8) | 128 for y in range(H) for x in range(W)])
    res["image_to_ascii_800x600_120cols_ms"], _ = t(lambda: image_to_art(img, ImageOptions(cols=120)))
    res["image_to_braille_floyd_ms"], _ = t(lambda: image_to_art(img, ImageOptions(cols=120, mode="braille", dither="floyd")))
    res["search_fuzzy_ms"], _ = t(lambda: fm.search("bannr"), 20)
    sizes = {}
    for f in ("LeerBox_Text_Art_Studio_V3.py", "LeerBox_Text_Art_Studio_V3.html", "dist/LeerBox_Text_Art_Studio_V3.exe",
              "legacy_v2/LeerBox_Text_Art_Studio_V2.py", "legacy_v2/LeerBox_Text_Art_Studio_V2.html", "src/leerbox/data/fontpack.bin"):
        p = ROOT / f
        if p.exists():
            sizes[f] = p.stat().st_size
    res["file_sizes"] = sizes
    node = shutil.which("node")
    if node:
        js = r"""
const LB=require(process.argv[1]+'/dist/leerbox_engine.js'),fs=require('fs');
LB.resources={arabicTables:JSON.parse(fs.readFileSync(process.argv[1]+'/src/leerbox/data/arabic_tables.json','utf8'))};
const T=(f,n=1)=>{const t=performance.now();let r;for(let i=0;i<n;i++)r=f();return [(performance.now()-t)/n,r];};
const out={node:process.version};
const packed=new Uint8Array(fs.readFileSync(process.argv[1]+'/src/leerbox/data/fontpack.bin'));
let [ms,raw]=T(()=>LB.inflateZlib(packed)); out.js_inflate_pack_ms=ms;
const fm=new LB.FontManager(); [ms]=T(()=>fm.loadPack(raw)); out.index_load_ms=ms;
[ms]=T(()=>fm.order.map(i=>fm.font(i))); out.parse_all_fonts_ms=ms;
const eng=new LB.Engine(fm);
[ms]=T(()=>fm.order.map(i=>LB.renderFont(fm.font(i),'LeerBox',LB.textOptions({})))); out.render_all_fonts_ms=ms; out.render_per_font_avg_ms=ms/fm.order.length;
const fx=['extrude','gradient','frame','glow'].map(k=>LB.effects.newEffect(k));
[ms]=T(()=>LB.effects.applyEffects(LB.renderFont(fm.font('fig:big'),'Effects',LB.textOptions({})),fx),5); out.effects_pipeline_ms=ms;
[ms]=T(()=>LB.renderFont(fm.font('ras:Amiri Bold'),'السلام عليكم ورحمة الله',LB.textOptions({raster_mode:'half'})),5); out.render_arabic_raster_ms=ms;
[ms]=T(()=>fm.search('bannr'),20); out.search_fuzzy_ms=ms;
console.log(JSON.stringify(out));
"""
        r = subprocess.run([node, "-e", js, str(ROOT)], capture_output=True, timeout=600)
        try:
            res["javascript"] = json.loads(r.stdout.decode())
        except ValueError:
            res["javascript_error"] = r.stderr.decode()[-500:]
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    os.chdir(ROOT)
    main()
