"""Built distributions: standalone Python script, single-file HTML, cross-edition JS suite, offline guarantees."""
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from helpers import ROOT, engine, tmpdir

from leerbox.export import to_txt
from leerbox.textart import TextOptions

PY = ROOT / "LeerBox_Text_Art_Studio_V3.py"
HTML = ROOT / "LeerBox_Text_Art_Studio_V3.html"


class TestStandalonePython(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = Path(tmpdir())
        shutil.copy(PY, cls.dir / PY.name)  # isolated copy: no access to src/

    def run_cli(self, *args):
        r = subprocess.run([sys.executable, "-I", str(self.dir / PY.name), *args], capture_output=True, cwd=self.dir,
                           env={"PYTHONIOENCODING": "utf-8", "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")}, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace"))
        return r.stdout.decode("utf-8")

    def test_same_output_as_modular_engine(self):
        for font, text in (("standard", "Bundle"), ("slant", "Test 123"), ("Amiri Bold", "مرحبا")):
            fid = {"standard": "fig:standard", "slant": "fig:slant", "Amiri Bold": "ras:Amiri Bold"}[font]
            expected = to_txt(engine().render(fid, text, TextOptions()))
            self.assertEqual(self.run_cli("--text", text, "--font", font).replace("\r\n", "\n"), expected)

    def test_png_export_and_listing(self):
        out = self.dir / "x.png"
        self.run_cli("--text", "Hi", "--font", "big", "--effect", "gradient", "--format", "png", "-o", str(out))
        self.assertEqual(out.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        listing = self.run_cli("--list-fonts")
        self.assertGreaterEqual(len(listing.strip().split("\n")), 900)

    def test_no_network_imports(self):
        src = PY.read_text(encoding="utf-8")
        for mod in ("urllib.request", "http.client", "socket", "requests", "ftplib", "smtplib"):
            self.assertNotRegex(src, rf"^\s*(import|from)\s+{re.escape(mod)}\b", mod)
        self.assertNotIn("eval(", src)


class TestHtml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = HTML.read_text(encoding="utf-8")

    def test_self_contained_offline(self):
        self.assertIn("Content-Security-Policy", self.html)
        self.assertIn("default-src 'none'", self.html)
        self.assertNotRegex(self.html, r'(?:src|href)\s*=\s*["\']https?://')
        self.assertNotRegex(self.html, r"@import\s+url\(\s*['\"]?https?://")
        self.assertNotIn("adguard", self.html.lower())
        self.assertNotIn("'unsafe-eval'", self.html)

    def test_no_dynamic_code(self):
        scripts = re.findall(r"<script[^>]*>(.*?)</script>", self.html, flags=re.S)
        code = "\n".join(s for s in scripts if len(s) < 2_000_000)  # skip base64 payloads
        self.assertNotRegex(code, r"\beval\s*\(")
        self.assertNotRegex(code, r"new\s+Function\s*\(")

    def test_size_reasonable(self):
        self.assertLess(len(self.html.encode("utf-8")), 8 * 1024 * 1024)


class TestCrossEditionJs(unittest.TestCase):
    def test_node_suite(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js not installed")
        r = subprocess.run([node, str(ROOT / "tests" / "js" / "run_tests.js")], capture_output=True, timeout=600)
        out = r.stdout.decode("utf-8", "replace")
        self.assertEqual(r.returncode, 0, out[-2000:])
        self.assertIn("0 failed", out)


if __name__ == "__main__":
    unittest.main()
