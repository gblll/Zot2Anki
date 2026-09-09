from contextlib import closing
from dataclasses import replace
from pathlib import Path
import sqlite3
import tempfile
import unittest

from scripts import export_vocabulary_note as export
from scripts.vocabulary_examples import SourceContext, ExampleCandidate, load_source_contexts, PdfExampleExtractor
from scripts import sync_packages
from tests.fixtures import create_source
from tests.test_sync_identity import card


class JournalTests(unittest.TestCase):
    def context(self, **kwargs):
        return replace(SourceContext("ANN", "ATT", None, "word", "5", 0, (), "Title", "", "zotero://open-pdf/library/items/ATT?annotation=ANN"), **kwargs)

    def test_fallback_and_escaping(self):
        for abbreviation, full, expected in [(" J. Test ", "Full Journal", "J. Test"), ("  ", "Full Journal", "Full Journal"), ("", "", "")]:
            context = self.context(journal_abbreviation=abbreviation, publication_title=full)
            result = export.render_sources([(context.href, context)])
            self.assertIn("Title", result)
            self.assertIn("p. 5", result)
            self.assertEqual('class="z2a-journal"' in result, bool(expected))
            if expected:
                self.assertIn('>' + expected + '</span>', result)
                self.assertNotIn("（", result)
        result = export.render_sources([("a&b", self.context(item_title="<Title>", journal_abbreviation='<J&"', page_label="<5>"))])
        self.assertIn("&lt;Title&gt;", result)
        self.assertIn("&lt;J.&amp;&quot;", result)
        self.assertIn("p. &lt;5&gt;", result)
        self.assertIn('href="a&amp;b"', result)
        self.assertNotIn("<Title>", result)

    def test_missing_title_and_multiple_sources(self):
        a = self.context(item_title="", journal_abbreviation="J. One")
        b = self.context(journal_abbreviation="J. Two")
        result = export.render_sources([(a.href, a), (b.href, b)])
        self.assertIn("打开来源 1", result)
        self.assertIn("打开来源 2", result)
        self.assertIn('>J. One</span>', result)
        self.assertIn('Title · <span class="z2a-journal">J. Two', result)

    def test_local_and_online_metadata_and_clean_boundary(self):
        for kind in ("local_sentence", "local_fragment"):
            example = ExampleCandidate("word sentence", kind, title="Title", journal="Private J.")
            self.assertIn('>Private J.</span>', export._example_metadata(example))
            vocabulary = card("word", "ANN")
            vocabulary.examples = [example]
            self.assertNotIn("Private J.", " ".join(sync_packages.share_fields(vocabulary)))
        online = ExampleCandidate("word sentence", "online", title="Public title", journal="Public Journal")
        self.assertIn("Public title · Public Journal", export._example_metadata(online))

    def test_database_extraction_and_missing_pdf_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = create_source(root)
            context = self.context()
            with closing(sqlite3.connect(database)) as db:
                db.executescript("INSERT INTO fields VALUES (2, 'journalAbbreviation'), (3, 'publicationTitle'); INSERT INTO itemDataValues VALUES (2, 'Syn. J.'), (3, 'Synthetic Journal'); INSERT INTO itemData VALUES (4,2,2), (4,3,3);")
                contexts = load_source_contexts(db, [context.href], root)
            context = next(iter(contexts.values()))
            self.assertEqual(context.publication_title, "Synthetic Journal")
            with PdfExampleExtractor() as extractor:
                example = extractor.extract(context, "readiness").example
            self.assertEqual(example.journal, "Syn. J.")
            with PdfExampleExtractor() as extractor:
                self.assertIsNone(extractor.extract(replace(context, attachment_path=None), "readiness").example)
            self.assertIn('>Syn. J.</span>', export.render_sources([(context.href, context)]))

    def test_journal_punctuation_is_conservative_and_idempotent(self):
        from scripts.vocabulary_examples import punctuate_journal_abbreviation
        cases = [
            ("Nat Commun", "Nature Communications", "Nat. Commun."),
            ("Nat. Commun.", "Nature Communications", "Nat. Commun."),
            ("Nat Rev Methods Primers", "Nature Reviews Methods Primers", "Nat. Rev. Methods Primers"),
            ("IEEE Trans Ultrason Ferroelectr Freq Control", "IEEE Transactions on Ultrasonics, Ferroelectrics, and Frequency Control", "IEEE Trans. Ultrason. Ferroelectr. Freq. Control"),
            ("ACS Nano", "ACS Nano", "ACS Nano"),
            ("npj Comput Mater", "npj Computational Materials", "npj Comput. Mater."),
            ("Science", "Science", "Science"),
            ("Phys Rev A", "Physical Review A", "Phys. Rev. A"),
            ("Proc Natl Acad Sci USA", "Proceedings of the National Academy of Sciences", "Proc. Natl. Acad. Sci. USA"),
            ("Nat Commun", "", "Nat. Commun."),
            ("Unknown Journal", "", "Unknown Journal"),
        ]
        for abbreviation, full, expected in cases:
            with self.subTest(abbreviation=abbreviation):
                value = punctuate_journal_abbreviation(abbreviation, full)
                self.assertEqual(value, expected)
                self.assertEqual(punctuate_journal_abbreviation(value, full), value)
        context = self.context(journal_abbreviation="Nat Commun", publication_title="Nature Communications")
        self.assertEqual(context.journal, "Nat. Commun.")
        source = export.render_sources([(context.href, context)])
        self.assertIn('Title · <span class="z2a-journal">Nat. Commun.</span> · p. 5', source)
        self.assertEqual(self.context(publication_title="Nature Communications").journal, "Nature Communications")
