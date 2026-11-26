"""Effects, gradients, transformations, exports, image conversion, projects and Unicode tools."""
import io
import json
import os
import shutil
import subprocess
import unittest
import xml.dom.minidom
from pathlib import Path

from helpers import engine, tmpdir

from leerbox import export as ex
from leerbox.art import Art
from leerbox.effects import DEFAULTS, Rng, apply_effects, gradient_color, new_effect, pipeline_representation
from leerbox.imageart import ImageData, ImageOptions, image_to_art
from leerbox.project import ProjectError, make_project, parse_project
from leerbox.textart import TextOptions
from leerbox.unicode_styles import STYLE_NAMES, decode, encode, stylize, text_box


def art():
    return engine().render("fig:standard", "Hi!", TextOptions())


class TestEffects(unittest.TestCase):
    def test_every_effect_runs_nondestructively(self):
        base = art()
        before = base.to_text()
        for kind in DEFAULTS:
            out = apply_effects(base, [new_effect(kind)])
            self.assertGreater(out.width, 0, kind)
        self.assertEqual(base.to_text(), before)

    def test_disabled_effect_ignored(self):
        e = new_effect("frame")
        e["enabled"] = False
        self.assertEqual(apply_effects(art(), [e]).to_text(), art().to_text())

    def test_order_matters(self):
        a = apply_effects(art(), [new_effect("frame"), new_effect("shadow")])
        b = apply_effects(art(), [new_effect("shadow"), new_effect("frame")])
        self.assertNotEqual(a.to_text(), b.to_text())

    def test_transform_identities(self):
        t = art().to_text()
        self.assertEqual(apply_effects(art(), [new_effect("mirror"), new_effect("mirror")]).to_text(), t)
        self.assertEqual(apply_effects(art(), [new_effect("flip_v"), new_effect("flip_v")]).to_text(), t)
        r = apply_effects(art(), [new_effect("rotate", angle=90)] * 4)
        self.assertEqual(r.to_text(), t)
        self.assertEqual(apply_effects(art(), [new_effect("rotate", angle=180)] * 2).to_text(), t)

    def test_gradient_endpoints(self):
        self.assertEqual(gradient_color([0xFF0000, 0x0000FF], 0), 0xFF0000)
        self.assertEqual(gradient_color([0xFF0000, 0x0000FF], 1), 0x0000FF)
        self.assertEqual(gradient_color([0x000000, 0xFFFFFF], 0.5), 0x808080)
        out = apply_effects(art(), [new_effect("gradient", stops=["#ff0000", "#0000ff"])])
        cols = [c for r in out.fg for c in r if c is not None]
        self.assertIn(0xFF0000, cols)

    def test_rng_reference_values(self):
        r = Rng(1)
        self.assertEqual([round(r.next(), 10) for _ in range(3)], [0.6270739406, 0.0027357212, 0.52744704])

    def test_random_effects_deterministic(self):
        for kind in ("noise", "glitch", "matrix", "zalgo"):
            a = apply_effects(art(), [new_effect(kind)]).to_text()
            b = apply_effects(art(), [new_effect(kind)]).to_text()
            self.assertEqual(a, b, kind)

    def test_representation_flags(self):
        rep = pipeline_representation([new_effect("gradient"), new_effect("glow"), new_effect("frame")])
        self.assertFalse(rep["plain_text"])
        self.assertIn("Glow", rep["lossy_in_text"])

    def test_effect_size_limit(self):
        big = Art.blank(1500, 1300)
        big.chars[0][0] = "x"
        with self.assertRaises(ValueError):
            apply_effects(big, [new_effect("padding", top=50, bottom=50, left=50, right=50)])


