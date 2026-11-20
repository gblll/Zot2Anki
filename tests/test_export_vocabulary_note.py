from pathlib import Path
from contextlib import closing, redirect_stdout, redirect_stderr
import io
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from scripts import export_vocabulary_note as exporter
from scripts.vocabulary_examples import ExtractionOutcome


class VocabularyNoteParserTests(unittest.TestCase):
    def test_strict_validation_rejects_unparsed_text_before_source(self):
        link = '<a href="zotero://open-pdf/library/items/ATT?annotation=ANN">second</a>'
        for prefix in ('first: <code>n. lost source</code><br>', 'unparsed text ', '<span>first</span>'):
            with self.subTest(prefix=prefix):
                records = exporter.parse_note_html(f'<p>{prefix}{link}: n. second</p>')
                with self.assertRaises(exporter.ExportError):
                    exporter.validate_records(records)
        records = exporter.parse_note_html(f'<p> \n&nbsp;{link}: n. second</p>')
        exporter.validate_records(records)

    def test_literal_entities_remain_distinct_through_merge_and_tsv(self):
        records = exporter.parse_note_html(
            '<p><a href="zotero://open-pdf/library/items/ATT?annotation=A">'
            '&amp;lt;word&amp;gt;</a>: n. literal entity</p>'
            '<p><a href="zotero://open-pdf/library/items/ATT?annotation=B">'
            '&lt;word&gt;</a>: n. angle brackets</p>')
        exporter.validate_records(records)
        cards, _ = exporter.build_cards(records)
        self.assertEqual([card.word for card in cards], ['&lt;word&gt;', '<word>'])
        fields = [row.split('\t')[0] for row in exporter.serialize_anki_tsv(cards).splitlines()[5:]]
        self.assertEqual(fields, ['&amp;lt;word&amp;gt;', '&lt;word&gt;'])

    def test_strict_validation_rejects_text_outside_paragraphs(self):
        valid = '<p><a href="zotero://open-pdf/library/items/ATT?annotation=ANN">one</a>: n. one</p>'
        for extra in ('<div>two: lost source</div>', '<h2>Another title</h2>',
                      '<ul><li>two: lost source</li></ul>', 'unwrapped text'):
            for note in (extra + valid, valid + extra):
                with self.subTest(note=note):
                    records = exporter.parse_note_html(note)
                    with self.assertRaises(exporter.ExportError):
                        exporter.validate_records(records, 'Vocabulary')

    def test_leading_plain_heading_matching_note_title_is_not_a_card(self):
        valid = '<p><a href="zotero://open-pdf/library/items/ATT?annotation=ANN">one</a>: n. one</p>'
        for tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            with self.subTest(tag=tag):
                records = exporter.parse_note_html(
                    f'<div class="zotero-note">\n<{tag} style="color: blue">'
                    f'<span>📘 Vocabulary &gt;&gt;</span></{tag}>' + valid + '</div>')
                exporter.validate_records(records, '📘 Vocabulary >>')
                cards, _ = exporter.build_cards(records)
                self.assertEqual([card.word for card in cards], ['one'])

    def test_title_exception_does_not_hide_damaged_content(self):
        valid = '<p><a href="zotero://open-pdf/library/items/ATT?annotation=ANN">one</a>: n. one</p>'
        for note in (
            '<div>Vocabulary</div>' + valid,
            '<h2>Vocabulary</h2>lost source' + valid,
            '<h2><code>Vocabulary</code></h2>' + valid,
            '<h2><a href="https://example.org">Vocabulary</a></h2>' + valid,
            '<h2><a href="zotero://open-pdf/library/items/ATT?annotation=ANN">Vocabulary</a></h2>' + valid,
            valid + '<h2>Vocabulary</h2>',
            '<h2>Vocabulary</h2><h2>Vocabulary</h2>' + valid,
            '<h2>Vocabulary</h2><p>two: lost source</p>' + valid,
            '<h2>Vocabulary</h2>',
        ):
            with self.subTest(note=note):
                with self.assertRaises(exporter.ExportError):
                    exporter.validate_records(exporter.parse_note_html(note), 'Vocabulary')

    def test_strict_validation_accepts_wrappers_whitespace_and_title_paragraph(self):
        records = exporter.parse_note_html(
            '<div data-schema-version="9">\n<p>Vocabulary</p>\n'
            '<div><p><a href="zotero://open-pdf/library/items/ATT?annotation=ANN">one</a>: n. one</p></div>'
            '\n&nbsp;</div>')
        exporter.validate_records(records, 'Vocabulary')
        cards, _ = exporter.build_cards(records)
        self.assertEqual([card.word for card in cards], ['one'])

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
    def test_missing_annotation_never_sends_text_online(self):
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
            def __init__(self, _cache, **kwargs):
                pass

            def find(self, _term):
                raise AssertionError('Invalid source text must not be sent online')

        with (
            patch.object(exporter, "load_source_contexts", return_value={}),
            patch.object(exporter, "PdfExampleExtractor", FakeExtractor),
            patch.object(exporter, "AcademicExampleClient", FakeOnline),
        ):
            connection = sqlite3.connect(":memory:")
            self.addCleanup(connection.close)
            stats, skipped = exporter.enrich_records_with_examples(
                connection,
                [record],
                Path("."),
                cache_path=Path("cache.json"),
                online_fallback=True,
            )
        self.assertIn("MissingSource", record.example_tags)
        self.assertNotIn("OnlineExample", record.example_tags)
        self.assertEqual(record.examples, [])
        self.assertEqual(stats["missing_sources"], 1)
        self.assertEqual(skipped, [])


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


