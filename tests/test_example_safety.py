from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from scripts import vocabulary_examples as examples, export_vocabulary_note as exporter
from tests.fixtures import create_source


class ExampleSafetyTests(unittest.TestCase):
    def test_word_boundaries_and_cross_line_hyphens(self):
        for text, term in [('article', 'art'), ('cancer', 'can'), ('a rt', 'art'), ('_art', 'art')]:
            self.assertIsNone(examples.find_term_span(text, term))
        for text, term in [('art is helpful.', 'art'), ('micro-\nperforated plate', 'microperforated plate'), ('The C++ language.', 'C++')]:
            self.assertIsNotNone(examples.find_term_span(text, term))

    def test_fault_is_not_a_persistent_empty_result(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'cache.json'
            client = examples.AcademicExampleClient(path)
            with patch.object(client, '_json', side_effect=OSError('offline')) as request:
                self.assertIsNone(client.find('word'))
                self.assertIsNone(client.find('word'))
                self.assertEqual(request.call_count, 4)
            self.assertFalse(path.exists())

    def test_positive_negative_expiry_and_refresh(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'cache.json'
            now = datetime.now(timezone.utc)
            for status, age, expected_calls in [('empty', .5, 0), ('empty', 2, 1), ('found', 29, 0), ('found', 31, 1)]:
                with self.subTest(status=status, age=age):
                    path.write_text(json.dumps({'word': {'status': status, 'fetched_at': (now - timedelta(days=age)).isoformat(),
                                    'result': {'text': 'word', 'kind': 'online'} if status == 'found' else None}}))
                    client = examples.AcademicExampleClient(path)
                    with patch.object(client, '_crossref', return_value=examples.ExampleCandidate('word', 'online')) as request:
                        client.find('word')
                        self.assertEqual(request.call_count, expected_calls)
            client = examples.AcademicExampleClient(path, refresh=True)
            with patch.object(client, '_crossref', return_value=examples.ExampleCandidate('word', 'online')) as request:
                client.find('word')
                request.assert_called_once()

    def test_invalid_url_is_filtered_before_lookup(self):
        record = exporter.ParagraphRecord(0, 'PRIVATE_NONVOCABULARY_TEXT', 'https://example.org/?annotation=ANN', '', 1, 1)
        with tempfile.TemporaryDirectory() as root, patch.object(exporter, 'load_source_contexts', return_value={}) as lookup, patch.object(examples.AcademicExampleClient, 'find', side_effect=AssertionError('outbound text')):
            exporter.enrich_records_with_examples(None, [record], Path(root), cache_path=Path(root) / 'cache', online_fallback=True)
            self.assertEqual(lookup.call_args.args[1], [])
            with self.assertRaises(exporter.ExportError):
                exporter.validate_records([record])

    def test_cross_library_attachment_and_deleted_parent_filters(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            database = create_source(root)
            db = sqlite3.connect(database)
            try:
                db.executescript('''
                    INSERT INTO items VALUES (10, 'ANN', 2), (11, 'ATT', 2), (12, 'PARENT2', 2);
                    INSERT INTO itemAnnotations VALUES (10,11,'group word','2','{}');
                    INSERT INTO itemAttachments VALUES (11,12,'storage:group.pdf');
                ''')
                personal = 'zotero://open-pdf/library/items/ATT?annotation=ANN'
                group = 'zotero://open-pdf/groups/123/items/ATT?annotation=ANN'
                contexts = examples.load_source_contexts(db, [personal, group], root)
                self.assertEqual(contexts['library/ATT/ANN'].annotation_text, 'readiness')
                self.assertEqual(contexts['groups/123/ATT/ANN'].annotation_text, 'group word')
                self.assertFalse(examples.load_source_contexts(db, [personal.replace('/ATT?', '/WRONG?')], root))
                for item in (2, 3, 4):
                    db.execute('insert into deletedItems values (?)', (item,))
                    self.assertNotIn('library/ATT/ANN', examples.load_source_contexts(db, [personal], root))
                    db.execute('delete from deletedItems')
            finally:
                db.close()

    def test_tsv_escaping_and_existing_files(self):
        from tests.test_sync_identity import card
        item = card('&lt;word&gt;', 'A')
        self.assertIn('&lt;word&gt;', exporter.serialize_anki_tsv([item]))
        self.assertNotIn('&amp;lt;', exporter.serialize_anki_tsv([item]))
        with tempfile.TemporaryDirectory() as root:
            paths = exporter.write_exports([item], Path(root), 'test')
            before = paths[0].read_bytes()
            with self.assertRaises(exporter.ExportError):
                exporter.write_exports([], Path(root), 'test')
            self.assertEqual(paths[0].read_bytes(), before)

    def test_lost_source_link_cannot_silently_become_a_missing_note(self):
        records = exporter.parse_note_html('<p>Vocabulary</p><p>readiness: <code>n. meaning</code></p>')
        with self.assertRaises(exporter.ExportError):
            exporter.validate_records(records, 'Vocabulary')
