"""Build the single self-contained LeerBox_Text_Art_Studio_V3.html.

Everything is inlined: CSS, the JavaScript engine, the application, the worker
source, the zlib-compressed font pack (base64), the Arabic shaping tables and
DejaVu Sans Mono (base64). The page makes no network requests; a strict
Content-Security-Policy forbids them. Also writes dist/leerbox_engine.js (the
concatenated engine, CommonJS-compatible) for the Node-based test-suite.
"""
from __future__ import annotations

import base64
import json
import re
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web" / "src"
DATA = ROOT / "src" / "leerbox" / "data"
OUT = ROOT / "LeerBox_Text_Art_Studio_V3.html"


def js_safe(src: str) -> str:
    # an inline <script> must never contain "</script" or "<!--"
    return src.replace("</script", "<\\/script").replace("<!--", "<\\!--")


def main() -> None:
    engine_files = sorted((WEB / "engine").glob("*.js"))
    engine = "\n".join(p.read_text(encoding="utf-8") for p in engine_files)
    app = (WEB / "app.js").read_text(encoding="utf-8")
    worker = (WEB / "worker.js").read_text(encoding="utf-8")
    istudio = (WEB / "imagestudio.js").read_text(encoding="utf-8")
    css = (WEB / "app.css").read_text(encoding="utf-8")
    for name, src in (("engine", engine), ("app", app), ("worker", worker), ("imagestudio", istudio)):
        if re.search(r"\beval\s*\(|new\s+Function\s*\(", src):
            raise SystemExit(f"unsafe dynamic code construct found in {name}")
    pack = (DATA / "fontpack.bin").read_bytes()  # already zlib-compressed
    mono = zlib.decompress((DATA / "DejaVuSansMono.ttf.z").read_bytes())
    arabic = (DATA / "arabic_tables.json").read_text(encoding="utf-8")
    glyphs = (DATA / "glyph_masks.json").read_text(encoding="utf-8")
    manifest = json.loads((ROOT / "FONT_MANIFEST.json").read_text(encoding="utf-8"))
    genuine = manifest["counts"]["genuineFigletToilet"]
    version = re.search(r'__version__ = "([^"]+)"', (ROOT / "src" / "leerbox" / "__init__.py").read_text()).group(1)
    tpl = (WEB / "index.template.html").read_text(encoding="utf-8")
    html = (tpl.replace("{{VERSION}}", version.rsplit(".", 1)[0])
               .replace("{{GENUINE}}", str(genuine))
               .replace("{{CSS}}", css)
               .replace("{{ARABIC_TABLES}}", js_safe(arabic))
               .replace("{{GLYPH_MASKS}}", js_safe(glyphs))
               .replace("{{PACK_B64}}", base64.b64encode(pack).decode("ascii"))
               .replace("{{MONO_B64}}", base64.b64encode(mono).decode("ascii"))
               .replace("{{ENGINE}}", js_safe(engine))
               .replace("{{WORKER}}", js_safe(worker))
               .replace("{{IMAGESTUDIO}}", js_safe(istudio))
               .replace("{{APP}}", js_safe(app)))
    leftovers = re.findall(r"\{\{[A-Z_]+\}\}", html)
    if leftovers:
        raise SystemExit(f"unreplaced placeholders: {leftovers}")
    for bad in ("http://", "https://"):
        # URLs may appear only inside metadata strings (manifest repo links), never as loadable resources
        for m in re.finditer(r'(?:src|href)\s*=\s*["\']' + re.escape(bad), html):
            raise SystemExit(f"external resource reference found at {m.start()}")
    OUT.write_text(html, encoding="utf-8", newline="\n")
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    (dist / "leerbox_engine.js").write_text(engine, encoding="utf-8", newline="\n")
    print(f"wrote {OUT.name}: {len(html.encode('utf-8')):,} bytes (font pack {len(pack):,} B compressed)")


if __name__ == "__main__":
    main()
