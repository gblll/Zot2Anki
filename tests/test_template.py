import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT / "anki-template"


class VocabularyTemplateContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.front = (TEMPLATE_DIR / "front.html").read_text(encoding="utf-8")
        cls.back = (TEMPLATE_DIR / "back.html").read_text(encoding="utf-8")
        cls.css = (TEMPLATE_DIR / "styling.css").read_text(encoding="utf-8")

    def test_pronunciation_uses_flags_and_dialect_classes(self):
        self.assertIn("pronunciation-uk", self.css)
        self.assertIn("pronunciation-us", self.css)
        self.assertIn('content: "🇬🇧"', self.css)
        self.assertIn('content: "🇺🇸"', self.css)

    def test_part_of_speech_palette_is_present(self):
        self.assertIn(".z2a-pos-noun", self.css)
        self.assertIn(".z2a-pos-adjective", self.css)
        self.assertIn(".z2a-pos-verb", self.css)

    def test_theme_state_uses_anki_persistence_on_both_sides(self):
        for template in (self.front, self.back):
            self.assertIn("window.Persistence", template)
            self.assertIn('persistenceKey = "selectedTheme"', template)
            self.assertIn('window.Persistence.setItem(persistenceKey, theme)', template)

    def test_spacing_and_word_size_are_present(self):
        self.assertIn("font-size: 36px", self.css)
        self.assertIn("padding: 5px 10px", self.css)
        self.assertIn("border-radius: 12px", self.css)


if __name__ == "__main__":
    unittest.main()
