import unittest

from scripts import sync_vocabulary as sync


class SourceKeyTests(unittest.TestCase):
    def test_extracts_unique_annotation_keys_from_html(self):
        source = (
            '<a href="zotero://open-pdf/library/items/A?page=1&amp;annotation=abc123">one</a>'
            '<a href="zotero://open-pdf/library/items/B?page=2&annotation=ABC123">two</a>'
        )
        self.assertEqual(sync._keys_from_source(source), ["ABC123"])

    def test_split_keys_is_stable_and_unique(self):
        self.assertEqual(sync._split_keys("abc123 DEF456 abc123"), ["ABC123", "DEF456"])


if __name__ == "__main__":
    unittest.main()
