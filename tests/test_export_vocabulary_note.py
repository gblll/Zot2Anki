from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from scripts import export_vocabulary_note as exporter


class VocabularyNoteParserTests(unittest.TestCase):
    def test_parses_standard_paragraph_and_preserves_source(self):
        records = exporter.parse_note_html(
            '<p><a href="zotero://open-pdf/library/items/AAAA?page=2&amp;annotation=BBBB">readiness</a>: '
            '<code>🔉 英 [ˈredinəs] n. 准备就绪</code></p>'
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].front, "readiness")
        self.assertEqual(records[0].href, "zotero://open-pdf/library/items/AAAA?page=2&annotation=BBBB")
        self.assertEqual(records[0].definition_html, "🔉 英 [ˈredinəs] n. 准备就绪")
        self.assertEqual(records[0].review_reasons, [])

    def test_preserves_multiple_code_blocks_as_html_breaks_and_flags_review(self):
        records = exporter.parse_note_html(
            '<p><a href="zotero://open-pdf/library/items/A?annotation=B">word</a>: '
            '<code>英 [wɜːd]</code><br><code>n. 单词</code></p>'
        )
        self.assertEqual(records[0].definition_html, "英 [wɜːd]<br>n. 单词")
        self.assertIn("multiple_code_blocks", records[0].review_reasons)

    def test_preserves_unwrapped_definition_and_flags_review(self):
        records = exporter.parse_note_html(
            '<p><a href="zotero://open-pdf/library/items/A?annotation=B">violet</a>: n. 紫罗兰</p>'
        )
        self.assertEqual(records[0].definition_html, "n. 紫罗兰")
        self.assertEqual(records[0].review_reasons, ["definition_without_code"])

    def test_skips_empty_paragraph_and_merges_nfkc_casefold_duplicates(self):
        records = exporter.parse_note_html(
            '<p><a href="zotero://open-pdf/library/items/A?annotation=1">Ａpple</a>: <code>苹果</code></p>'
            '<p><a href="zotero://open-pdf/library/items/B?annotation=2">apple</a>: <code>苹果树的果实</code></p>'
            '<p>&nbsp;</p>'
        )
        cards, stats = exporter.build_cards(records)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].word, "Apple")
        self.assertIn("苹果", cards[0].chn_html)
        self.assertIn("苹果树的果实", cards[0].chn_html)
        self.assertEqual(len(cards[0].sources), 2)
        self.assertEqual(stats["duplicates_merged"], 1)
        self.assertEqual(stats["skipped_empty"], 1)

    def test_private_review_list_marks_only_selected_annotation(self):
        connection = sqlite3.connect(":memory:")
        note = exporter.NoteRecord(1, "TESTNOTE", 1, "Vocabulary", (
            '<p><a href="zotero://open-pdf/library/items/A?annotation=TESTKEY">word</a>: '
            '<code>🔉 英 [wɜːd] n. 单词</code></p>'
            '<p><a href="zotero://open-pdf/library/items/A?annotation=OTHERKEY">sample</a>: '
            '<code>🔉 英 [ˈsɑːmpəl] n. 示例</code></p>'
        ))
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            exporter, "open_database_readonly", return_value=(connection, "test")
        ), patch.object(exporter, "find_note", return_value=note):
            result = exporter.export_note(
                Path("unused.sqlite"), "Vocabulary", Path(temp_dir),
                extract_examples=False, review_annotation_keys=["testkey"],
            )
        cards = result[1]
        self.assertIn("NeedsReview", cards[0].tags)
        self.assertIn("manual_review", cards[0].review_reasons)
        self.assertEqual(cards[1].review_reasons, [])