class TestExports(unittest.TestCase):
    def setUp(self):
        self.a = apply_effects(art(), [new_effect("gradient"), new_effect("glow"), new_effect("frame")])

    def test_all_formats_valid(self):
        from PIL import Image
        for fmt in ex.FORMATS:
            data = ex.export_bytes(self.a, fmt)
            self.assertGreater(len(data), 50, fmt)
            if fmt in ("png", "jpeg", "webp", "bmp"):
                im = Image.open(io.BytesIO(data))
                im.verify()
            if fmt == "svg":
                xml.dom.minidom.parseString(data)
            if fmt == "html":
                self.assertTrue(data.startswith(b"<!doctype html>"))

    def test_transparent_png(self):
        from PIL import Image
        im = Image.open(io.BytesIO(ex.export_bytes(self.a, "png", ex.ExportSettings(transparent=True))))
        self.assertEqual(im.mode, "RGBA")
        self.assertEqual(im.getpixel((0, 0))[3], 0)

    def test_scale_changes_resolution(self):
        from PIL import Image
        s1 = Image.open(io.BytesIO(ex.export_bytes(self.a, "png", ex.ExportSettings(scale=1)))).size
        s2 = Image.open(io.BytesIO(ex.export_bytes(self.a, "png", ex.ExportSettings(scale=2)))).size
        self.assertAlmostEqual(s2[0] / s1[0], 2, delta=0.05)

    def test_fallback_raster_without_pillow(self):
        from PIL import Image
        saved = ex.HAVE_PILLOW
        ex.HAVE_PILLOW = False
        try:
            for fmt in ("png", "bmp"):
                Image.open(io.BytesIO(ex.export_bytes(self.a, fmt))).verify()
            with self.assertRaises(RuntimeError):
                ex.export_bytes(self.a, "jpeg")
        finally:
            ex.HAVE_PILLOW = saved

    def test_ansi_modes(self):
        self.assertIn("\x1b[0;38;2;", ex.to_ansi(self.a, "truecolor"))
        self.assertIn("38;5;", ex.to_ansi(self.a, "256"))
        self.assertRegex(ex.to_ansi(self.a, "16"), r"\x1b\[0;(3[0-7]|9[0-7])m")
        self.assertEqual(ex.rgb_to_256(0xFF0000), 196)
        self.assertEqual(ex.rgb_to_16(0xFFFFFF), 15)

    def test_code_literals_reproduce_text(self):
        expected = ex.to_txt(self.a)
        d = tmpdir()
        py = ex.to_code(self.a, "python")
        ns = {}
        exec(compile(py.replace("print(ART, end=\"\")", ""), "art.py", "exec"), ns)  # our own generated code, test only
        self.assertEqual(ns["ART"], expected)
        node = shutil.which("node")
        if node:
            p = os.path.join(d, "a.js")
            open(p, "w", encoding="utf-8").write(ex.to_code(self.a, "javascript"))
            out = subprocess.run([node, p], capture_output=True).stdout.decode("utf-8")
            self.assertEqual(out, expected)
        for cc, lang in (("gcc", "c"), ("g++", "cpp")):
            exe = shutil.which(cc)
            if not exe:
                continue
            src = os.path.join(d, f"a.{lang}")
            open(src, "w", encoding="utf-8").write(ex.to_code(self.a, lang))
            binp = os.path.join(d, f"a_{lang}.exe")
            subprocess.run([exe, src, "-o", binp], check=True)
            self.assertEqual(subprocess.run([binp], capture_output=True).stdout.decode("utf-8"), expected)
        pwsh = shutil.which("pwsh") or shutil.which("powershell")
        if pwsh:
            p = os.path.join(d, "a.ps1")
            open(p, "w", encoding="utf-8-sig").write(ex.to_code(self.a, "powershell"))
            r = subprocess.run([pwsh, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                                f"[Console]::OutputEncoding=[Text.Encoding]::UTF8; . '{p}'"], capture_output=True)
            self.assertEqual(r.stdout.decode("utf-8").replace("\r\n", "\n"), expected)
        bash = shutil.which("bash")
        if bash:  # C:\Windows\System32\bash.exe is the WSL launcher and may have no distro: probe first
            try:
                probe = subprocess.run([bash, "-c", "echo ok"], capture_output=True, timeout=20).stdout.strip()
            except (OSError, subprocess.TimeoutExpired):
                probe = b""
            if probe != b"ok":
                git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
                bash = str(git_bash) if git_bash.exists() else None
        if bash:
            p = os.path.join(d, "a.sh")
            script = ex.to_code(self.a, "bash").encode("utf-8")  # via stdin: works for Git Bash and WSL alike
            self.assertEqual(subprocess.run([bash, "-s"], input=script, capture_output=True).stdout.decode("utf-8"), expected)

    def test_markdown_fence(self):
        md = ex.to_markdown(Art.from_text("a```b"))
        self.assertTrue(md.startswith("````text"))


