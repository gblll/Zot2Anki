"""Regressions for preflight ownership and transactional file handling."""
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from scripts import sync_storage as storage
from scripts.source_identity import source_identity, identities_from_html


class SourceIdentityTests(unittest.TestCase):
    def test_identity_includes_library_attachment_and_annotation(self):
        a = 'zotero://open-pdf/library/items/ATT?page=1&annotation=ANN'
        b = 'zotero://open-pdf/groups/123/items/ATT?page=1&annotation=ANN'
        self.assertNotEqual(source_identity(a), source_identity(b))
        self.assertNotEqual(source_identity(a), source_identity(a.replace('/ATT?', '/OTHER?')))
        self.assertEqual(identities_from_html('<a href="' + a.replace('&', '&amp;') + '">x</a>'), [source_identity(a)])

    def test_invalid_or_ambiguous_link_is_rejected(self):
        for value in ['https://example.org/?annotation=ANN',
                      'zotero://open-pdf/library/items/ATT',
                      'zotero://open-pdf/library/items/ATT?annotation=A&annotation=B']:
            self.assertIsNone(source_identity(value))


class StorageTests(unittest.TestCase):
    def test_backup_includes_committed_wal_and_blocks_commit(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'collection.anki2'
            db = sqlite3.connect(path)
            db.execute('pragma journal_mode=wal')
            db.execute('create table sample (value)')
            db.execute('insert into sample values (42)')
            db.commit()
            backup = Path(root) / 'backup.anki2'
            storage.consistent_backup(path, backup)
            with closing(sqlite3.connect(backup)) as copy:
                self.assertEqual(copy.execute('select value from sample').fetchone(), (42,))
            with self.assertRaises(storage.StorageError):
                storage.require_no_wal(path)
            db.close()

    def test_lock_prevents_duplicate_runs_and_releases_on_failure(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'collection.anki2'
            with storage.CollectionLock(path):
                with self.assertRaises(storage.StorageError):
                    with storage.CollectionLock(path):
                        pass
            with storage.CollectionLock(path):
                pass

    def test_output_collision_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as root:
            source, target = Path(root) / 'new', Path(root) / 'existing'
            source.write_text('new')
            target.write_text('original')
            with self.assertRaises(storage.StorageError):
                storage.publish_file(source, target)
            self.assertEqual(target.read_text(), 'original')

    def test_changed_original_rejected_before_replace(self):
        with tempfile.TemporaryDirectory() as root:
            target, candidate = Path(root) / 'db', Path(root) / 'candidate'
            target.write_bytes(b'original')
            original = storage.fingerprint(target)
            with closing(sqlite3.connect(candidate)) as db:
                db.execute('create table sample (value)')
            target.write_bytes(b'changed')
            with self.assertRaises(storage.StorageError):
                storage.commit_candidate(target, candidate, original, lambda: [])
            self.assertEqual(target.read_bytes(), b'changed')

    def test_atomic_json_and_recovery_does_not_resync(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            db, src, dst = root / 'db', root / 'staged', root / 'result'
            db.write_bytes(b'committed')
            src.write_bytes(b'package')
            journal = root / 'run.json'
            state = {'stage': 'committed', 'committed': True, 'collection': str(db),
                     'after': storage.fingerprint(db),
                     'artifacts': [{'staged': str(src), 'final': str(dst), 'sha256': storage.sha256(src)}]}
            storage.atomic_json(journal, state)
            storage.recover_outputs(journal)
            self.assertEqual(dst.read_bytes(), b'package')
            self.assertEqual(db.read_bytes(), b'committed')
            self.assertEqual(json.loads(journal.read_text())['stage'], 'complete')
