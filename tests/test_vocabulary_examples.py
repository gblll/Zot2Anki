import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError

from scripts import export_vocabulary_note as exporter
from scripts import vocabulary_examples as examples


class TextRecoveryTests(unittest.TestCase):
    def test_annotation_and_attachment_keys(self):
        href = "zotero://open-pdf/library/items/ABCD1234?page=2&annotation=EFGH5678"
        self.assertEqual(examples.extract_attachment_key(href), "ABCD1234")
        self.assertEqual(examples.extract_annotation_key(href), "EFGH5678")

    def test_cross_line_hyphen_span_and_highlight(self):
        text = "A micro- perforated plate provides an effective acoustic absorber."
        self.assertIsNotNone(examples.find_term_span(text, "microperforated plate"))
        rendered = examples.highlight_term(text, "microperforated plate")
        self.assertIn('<strong class="z2a-example-word">micro- perforated plate</strong>', rendered)

    def test_plain_terms_keep_literal_html_entities(self):
        text = "The literal &lt;word&gt; token remains distinct from the <word> token."
        span = examples.find_term_span(text, "&lt;word&gt;")
        self.assertEqual(text[slice(*span)], "&lt;word&gt;")
        self.assertIsNone(examples.find_term_span("A <word> token.", "&lt;word&gt;"))
        self.assertIn('&amp;lt;word&amp;gt;</strong>', examples.highlight_term(text, "&lt;word&gt;"))
        self.assertNotEqual(examples.normalize_for_match("&lt;word&gt;"), examples.normalize_for_match("<word>"))

    def test_complete_sentence_and_fragment(self):
        sentence = "Earlier work showed that readiness strongly influences the final response."
        self.assertEqual(examples._sentence_containing(sentence, "readiness"), sentence)
        self.assertIsNone(examples._sentence_containing("Table 2 readiness", "readiness"))
        self.assertEqual(examples._trim_fragment("Table 2 readiness value", "readiness"), "Table 2 readiness value")

    def test_mapped_zotero_rect_overlaps_pdf_word(self):
        word = (10.0, 90.0, 40.0, 100.0, "word", 0, 0, 0)
        mapped_rect = (10.0, 90.0, 40.0, 100.0)
        self.assertTrue(examples.PdfExampleExtractor._overlaps(word, mapped_rect))

    def test_join_tokens_removes_pdf_line_numbers(self):
        words = [
            (42.0, 10.0, 54.0, 20.0, "27", 1, 0, 0),
            (72.0, 10.0, 90.0, 20.0, "the", 1, 0, 1),
            (93.0, 10.0, 110.0, 20.0, "wet", 1, 0, 2),
            (42.0, 25.0, 54.0, 35.0, "28", 2, 0, 0),
            (72.0, 25.0, 110.0, 35.0, "process", 2, 0, 1),
        ]
        self.assertEqual(examples._join_tokens(words), "the wet process")

    def test_join_tokens_removes_line_number_even_when_pdf_word_order_is_last(self):
        words = [
            (72.0, 10.0, 106.0, 20.0, "process", 1, 0, 0),
            (109.0, 10.0, 134.0, 20.0, "step).", 1, 0, 1),
            (42.0, 10.0, 54.0, 20.0, "28", 1, 0, 2),
        ]
        self.assertEqual(examples._join_tokens(words), "process step).")


class SourceAssociationTests(unittest.TestCase):
    def test_resolves_annotation_attachment_title_doi_and_position(self):
        connection = sqlite3.connect(":memory:")
        connection.executescript(
            """
            CREATE TABLE items (itemID INTEGER PRIMARY KEY, key TEXT, libraryID INTEGER DEFAULT 1);
            CREATE TABLE libraries (libraryID INTEGER, type TEXT);
            CREATE TABLE groups (groupID INTEGER, libraryID INTEGER);
            INSERT INTO libraries VALUES (1, 'user');
            CREATE TABLE itemAnnotations (
                itemID INTEGER, parentItemID INTEGER, text TEXT,
                pageLabel TEXT, position TEXT
            );
            CREATE TABLE itemAttachments (itemID INTEGER, parentItemID INTEGER, path TEXT);
            CREATE TABLE deletedItems (itemID INTEGER);
            CREATE TABLE itemData (itemID INTEGER, fieldID INTEGER, valueID INTEGER);
            CREATE TABLE fields (fieldID INTEGER, fieldName TEXT);
            CREATE TABLE itemDataValues (valueID INTEGER, value TEXT);
            INSERT INTO items(itemID,key) VALUES (1, 'ANNKEY'), (2, 'ATTKEY'), (3, 'PARENT');
            INSERT INTO itemAnnotations VALUES (
                1, 2, 'readiness', '7',
                '{"pageIndex": 6, "rects": [[10, 20, 30, 40]]}'
            );
            INSERT INTO itemAttachments VALUES (2, 3, 'storage:paper.pdf');
            INSERT INTO fields VALUES (1, 'title'), (2, 'DOI');
            INSERT INTO itemDataValues VALUES (1, 'Paper title'), (2, '10.1/test');
            INSERT INTO itemData VALUES (3, 1, 1), (3, 2, 2);
            """
        )
        with tempfile.TemporaryDirectory() as directory:
            href = "zotero://open-pdf/library/items/ATTKEY?page=7&annotation=ANNKEY"
            context = examples.load_source_contexts(connection, [href], Path(directory))["library/ATTKEY/ANNKEY"]
            self.assertEqual(context.attachment_key, "ATTKEY")
            self.assertEqual(context.page_index, 6)
            self.assertEqual(context.rects, ((10.0, 20.0, 30.0, 40.0),))
            self.assertEqual(context.item_title, "Paper title")
            self.assertEqual(context.doi, "10.1/test")
            self.assertEqual(context.attachment_path, (Path(directory) / "storage" / "ATTKEY" / "paper.pdf").resolve())
        connection.close()


