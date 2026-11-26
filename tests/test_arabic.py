"""Arabic shaping, ligatures, diacritics, Persian/Urdu letters and bidirectional reordering."""
import unittest

from helpers import engine

from leerbox.arabic import bidi_class, convert_digits, shape, visual_clusters, visual_text


class TestShaping(unittest.TestCase):
    def test_contextual_forms(self):
        # beh: initial FE91, medial FE92, final FE90, isolated FE8F
        self.assertEqual(shape("ببب"), "ﺑﺒﺐ")
        self.assertEqual(shape("ب"), "ﺏ")

    def test_right_joining_breaks(self):
        # alef does not join to the following letter: "ابا" -> alef isolated, beh initial, alef final
        self.assertEqual(shape("ابا"), "ﺍﺑﺎ")

    def test_lam_alef_ligatures(self):
        self.assertEqual(shape("لا"), "ﻻ")
        self.assertEqual(shape("سلا"), "ﺳﻼ")
        self.assertEqual(shape("لأ"), "ﻷ")
        self.assertEqual(shape("لا", ligatures=False), "ﻟﺎ")

    def test_diacritics_are_transparent(self):
        s = shape("بَب")  # fatha between two behs must not break the join
        self.assertEqual(s, "ﺑَﺐ")

    def test_persian_letters(self):
        s = shape("پچژگ")
        self.assertEqual(s[0], "ﭘ")  # peh initial
        self.assertEqual(s[1], "ﭽ")  # tcheh medial
        self.assertEqual(s[2], "ﮋ")  # jeh final (right-joining)
        self.assertEqual(s[3], "ﮒ")  # gaf isolated (after right-joining jeh)

    def test_zwnj_prevents_joining(self):
        s = shape("ب‌ب")
        self.assertEqual(s, "ﺏ‌ﺏ")

    def test_tatweel_joins(self):
        self.assertEqual(shape("بـ"), "ﺑـ")

    def test_non_arabic_untouched(self):
        self.assertEqual(shape("Hello 123"), "Hello 123")


class TestBidi(unittest.TestCase):
    def test_classes(self):
        self.assertEqual(bidi_class("a"), "L")
        self.assertEqual(bidi_class("ب"), "AL")
        self.assertEqual(bidi_class("א"), "R")
        self.assertEqual(bidi_class("5"), "EN")
        self.assertEqual(bidi_class("٥"), "AN")
        self.assertEqual(bidi_class("َ"), "NSM")

    def test_pure_rtl_reversed(self):
        self.assertEqual("".join(visual_clusters("ابت")), "تبا")

    def test_numbers_keep_ltr_order(self):
        self.assertEqual("".join(visual_clusters("عدد 123")), "123 ددع")

    def test_mixed_ltr_paragraph(self):
        self.assertEqual("".join(visual_clusters("Hi ابت!")), "Hi تبا!")

    def test_brackets_mirrored(self):
        self.assertEqual("".join(visual_clusters("(اب)")), "(با)")

    def test_marks_stay_with_base(self):
        v = visual_clusters("بَت")
        self.assertEqual(v, ["ت", "بَ"])

    def test_against_python_bidi_reference(self):
        try:
            from bidi.algorithm import get_display
        except ImportError:
            self.skipTest("python-bidi not installed (optional reference)")
        samples = ["مرحبا بالعالم", "Hello مرحبا 123", "عدد ١٢٣ و 456", "السلام عليكم!", "abc def", "(قوسين) [x]",
                   "Mixed English، then عربي.", "שלום עולם 2026"]
        for s in samples:
            self.assertEqual("".join(visual_clusters(s)), get_display(s), s)

    def test_against_arabic_reshaper_reference(self):
        try:
            import arabic_reshaper
        except ImportError:
            self.skipTest("arabic-reshaper not installed (optional reference)")
        r = arabic_reshaper.ArabicReshaper({"delete_harakat": False, "support_ligatures": True})
        for s in ["مرحبا", "السلام عليكم", "كتاب", "محمد", "لا إله", "پژوهش"]:
            ours = shape(s)
            ref = r.reshape(s)
            self.assertEqual(ours, ref, s)

    def test_digit_conversion(self):
        self.assertEqual(convert_digits("123", "arabic"), "١٢٣")
        self.assertEqual(convert_digits("١٢٣", "persian"), "۱۲۳")
        self.assertEqual(convert_digits("۱۲۳", "western"), "123")

    def test_visual_text(self):
        self.assertEqual(visual_text("لا"), "ﻻ")


class TestArabicRaster(unittest.TestCase):
    def test_render_connected(self):
        for fid in ("ras:Amiri Bold", "ras:Noto Naskh Arabic Bold", "ras:Noto Kufi Arabic Bold", "ras:Noto Sans Arabic Bold",
                    "ras:Vazirmatn Bold", "ras:Amiri"):
            art = engine().render(fid, "مرحبا", None)
            self.assertGreater(art.width, 20, fid)
            self.assertEqual(engine().unsupported_chars(fid, "مرحبا بالعالم"), [], fid)

    def test_diacritics_add_ink(self):
        from leerbox.textart import TextOptions
        a = engine().render("ras:Amiri Bold", "مدرسة", TextOptions()).to_text().count("█")
        b = engine().render("ras:Amiri Bold", "مَدْرَسَةٌ", TextOptions()).to_text().count("█")
        c = engine().render("ras:Amiri Bold", "مَدْرَسَةٌ", TextOptions(diacritics=False)).to_text().count("█")
        self.assertGreater(b, a)
        self.assertEqual(a, c)


if __name__ == "__main__":
    unittest.main()
