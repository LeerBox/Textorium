"""Font collection integrity, imports, ZIP safety, duplicate detection and injection hardening."""
import io
import json
import os
import unittest
import zipfile

from helpers import MINI_FONT, ROOT, fm, tmpdir

from leerbox.art import Art
from leerbox.export import ExportSettings, to_ansi, to_html, to_svg, to_txt
from leerbox.figlet import glyph_hash_key
from leerbox.fontdb import FontManager, fuzzy_score


class TestCollection(unittest.TestCase):
    def test_counts_match_manifest(self):
        m = json.loads((ROOT / "FONT_MANIFEST.json").read_text(encoding="utf-8"))
        st = fm().stats()
        self.assertEqual(st["genuine"], m["counts"]["genuineFigletToilet"])
        self.assertGreaterEqual(st["genuine"], 400)

    def test_every_font_parses_and_renders(self):
        bad = []
        for fid in fm().order:
            try:
                f = fm().font(fid)
                from leerbox.textart import TextOptions, render_font
                render_font(f, "Ab1", TextOptions())
            except Exception as exc:  # noqa: BLE001
                bad.append(f"{fid}: {exc}")
        self.assertEqual(bad, [])

    def test_no_duplicate_glyph_sets(self):
        seen = {}
        dups = []
        for fid in fm().order:
            e = fm().entries[fid]
            if e.type not in ("figlet", "toilet"):
                continue
            f = fm().font(fid)
            k = glyph_hash_key(f) + f":{f.print_direction}:{f.full_layout}"
            if k in seen:
                dups.append((seen[k], fid))
            seen[k] = fid
        self.assertEqual(dups, [])

    def test_metadata_complete(self):
        for fid in fm().order:
            m = fm().entries[fid].meta
            for key in ("name", "source", "license", "licenseTier", "height", "category"):
                self.assertIn(key, m, fid)
            self.assertIn(m["licenseTier"], ("clear", "unstated"))

    def test_search(self):
        self.assertEqual(fm().search("standard")[0], "fig:standard")
        self.assertIn("fig:banner", fm().search("bannr")[:3])
        self.assertTrue(all(fm().entries[f].category == "Arabic" or "Arabic" in fm().entries[f].tags
                            for f in fm().search("", category="Arabic")))
        self.assertGreater(fuzzy_score("bnr", "banner"), 0)
        self.assertEqual(fuzzy_score("xyz", "banner"), 0)


class TestImports(unittest.TestCase):
    def setUp(self):
        self.dir = tmpdir()
        self.m = FontManager(user_dir=self.dir)

    def test_import_valid_persist_reload_remove(self):
        r = self.m.import_bytes(MINI_FONT.encode(), "mini.flf")
        self.assertTrue(r["ok"], r)
        self.assertIn(r["id"], self.m.entries)
        m2 = FontManager(user_dir=self.dir)
        self.assertIn(r["id"], m2.entries)
        self.assertTrue(m2.remove_user(r["id"]))
        self.assertNotIn(r["id"], FontManager(user_dir=self.dir).entries)

    def test_duplicate_of_builtin_rejected(self):
        data = self.m.payload(self.m.entries["fig:standard"])
        r = self.m.import_bytes(data, "standard_copy.flf")
        self.assertFalse(r["ok"])
        self.assertEqual(r.get("duplicate"), "fig:standard")

    def test_malformed_rejected(self):
        for blob in (b"not a font", b"flf2a$ 3 2 8 0 0\nshort\n", b"\x00" * 100):
            self.assertFalse(self.m.import_bytes(blob, "bad.flf")["ok"])

    def test_zip_import_and_safety(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("fonts/mini.flf", MINI_FONT)
            z.writestr("../evil.flf", MINI_FONT.replace("mini", "evil"))
            z.writestr("C:/abs.flf", MINI_FONT)
            z.writestr("bomb.flf", "flf2a$ 1 1 1 0 0\n" + " " * (5 * 1024 * 1024))
            z.writestr("readme.txt", "ignored")
        res = self.m.import_zip(buf.getvalue())
        by = {os.path.basename(r["file"]): r for r in res}
        self.assertTrue(by["mini.flf"]["ok"])
        self.assertIn("unsafe path", by["evil.flf"]["error"])
        self.assertIn("unsafe path", by["abs.flf"]["error"])
        self.assertIn("ratio", by["bomb.flf"]["error"])
        self.assertFalse(any("readme" in r["file"] for r in res))
        self.assertFalse(os.path.exists(os.path.join(self.dir, "..", "evil.flf")))

    def test_invalid_zip(self):
        self.assertFalse(self.m.import_zip(b"PK\x03\x04 broken")[0]["ok"])

    def test_export_collection_roundtrip(self):
        path = os.path.join(self.dir, "c.zip")
        n = self.m.export_collection(["fig:standard", "fig:slant", "tlf:future", "ras:Amiri"], path)
        self.assertEqual(n, 3)
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            self.assertIn("MANIFEST.json", names)
            self.assertEqual(z.read("standard.flf"), self.m.payload(self.m.entries["fig:standard"]))

    def test_reset(self):
        self.m.import_bytes(MINI_FONT.encode(), "a.flf")
        self.assertEqual(self.m.reset_user(), 1)


class TestInjection(unittest.TestCase):
    def test_control_chars_stripped(self):
        a = Art.from_text("ok\x1b[31mred\x07\x9b2J")
        self.assertNotIn("\x1b", to_txt(a))
        self.assertNotIn("\x07", to_txt(a))
        self.assertEqual(to_ansi(Art.from_text("\x1b]0;evil\x07"), "none").strip(), "]0;evil")

    def test_html_svg_escaped(self):
        a = Art.from_text('<script>alert("x")</script> & </pre>')
        h = to_html(a, ExportSettings())
        s = to_svg(a, ExportSettings())
        self.assertNotIn("<script>", h)
        self.assertNotIn("<script>", s)
        self.assertIn("&lt;script&gt;", h)
        import xml.dom.minidom
        xml.dom.minidom.parseString(s)

    def test_color_values_validated(self):
        from leerbox.effects import apply_effects, new_effect
        a = Art.from_text("X")
        with self.assertRaises(ValueError):
            apply_effects(a, [new_effect("color", fg='red" onload="evil')])

    def test_imported_font_with_escape_sequences(self):
        evil = MINI_FONT.replace(" AA@", " \x1b[2J@")
        f = FontManager(user_dir=tmpdir())
        r = f.import_bytes(evil.encode(), "evil.flf")
        self.assertTrue(r["ok"])
        from leerbox.textart import RenderingEngine
        out = to_ansi(RenderingEngine(f).render(r["id"], "A"), "truecolor")
        self.assertNotIn("\x1b[2J", out)


if __name__ == "__main__":
    unittest.main()