class PdfAnchorTests(unittest.TestCase):
    @staticmethod
    def make_pdf(path, lines, *, pages=1):
        import pymupdf
        contexts = []
        with pymupdf.open() as document:
            for page_index in range(pages):
                page = document.new_page()
                for y, text in lines:
                    page.insert_text((72, y), text, fontsize=10)
                matches = page.search_for("readiness")
                for rect in matches:
                    contexts.append(examples.SourceContext(
                        "ANN", "ATT", path, "readiness", str(page_index + 1), page_index,
                        (tuple(rect * ~page.transformation_matrix),), "Synthetic paper", "",
                        "zotero://open-pdf/library/items/ATT?annotation=ANN"))
            document.save(path)
        return contexts

    def test_same_block_repeated_term_uses_highlighted_occurrence(self):
        first = "Earlier readiness studies reported entirely different baseline observations."
        second = "The later readiness result was measured carefully in our experiment."
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "repeated.pdf"
            contexts = self.make_pdf(path, [(72, first + "\n" + second)])
            with examples.PdfExampleExtractor() as extractor:
                self.assertEqual(extractor.extract(contexts[0], "readiness").example.text, first)
                self.assertEqual(extractor.extract(contexts[1], "readiness").example.text, second)

    def test_neighbor_blocks_keep_highlighted_occurrence(self):
        first = "Earlier readiness studies reported entirely different baseline observations."
        beginning = "The second readiness result"
        ending = "was measured carefully in the follow-up experiment."
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "neighbors.pdf"
            contexts = self.make_pdf(path, [(72, first), (104, beginning), (136, ending)])
            with examples.PdfExampleExtractor() as extractor:
                outcome = extractor.extract(contexts[1], "readiness")
                self.assertEqual(outcome.example.kind, "local_sentence")
                self.assertEqual(outcome.example.text, beginning + " " + ending)

    def test_cross_line_hyphen_keeps_pdf_anchor_after_text_repair(self):
        import pymupdf
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hyphen.pdf"
            with pymupdf.open() as document:
                page = document.new_page()
                page.insert_text((72, 72), "The micro-\nperforated plate provides an effective acoustic absorber.", fontsize=10)
                rect = page.search_for("perforated")[0] * ~page.transformation_matrix
                context = examples.SourceContext("ANN", "ATT", path, "microperforated plate", "1", 0,
                                                 (tuple(rect),), "Synthetic", "", "")
                document.save(path)
            with examples.PdfExampleExtractor() as extractor:
                outcome = extractor.extract(context, "microperforated plate")
                self.assertEqual(outcome.example.text, "The microperforated plate provides an effective acoustic absorber.")

    def test_fragment_is_centered_on_highlighted_occurrence(self):
        text = "readiness " + "baseline " * 28 + "readiness " + "target " * 24
        import pymupdf
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fragment.pdf"
            with pymupdf.open() as document:
                page = document.new_page()
                page.insert_textbox(pymupdf.Rect(72, 72, 500, 500), text, fontsize=10)
                rect = page.search_for("readiness")[1] * ~page.transformation_matrix
                context = examples.SourceContext("ANN", "ATT", path, "readiness", "1", 0,
                                                 (tuple(rect),), "Synthetic", "", "")
                document.save(path)
            with examples.PdfExampleExtractor() as extractor:
                outcome = extractor.extract(context, "readiness")
                self.assertEqual(outcome.example.kind, "local_fragment")
                self.assertFalse(outcome.example.text.startswith("readiness"))
                self.assertIn("target", outcome.example.text)

    def test_unrelated_highlight_does_not_adopt_another_occurrence(self):
        import pymupdf
        text = "The readiness value was compared with an unrelated baseline measurement."
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unrelated.pdf"
            self.make_pdf(path, [(72, text)])
            with pymupdf.open(path) as document:
                page = document[0]
                rect = page.search_for("unrelated")[0] * ~page.transformation_matrix
            context = examples.SourceContext("ANN", "ATT", path, "unrelated", "1", 0,
                                             (tuple(rect),), "Synthetic", "", "")
            with examples.PdfExampleExtractor() as extractor:
                outcome = extractor.extract(context, "readiness")
                self.assertIsNone(outcome.example)
                self.assertIn("ExampleNeedsReview", outcome.tags)

    def test_page_text_is_reused_and_lru_eviction_reloads_only_evicted_page(self):
        import pymupdf
        text = "The readiness metric was evaluated carefully across all enrolled participants."
        with tempfile.TemporaryDirectory() as directory:
            contexts = self.make_pdf(Path(directory) / "pages.pdf", [(72, text)], pages=2)
            get_text = pymupdf.Page.get_text
            calls = []

            def counted(page, option, **kwargs):
                calls.append((page.number, option))
                return get_text(page, option, **kwargs)

            with patch.object(pymupdf.Page, "get_text", counted), examples.PdfExampleExtractor(max_cached_pages=1) as extractor:
                for context in (contexts[0], contexts[0], contexts[1], contexts[1], contexts[0]):
                    self.assertEqual(extractor.extract(context, "readiness").example.text, text)
                self.assertEqual(calls, [(0, "words"), (0, "blocks"), (1, "words"), (1, "blocks"), (0, "words"), (0, "blocks")])

    def test_document_cache_closes_evicted_pdfs_and_large_pages_skip_text_cache(self):
        text = "The readiness metric was evaluated carefully across all enrolled participants."
        with tempfile.TemporaryDirectory() as directory:
            first = self.make_pdf(Path(directory) / "first.pdf", [(72, text)])[0]
            second = self.make_pdf(Path(directory) / "second.pdf", [(72, text)])[0]
            with examples.PdfExampleExtractor(max_cached_documents=1, max_cached_text_bytes=1) as extractor:
                self.assertEqual(extractor.extract(first, "readiness").example.text, text)
                first_document = extractor._document(first.attachment_path)
                self.assertEqual(extractor.extract(second, "readiness").example.text, text)
                self.assertTrue(first_document.is_closed)
                self.assertFalse(extractor._pages)
                second_document = extractor._document(second.attachment_path)
            self.assertTrue(second_document.is_closed)
            self.assertFalse(extractor._pages)