class SkippedSourceTests(unittest.TestCase):
    """A dead annotation link must stop the run by default, or skip one entry on demand."""

    URL = "zotero://open-pdf/library/items/ATT?page=1&annotation={key}"

    def setUp(self):
        from tests.fixtures import create_source
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)
        self.database = create_source(self.root)
        self.valid = exporter.ParagraphRecord(
            index=0, front="readiness", href=self.URL.format(key="ANN"),
            definition_html="n. readiness", code_count=1, link_count=1)
        self.dead = exporter.ParagraphRecord(
            index=1, front="vanished", href=self.URL.format(key="GONE"),
            definition_html="n. vanished", code_count=1, link_count=1)

    class _StubExtractor:
        """The resolved record still resolves; only PDF extraction is stubbed."""

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def extract(self, _context, _term):
            return ExtractionOutcome(None, (), ("stubbed",))

    def _enrich(self, records, **options):
        connection, _mode = exporter.open_database_readonly(self.database)
        self.addCleanup(connection.close)
        with patch.object(exporter, "PdfExampleExtractor", self._StubExtractor):
            return exporter.enrich_records_with_examples(
                connection, records, self.root,
                cache_path=self.root / "cache.json", online_fallback=False, **options)

    def test_default_still_stops_the_whole_run(self):
        with self.assertRaisesRegex(exporter.ExportError, "无法对应到有效 annotation"):
            self._enrich([self.valid, self.dead], strict_sources=True)

    def test_standalone_cli_checks_sources_even_without_examples(self):
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute('UPDATE itemNotes SET note=note || ?', (
                '<p><a href="' + self.dead.href + '">vanished</a>: <code>n. gone</code></p>',))
            connection.commit()
        config = self.root / 'settings.json'
        output = self.root / 'output'
        config.write_text(json.dumps({'database': str(self.database), 'note_title': 'Vocabulary',
                                      'output_dir': str(output)}), encoding='utf-8')
        args = ['--config', str(config), '--no-examples']
        with patch.object(exporter, 'PdfExampleExtractor', side_effect=AssertionError('PDF requested')), \
                patch('scripts.vocabulary_examples.urlopen', side_effect=AssertionError('network requested')), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(exporter.main(args), 2)
            self.assertFalse(output.exists())
            self.assertEqual(exporter.main(args + ['--skip-invalid-sources']), 0)
        review = next(output.glob('*.review.tsv')).read_text(encoding='utf-8')
        self.assertIn('vanished\tskipped_invalid_source', review)
        tsv = next(path for path in output.glob('*.tsv') if not path.name.endswith('.review.tsv'))
        self.assertIn('readiness', tsv.read_text(encoding='utf-8'))
        self.assertNotIn('vanished', tsv.read_text(encoding='utf-8'))

    def test_skip_reports_the_dead_entry_and_keeps_the_rest(self):
        stats, skipped = self._enrich([self.valid, self.dead], strict_sources=True,
                                      skip_invalid_sources=True)
        self.assertEqual(stats["resolved_contexts"], 1)
        self.assertEqual(stats["missing_sources"], 0)
        self.assertEqual([entry["word"] for entry in skipped], ["vanished"])
        self.assertEqual(skipped[0]["reason"], "annotation_not_found_or_deleted")
        self.assertEqual(skipped[0]["source"], self.URL.format(key="GONE"))
        self.assertIn("MissingSource", self.dead.example_tags)
        self.assertIn("annotation_not_found", self.dead.review_reasons)
        self.assertEqual(self.dead.examples, [])

    def test_malformed_source_never_reaches_lookup_or_extractor(self):
        # source_identity() rejects an unusable annotation key before any work.
        record = exporter.ParagraphRecord(
            index=0, front="broken", href="zotero://open-pdf/library/items/ATT?annotation=???",
            definition_html="n. broken", code_count=1, link_count=1)
        with patch.object(exporter, "load_source_contexts", return_value={}) as lookup, \
                patch.object(exporter, "PdfExampleExtractor") as extractor:
            stats, skipped = exporter.enrich_records_with_examples(
                None, [record], self.root, cache_path=self.root / "cache.json",
                strict_sources=True, skip_invalid_sources=True)
        self.assertEqual(skipped, [])
        self.assertEqual(stats["resolved_contexts"], 0)
        # Nothing to resolve, and no extraction for a malformed source.
        self.assertEqual(lookup.call_args.args[1], [])
        extractor.return_value.__enter__.return_value.extract.assert_not_called()

    def test_skipped_entries_appear_in_the_review_file(self):
        with tempfile.TemporaryDirectory() as output:
            cards, _stats = exporter.build_cards([self.valid])
            _vocabulary, review = exporter.write_exports(
                cards, Path(output), "regression",
                [{"word": "vanished", "reason": "annotation_not_found_or_deleted",
                  "source": self.URL.format(key="GONE")}])
            lines = review.read_text(encoding="utf-8").splitlines()
        self.assertIn("vanished\tskipped_invalid_source\tannotation_not_found_or_deleted", lines[-1])
        self.assertTrue(lines[-1].endswith("GONE"))

    def test_online_lookup_never_receives_an_unresolved_word(self):
        class Recording:
            """Records every provider query; the dead entry must never appear here."""

            queries = []

            def __init__(self, _cache_path, **_options):
                pass

            def find(self, term):
                Recording.queries.append(term)
                return None

        connection, _mode = exporter.open_database_readonly(self.database)
        self.addCleanup(connection.close)
        with patch.object(exporter, "PdfExampleExtractor", self._StubExtractor), \
                patch.object(exporter, "AcademicExampleClient", Recording):
            stats, skipped = exporter.enrich_records_with_examples(
                connection, [self.valid, self.dead], self.root,
                cache_path=self.root / "cache.json",
                online_fallback=True, strict_sources=True, skip_invalid_sources=True)
        self.assertEqual([entry["word"] for entry in skipped], ["vanished"])
        self.assertNotIn("vanished", Recording.queries)
        self.assertNotIn("OnlineExample", self.dead.example_tags)
        self.assertNotIn("NoExample", self.dead.example_tags)
        self.assertEqual(stats["online_sentences"], 0)


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