class TestImageArt(unittest.TestCase):
    def img(self):
        W, H = 40, 20
        return ImageData(W, H, [(int(255 * x / (W - 1)) * 0x010101) for y in range(H) for x in range(W)])

    def test_ascii_monotonic(self):
        a = image_to_art(self.img(), ImageOptions(cols=40, mode="ascii", ramp="standard"))
        row = "".join(a.chars[0])
        ramp = " .:-=+*#%@"
        idx = [ramp.index(c) for c in row]
        self.assertEqual(idx, sorted(idx, reverse=True))  # dark (left) -> dense, light (right) -> sparse

    def test_modes_and_dithering(self):
        for mode in ("ascii", "blocks", "half", "quarter", "braille"):
            for dither in ("none", "floyd", "atkinson", "ordered"):
                a = image_to_art(self.img(), ImageOptions(cols=30, mode=mode, dither=dither))
                self.assertEqual(a.width, 30)

    def test_color_mapping(self):
        a = image_to_art(self.img(), ImageOptions(cols=20, mode="half", color="truecolor"))
        self.assertTrue(a.has_color())

    def test_invert(self):
        a = image_to_art(self.img(), ImageOptions(cols=20)).to_text()
        b = image_to_art(self.img(), ImageOptions(cols=20, invert=True)).to_text()
        self.assertNotEqual(a, b)

    def test_pillow_loader_limits(self):
        from leerbox.imageart import load_image
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (30, 10), (255, 0, 0)).save(buf, "PNG")
        img = load_image(buf.getvalue())
        self.assertEqual((img.width, img.height), (30, 10))
        with self.assertRaises(Exception):
            load_image(b"not an image")


class TestProjects(unittest.TestCase):
    def test_roundtrip(self):
        p = make_project("Hello", "fig:slant", "slant", TextOptions(h_layout="full", width=40),
                         [new_effect("gradient"), new_effect("frame")], {"scale": 2})
        q = parse_project(json.dumps(p))
        self.assertEqual(q["text"], "Hello")
        self.assertEqual(q["options"].h_layout, "full")
        self.assertEqual([e["type"] for e in q["effects"]], ["gradient", "frame"])

    def test_malicious_project_sanitized(self):
        evil = {"format": "leerbox-text-art-project", "version": 3, "text": "x" * 99999,
                "font": {"id": "fig:standard", "name": 5}, "options": {"width": "99999999", "h_layout": {"a": 1}},
                "effects": [{"type": "__import__", "x": 1}, {"type": "frame", "style": ["x"] * 9, "padding": 1e99}],
                "export": {"scale": [1, 2]}}
        q = parse_project(json.dumps(evil))
        self.assertEqual(len(q["text"]), 5000)
        self.assertEqual(len(q["effects"]), 1)
        self.assertLessEqual(q["options"].width, 10000)

    def test_rejects(self):
        for bad in (b"{", b"[]", json.dumps({"format": "other"}).encode(), json.dumps({"format": "leerbox-text-art-project", "version": 99}).encode()):
            with self.assertRaises(ProjectError):
                parse_project(bad)


class TestUnicodeTools(unittest.TestCase):
    def test_styles(self):
        self.assertEqual(stylize("Az9", "bold"), "𝐀𝐳𝟗")
        self.assertEqual(stylize("Hh", "italic"), "𝐻ℎ")
        self.assertEqual(stylize("CHR", "fraktur"), "ℭℌℜ")
        self.assertEqual(stylize("NZ", "double_struck"), "ℕℤ")
        self.assertEqual(stylize("ab", "fullwidth"), "ａｂ")
        self.assertEqual(stylize("a1", "circled"), "ⓐ①")
        for k in STYLE_NAMES:
            self.assertTrue(stylize("Hello", k))

    def test_encoders_roundtrip(self):
        s = "LeerBox Ä€"
        for k in ("binary", "hex", "base64"):
            self.assertEqual(decode(encode(s, k), k), s)
        self.assertEqual(encode("SOS", "morse"), "... --- ...")
        self.assertEqual(decode("... --- ...", "morse"), "SOS")
        self.assertEqual(encode("ab 12", "braille"), "⠁⠃ ⠼⠁⠃")

    def test_text_box_alignment(self):
        b = text_box("a\nbbb", "single", 1, "center").split("\n")
        self.assertEqual(len({len(x) for x in b}), 1)


if __name__ == "__main__":
    unittest.main()