class OnlineExampleTests(unittest.TestCase):
    def test_fixed_crossref_response_is_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            client = examples.AcademicExampleClient(Path(directory) / "cache.json")
            calls = []

            def fixed_json(url):
                calls.append(url)
                return {
                    "message": {
                        "items": [{
                            "DOI": "10.1000/example",
                            "title": ["A paper"],
                            "container-title": ["A Journal"],
                            "published": {"date-parts": [[2026]]},
                            "abstract": "The readiness metric was evaluated carefully across all enrolled participants.",
                            "URL": "https://doi.org/10.1000/example",
                        }]
                    }
                }

            client._json = fixed_json
            result = client.find("readiness")
            self.assertEqual(result.doi, "10.1000/example")
            self.assertEqual(len(calls), 1)
            second = client.find("readiness")
            self.assertEqual(second.text, result.text)
            self.assertEqual(len(calls), 1)
            persisted = json.loads((Path(directory) / "cache.json").read_text(encoding="utf-8"))
            self.assertIn("readiness", persisted)

    def test_negative_result_is_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            client = examples.AcademicExampleClient(Path(directory) / "cache.json")
            calls = []

            def empty_json(url):
                calls.append(url)
                if "crossref" in url:
                    return {"message": {"items": []}}
                return {"resultList": {"result": []}}

            client._json = empty_json
            self.assertIsNone(client.find("unfindableterm"))
            self.assertEqual(len(calls), 2)
            self.assertIsNone(client.find("unfindableterm"))
            self.assertEqual(len(calls), 2)

    def test_provider_failure_falls_through_without_aborting(self):
        with tempfile.TemporaryDirectory() as directory:
            client = examples.AcademicExampleClient(Path(directory) / "cache.json")
            client._crossref = lambda _term: (_ for _ in ()).throw(URLError("offline"))
            client._europe_pmc = lambda _term: examples.ExampleCandidate(
                "A complete fallback sentence contains the target term for validation.",
                "online",
                doi="10.1000/fallback",
            )
            result = client.find("target term")
            self.assertEqual(result.doi, "10.1000/fallback")


class MergeTests(unittest.TestCase):
    def test_at_most_three_unique_examples_and_keys(self):
        record = exporter.ParagraphRecord(
            index=0,
            front="word",
            href="zotero://open-pdf/library/items/AAAA?page=1&annotation=BBBB",
            definition_html="🔉 英 [wɜːd] n. 单词",
            code_count=1,
            link_count=1,
            zotero_key="BBBB",
        )
        record.examples = [
            examples.ExampleCandidate(f"This is example sentence number {index} for the word.", "local_sentence")
            for index in range(4)
        ]
        cards, stats = exporter.build_cards([record])
        self.assertEqual(len(cards[0].examples), 3)
        self.assertEqual(cards[0].zotero_keys, ["BBBB"])
        self.assertEqual(stats["example_count"], 3)


if __name__ == "__main__":
    unittest.main()