class DefinitionSplitTests(unittest.TestCase):
    def test_splits_uk_us_pronunciation_and_meaning(self):
        parsed = exporter.split_definition(
            "🔉 英 [ˈredinəs],美 [ˈrɛdɪnɪs] n. 准备就绪,愿意"
        )
        self.assertTrue(parsed.parsed)
        self.assertIn("UK", parsed.symbol_html)
        self.assertIn("pronunciation-uk", parsed.symbol_html)
        self.assertIn('aria-label="英音"', parsed.symbol_html)
        self.assertIn("/ˈredinəs/", parsed.symbol_html)
        self.assertIn("US", parsed.symbol_html)
        self.assertIn("pronunciation-us", parsed.symbol_html)
        self.assertIn('aria-label="美音"', parsed.symbol_html)
        self.assertEqual(parsed.chn_html, "n. 准备就绪,愿意")

    def test_splits_single_us_pronunciation(self):
        parsed = exporter.split_definition("🔉 美 [wɝːd] n. 单词")
        self.assertTrue(parsed.parsed)
        self.assertNotIn("UK", parsed.symbol_html)
        self.assertIn("US", parsed.symbol_html)
        self.assertEqual(parsed.chn_html, "n. 单词")

    def test_preserves_unparsed_definition(self):
        parsed = exporter.split_definition("血管内超声光学相干断层扫描")
        self.assertFalse(parsed.parsed)
        self.assertEqual(parsed.symbol_html, "")
        self.assertEqual(parsed.chn_html, "血管内超声光学相干断层扫描")

    def test_extracts_labeled_multiblock_pronunciation_and_preserves_definition(self):
        definition = "🔉 英 [wɪtʃ]<br>🔉 美 [hwɪtʃ,wɪtʃ]<br>pron. 哪一个"
        parsed = exporter.split_definition(definition)
        self.assertTrue(parsed.parsed)
        self.assertIn("/wɪtʃ/", parsed.symbol_html)
        self.assertIn("/hwɪtʃ,wɪtʃ/", parsed.symbol_html)
        self.assertEqual(parsed.chn_html, definition)

    def test_preserves_unstructured_multiblock_definition(self):
        definition = "英 [wɜːd]<br>n. 单词"
        parsed = exporter.split_definition(definition)
        self.assertFalse(parsed.parsed)
        self.assertEqual(parsed.symbol_html, "")
        self.assertEqual(parsed.chn_html, definition)

    def test_styles_known_parts_of_speech_without_touching_tags(self):
        styled = exporter.style_parts_of_speech(
            '<em title="n. should stay">n. 单词</em><br>adj. 合适的'
        )
        self.assertIn('title="n. should stay"', styled)
        self.assertIn('z2a-pos-noun">n.</span>', styled)
        self.assertIn('z2a-pos-adjective">adj.</span>', styled)

    def test_cards_include_part_of_speech_markup(self):
        records = exporter.parse_note_html(
            '<p><a href="zotero://open-pdf/library/items/A?annotation=POS123">word</a>: '
            '<code>🔉 美 [wɝːd] n. 单词</code></p>'
        )
        cards, _stats = exporter.build_cards(records)
        self.assertEqual(len(cards), 1)
        self.assertIn('z2a-pos-noun">n.</span>', cards[0].chn_html)


class SerializationTests(unittest.TestCase):
    def test_anki_headers_html_escaping_and_seven_columns(self):
        card = exporter.Card(
            word="A\t<B>",
            symbol_html='<span class="pronunciation-ipa">/eɪ/</span>',
            chn_html="line 1<br>line 2 &amp; more",
            example_html="<div>An example.</div>",
            source_html='<div><a href="zotero://source">来源</a></div>',
            zotero_keys=["BBBB"],
            tags=["Zotero2Anki"],
            sources=["zotero://source"],
            examples=[],
            review_reasons=[],
            original_definition_html="definition",
        )
        output = exporter.serialize_anki_tsv([card])
        lines = output.splitlines()
        self.assertEqual(lines[:5], list(exporter.ANKI_HEADERS))
        self.assertEqual(len(lines[5].split("\t")), 7)
        self.assertIn("A &lt;B&gt;", lines[5])
        self.assertIn("BBBB", lines[5])
        self.assertNotIn("\r", output)


