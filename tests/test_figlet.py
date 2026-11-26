"""FLF/TLF parsing, FIGlet layout compatibility and smushing rules."""
import io
import unittest
import zipfile

from helpers import MINI_FONT, fm, golden

from leerbox.figlet import (SM_BIGX, SM_EQUAL, SM_HARDBLANK, SM_HIERARCHY, SM_KERN, SM_LOWLINE, SM_PAIR, SM_SMUSH,
                            FontError, RenderOptions, _LineBuilder, char_width, graphemes, parse_font, render_figlet,
                            render_figlet_rows)


class TestReferenceCompatibility(unittest.TestCase):
    def test_pyfiglet_golden(self):
        """Every shared font must match the independent pyfiglet implementation."""
        g = golden("figlet_reference.json")
        self.assertGreater(len(g["cases"]), 2000)
        failures = []
        for c in g["cases"]:
            rows = [r.rstrip() for r in render_figlet_rows(fm().font(c["font"]), c["text"], RenderOptions())]
            while rows and not rows[-1]:
                rows.pop()
            if rows != c["expected"]:
                failures.append(f"{c['font']} {c['text']!r}")
        self.assertEqual(failures, [], f"{len(failures)} mismatches: {failures[:10]}")


class TestParsing(unittest.TestCase):
    def test_minimal_font(self):
        f = parse_font(MINI_FONT, "mini")
        self.assertEqual(f.height, 3)
        self.assertEqual(f.hardblank, "$")
        self.assertEqual(len([c for c in f.glyphs if 32 <= c < 127]), 95)
        self.assertEqual(f.glyphs[ord("A")], [" AA", "|A|", " --"])
        self.assertEqual(f.full_layout, 24463 & 32767)

    def test_old_layout_derivation(self):
        def with_old(v):
            return parse_font(MINI_FONT.replace("flf2a$ 3 2 8 15 1 0 24463", f"flf2a$ 3 2 8 {v} 1"))
        self.assertEqual(with_old(0).full_layout, SM_KERN)
        self.assertEqual(with_old(-1).full_layout, 0)
        self.assertEqual(with_old(15).full_layout, 15 | SM_SMUSH)
        self.assertEqual(with_old(63).full_layout, 31 | SM_SMUSH)  # figlet masks old layout with 31

    def test_hardblank_rendering(self):
        f = parse_font(MINI_FONT)
        self.assertNotIn("$", render_figlet(f, "A B"))

    def test_codetags_hex_octal_decimal_negative(self):
        tail = ("196\n" + "x@\n" * 2 + "x@@\n") * 0
        extra = "0x0100 LATIN A MACRON\nA1@\nA2@\nA3@@\n0256 octal\nB1@\nB2@\nB3@@\n300 decimal\nC1@\nC2@\nC3@@\n-5 negative\nN@\nN@\nN@@\n"
        deutsch = "".join("D@\nD@\nD@@\n" for _ in range(7))
        f = parse_font(MINI_FONT + deutsch + extra + tail)
        self.assertIn(0x100, f.glyphs)
        self.assertIn(0o256, f.glyphs)
        self.assertIn(300, f.glyphs)
        self.assertNotIn(-5, f.glyphs)
        self.assertIn(196, f.glyphs)

    def test_missing_deutsch_detected(self):
        extra = "0x0100 LATIN A MACRON\nA1@\nA2@\nA3@@\n"
        f = parse_font(MINI_FONT + extra)
        self.assertIn(0x100, f.glyphs)
        self.assertNotIn(196, f.glyphs)

    def test_tlf_utf8(self):
        tlf = MINI_FONT.replace("flf2a$", "tlf2a$").replace(" AA@", " █▀@")
        f = parse_font(tlf.encode("utf-8"))
        self.assertEqual(f.kind, "tlf")
        self.assertIn("█▀", f.glyphs[ord("A")][0])

    def test_latin1_flf(self):
        data = MINI_FONT.replace(" ~~@", " \xb4\xb4@").encode("latin-1")
        f = parse_font(data)
        self.assertEqual(f.glyphs[ord("~")][0], " ´´")

    def test_zipped_font(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("mini.flf", MINI_FONT)
        self.assertEqual(parse_font(buf.getvalue()).height, 3)

    def test_malformed_fonts_rejected(self):
        for bad in (b"", b"hello", b"flf2a$ 0 0 0 0 0\n", b"flf2a$ 999 1 1 0 0\n", b"flf2a$ 3 2 8 0 abc\n",
                    b"flf2a$ 3 2 8 0 5\nonly one line\n", b"flf2a$ 3\n", b"PK\x03\x04garbage"):
            with self.assertRaises((FontError, ValueError), msg=bad[:20]):
                parse_font(bad)

    def test_oversized_rejected(self):
        with self.assertRaises(FontError):
            parse_font(b"flf2a$ 3 2 8 0 0\n" + b"x" * (7 * 1024 * 1024))


class TestSmushing(unittest.TestCase):
    def builder(self, mode):
        f = parse_font(MINI_FONT)
        b = _LineBuilder(f, mode, False, 0)
        b.prev_w = b.cur_w = 3
        return b

    def test_rules(self):
        cases = [(SM_EQUAL, "|", "|", "|"), (SM_LOWLINE, "_", "/", "/"), (SM_LOWLINE, "[", "_", "["),
                 (SM_HIERARCHY, "|", "/", "/"), (SM_HIERARCHY, "{", "(", "("), (SM_HIERARCHY, "<", "]", "<"), (SM_HIERARCHY, "]", "<", "<"),
                 (SM_PAIR, "[", "]", "|"), (SM_PAIR, ")", "(", "|"), (SM_BIGX, "/", "\\", "|"), (SM_BIGX, "\\", "/", "Y"),
                 (SM_BIGX, ">", "<", "X"), (SM_HARDBLANK, "$", "$", "$")]
        for rule, l, r, exp in cases:
            self.assertEqual(self.builder(rule | SM_SMUSH).smush_chars(l, r), exp, (rule, l, r))

    def test_no_smush_without_rule(self):
        self.assertIsNone(self.builder(SM_EQUAL | SM_SMUSH).smush_chars("/", "\\"))
        self.assertIsNone(self.builder(SM_BIGX | SM_SMUSH).smush_chars("<", ">"))
        self.assertIsNone(self.builder(SM_KERN).smush_chars("a", "b"))

    def test_universal(self):
        b = self.builder(SM_SMUSH)
        self.assertEqual(b.smush_chars("a", "b"), "b")
        self.assertEqual(b.smush_chars("$", "b"), "b")
        self.assertEqual(b.smush_chars("a", "$"), "a")

    def test_layout_widths_ordered(self):
        f = fm().font("fig:standard")
        w = {lay: max(len(r) for r in render_figlet_rows(f, "Hello World", RenderOptions(h_layout=lay)))
             for lay in ("full", "fitted", "smush")}
        self.assertGreater(w["full"], w["fitted"])
        self.assertGreaterEqual(w["fitted"], w["smush"])

    def test_vertical_smushing_reduces_height(self):
        f = fm().font("fig:standard")
        full = render_figlet_rows(f, "A\nB", RenderOptions(v_layout="full"))
        smushed = render_figlet_rows(f, "A\nB", RenderOptions(v_layout="smush"))
        self.assertEqual(len(full), 2 * f.height)
        self.assertLess(len(smushed), len(full))


class TestLayoutOptions(unittest.TestCase):
    def test_wrap(self):
        f = fm().font("fig:standard")
        rows = render_figlet_rows(f, "the quick brown fox jumps over the lazy dog", RenderOptions(width=60))
        self.assertTrue(all(len(r) <= 60 for r in rows))
        self.assertGreater(len(rows), f.height)

    def test_alignment(self):
        f = fm().font("fig:standard")
        rows = render_figlet_rows(f, "I", RenderOptions(align="right", width=40))
        self.assertTrue(all(len(r) == 40 for r in rows if r.strip()))

    def test_rtl_reverses_order(self):
        f = fm().font("fig:standard")
        ltr = render_figlet_rows(f, "AB", RenderOptions(direction="ltr"))
        rtl = render_figlet_rows(f, "BA", RenderOptions(direction="rtl"))
        def dedent(rows):
            rows = [r.rstrip() for r in rows]
            ind = min((len(r) - len(r.lstrip()) for r in rows if r.strip()), default=0)
            return [r[ind:] for r in rows]
        self.assertEqual(dedent(ltr), dedent(rtl))  # same glyph order; leading trim differs by direction

    def test_unicode_fallback(self):
        f = fm().font("fig:standard")
        self.assertEqual(render_figlet(f, "é"), render_figlet(f, "e") if 233 not in f.glyphs else render_figlet(f, "é"))
        self.assertEqual(render_figlet(f, "ȩ"), render_figlet(f, "e"))  # NFKD base letter fallback

    def test_graphemes_and_width(self):
        self.assertEqual(graphemes("éx"), ["é", "x"])
        self.assertEqual(graphemes("🇸🇦!"), ["🇸🇦", "!"])
        self.assertEqual(graphemes("👍🏽"), ["👍🏽"])
        self.assertEqual(char_width("全"), 2)
        self.assertEqual(char_width("́"), 0)

    def test_input_limit(self):
        f = fm().font("fig:term") if "fig:term" in fm().entries else fm().font("fig:standard")
        out = render_figlet_rows(f, "x" * 10000, RenderOptions(max_input=100))
        self.assertLess(max(len(r) for r in out), 100 * f.max_width + 10)


if __name__ == "__main__":
    unittest.main()