class ExampleFallbackTests(unittest.TestCase):
    def test_missing_annotation_still_uses_online_fallback(self):
        record = exporter.ParagraphRecord(
            index=0,
            front="readiness",
            href="zotero://open-pdf/library/items/AAAA?page=1&annotation=MISSING",
            definition_html="n. 准备",
            code_count=1,
            link_count=1,
        )

        class FakeExtractor:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

        class FakeOnline:
            def __init__(self, _cache):
                pass

            def find(self, _term):
                from scripts.vocabulary_examples import ExampleCandidate
                return ExampleCandidate(
                    "The readiness metric was evaluated across all study participants.",
                    "online",
                    doi="10.1/test",
                )

        with (
            patch.object(exporter, "load_source_contexts", return_value={}),
            patch.object(exporter, "PdfExampleExtractor", FakeExtractor),
            patch.object(exporter, "AcademicExampleClient", FakeOnline),
        ):
            stats = exporter.enrich_records_with_examples(
                sqlite3.connect(":memory:"),
                [record],
                Path("."),
                cache_path=Path("cache.json"),
            )
        self.assertIn("MissingSource", record.example_tags)
        self.assertIn("OnlineExample", record.example_tags)
        self.assertEqual(record.examples[0].kind, "online")
        self.assertEqual(stats["missing_sources"], 1)


class SerializationReviewTests(unittest.TestCase):
    def test_export_filenames_use_project_neutral_names(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            vocabulary_path, review_path = exporter.write_exports(
                [], Path(temp_dir), "20260101-120000"
            )
            self.assertEqual(vocabulary_path.name, "zot2anki-vocabulary-20260101-120000.tsv")
            self.assertEqual(review_path.name, "zot2anki-vocabulary-20260101-120000.review.tsv")
            self.assertTrue(vocabulary_path.is_file())
            self.assertTrue(review_path.is_file())

    def test_review_output_contains_only_review_cards(self):
        cards = [
            exporter.Card(
                "ok", "", "normal", "", "source", ["OKKEY"], ["Zotero2Anki"],
                ["zotero://ok"], [], [], "normal"
            ),
            exporter.Card(
                "check", "UK /tʃek/", "line one<br>line two", "<div>example</div>", "source",
                ["CHECKKEY"], ["Zotero2Anki", "NeedsReview"], ["zotero://check"],
                [], ["definition_without_code"], "line one<br>line two"
            ),
        ]
        output = exporter.serialize_review_tsv(cards)
        self.assertNotIn("\nok\t", output)
        self.assertIn(
            "\ncheck\tdefinition_without_code\tline one / line two\tUK /tʃek/\tline one / line two\texample\t",
            output,
        )


class DatabaseTests(unittest.TestCase):
    def _create_database(self, path: Path, titles: list[str]) -> None:
        connection = sqlite3.connect(path)
        connection.executescript(
            """
            CREATE TABLE items (itemID INTEGER PRIMARY KEY, key TEXT, libraryID INTEGER);
            CREATE TABLE itemNotes (itemID INTEGER PRIMARY KEY, title TEXT, note TEXT);
            CREATE TABLE deletedItems (itemID INTEGER PRIMARY KEY);
            """
        )
        for item_id, title in enumerate(titles, start=1):
            connection.execute("INSERT INTO items VALUES (?, ?, 1)", (item_id, f"KEY{item_id}"))
            connection.execute("INSERT INTO itemNotes VALUES (?, ?, ?)", (item_id, title, "<p>&nbsp;</p>"))
        connection.commit()
        connection.close()

    def test_exact_note_match_and_not_found(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "zotero.sqlite"
            self._create_database(database, ["Vocabulary", "Vocabulary copy"])
            connection, _mode = exporter.open_database_readonly(database)
            try:
                self.assertEqual(exporter.find_note(connection, "Vocabulary").key, "KEY1")
                with self.assertRaises(exporter.ExportError):
                    exporter.find_note(connection, "不存在")
            finally:
                connection.close()

    def test_duplicate_exact_titles_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "zotero.sqlite"
            self._create_database(database, ["same", "same"])
            connection, _mode = exporter.open_database_readonly(database)
            try:
                with self.assertRaisesRegex(exporter.ExportError, "多条同名笔记"):
                    exporter.find_note(connection, "same")
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
