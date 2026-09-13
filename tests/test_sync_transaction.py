import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from scripts import sync_vocabulary as sync, sync_storage as storage, sync_plan, sync_packages
from tests.fixtures import create_config


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='zot2anki 测试 ')
        self.root = Path(self.temp.name)
        self.config, self.collection = create_config(self.root)
        self.before = storage.fingerprint(self.collection)
        self.processes = patch.object(sync, '_running_applications', return_value=[])
        self.processes.start()

    def tearDown(self):
        self.processes.stop()
        self.temp.cleanup()

    def run_cli(self, *flags):
        with redirect_stdout(io.StringIO()):
            return sync.main(['--config', str(self.config), *flags])

    def reports(self):
        return [(p, json.loads(p.read_text(encoding='utf-8')))
                for p in (self.root / 'output').glob('zot2anki-sync-*.json')]

    def latest(self, stage=None):
        """Select a journal by stage, never by filename order.

        Two runs in the same second share a timestamp and differ only in a random
        suffix, so sorting by name would pick either run at random.
        """
        found = [(path.stat().st_mtime_ns, path, state) for path, state in self.reports()
                 if stage is None or state.get('stage') == stage]
        path, state = max(found, key=lambda item: item[0])[1:]
        return path, state

    def report(self):
        return self.latest()

    def test_full_offline_cli_and_backup_restore(self):
        with patch('urllib.request.urlopen', side_effect=AssertionError('Offline run made a network request')):
            self.assertEqual(self.run_cli(), 0)
        _, report = self.report()
        self.assertTrue(report['committed'])
        self.assertEqual(report['stage'], 'complete')
        self.assertEqual(report['export']['local_sentences'], 1)
        self.assertEqual(report['profile'], '测试 Profile')
        self.assertEqual(report['clean_package']['notes'], 1)
        backup = Path(report['outputs']['backup'])
        storage.validate_database(backup)
        restored = self.root / 'restore.anki2'
        storage.consistent_backup(backup, restored)
        self.assertEqual(storage.sha256(restored), storage.sha256(backup))
        Collection, _ = sync._configure_anki(sync.DEFAULT_ANKI_PACKAGES)
        col = Collection(str(restored))
        try:
            self.assertEqual(col.db.scalar('select count(*) from notes'), 0)
        finally:
            col.close()
        self.assertEqual(self.run_cli(), 0)
        reports = [json.loads(p.read_text(encoding='utf-8')) for p in (self.root / 'output').glob('zot2anki-sync-*.json')]
        self.assertEqual(len(reports), 2)
        self.assertTrue(any(r['sync']['added'] == 0 for r in reports))

    def test_journal_upgrade_preserves_identity_and_is_idempotent(self):
        import sqlite3
        import zipfile
        self.assertEqual(self.run_cli(), 0)
        Collection, _ = sync._configure_anki(sync.DEFAULT_ANKI_PACKAGES)
        col = Collection(str(self.collection))
        try:
            nid = col.db.scalar("select id from notes where flds like 'readiness%'")
            note = col.get_note(nid)
            note['Notes'] = 'Personal note'
            note.add_tag('PersonalTag')
            col.update_note(note)
            cid = col.db.scalar('select id from cards')
            col.db.execute('update cards set reps=7,ivl=12 where id=?', cid)
            col.db.execute('insert into revlog values (123456789,?,0,3,12,6,2500,1000,1)', cid)
            before_cards = col.db.all('select * from cards')
            before_reviews = col.db.all('select * from revlog')
            guid = note.guid
        finally:
            col.close()
        from contextlib import closing
        with closing(sqlite3.connect(self.root / 'zotero.sqlite')) as db:
            db.executescript("INSERT INTO fields VALUES (2,'journalAbbreviation'); INSERT INTO itemDataValues VALUES (2,'Private Syn. J.'); INSERT INTO itemData VALUES (4,2,2);")
        self.assertEqual(self.run_cli(), 0)
        reports = [json.loads(p.read_text(encoding='utf-8')) for p in (self.root / 'output').glob('zot2anki-sync-*.json')]
        report = next(r for r in reports if r['sync']['updated'] == 1)
        col = Collection(str(self.collection))
        try:
            note = col.get_note(nid)
            self.assertEqual(note.guid, guid)
            self.assertEqual(note['Notes'], 'Personal note')
            self.assertIn('PersonalTag', note.tags)
            self.assertIn('>Private Syn. J.</span>', note['Source'])
            self.assertIn('>Private Syn. J.</span>', note['Example'])
            self.assertEqual(col.db.all('select * from cards'), before_cards)
            self.assertEqual(col.db.all('select * from revlog'), before_reviews)
        finally:
            col.close()
        for key, present in [('personal', True), ('clean', False)]:
            with zipfile.ZipFile(report['outputs'][key + '_apkg']) as archive:
                self.assertEqual('Private Syn. J.'.encode() in archive.read('collection.anki21'), present)
        self.assertEqual(self.run_cli(), 0)
        reports = [json.loads(p.read_text(encoding='utf-8')) for p in (self.root / 'output').glob('zot2anki-sync-*.json')]
        self.assertTrue(any(r['sync']['unchanged'] == 1 and r['sync']['updated'] == 0 for r in reports))

    def test_dry_run_is_read_only_and_has_match_plan(self):
        self.assertEqual(self.run_cli('--dry-run'), 0)
        _, report = self.report()
        self.assertEqual(report['stage'], 'dry_run')
        self.assertEqual(report['plan']['new_count'], 1)
        self.assertFalse(report['committed'])
        self.assertEqual(storage.fingerprint(self.collection), self.before)

    def test_precommit_faults_leave_original_untouched(self):
        for module, name in [(sync, '_ensure_notetype'), (sync_plan, 'execute_plan'),
                             (sync_packages, 'export_personal'), (storage, 'commit_candidate')]:
            with self.subTest(stage=name), patch.object(module, name, side_effect=OSError('synthetic disk/permission failure')) as failure:
                with self.assertRaises(sync.SyncError):
                    self.run_cli()
                self.assertEqual(storage.fingerprint(self.collection), self.before)
                failure.assert_called_once()

    def test_postcommit_output_fault_is_recoverable_without_resync(self):
        with patch.object(storage, 'publish_file', side_effect=PermissionError('synthetic output failure')):
            with self.assertRaisesRegex(sync.SyncError, '数据库已提交'):
                self.run_cli()
        report_path, report = self.report()
        self.assertTrue(report['committed'])
        committed = storage.fingerprint(self.collection)
        with patch.object(sync_plan, 'execute_plan', side_effect=AssertionError('must not resync')):
            storage.recover_outputs(report_path)
        self.assertEqual(storage.fingerprint(self.collection), committed)
        self.assertEqual(json.loads(report_path.read_text(encoding='utf-8'))['stage'], 'complete')

    def test_error_immediately_after_replace_is_identified_as_committed(self):
        original = storage.commit_candidate
        def fail_after(*args):
            original(*args)
            raise OSError('simulated journal failure after database replacement')
        with patch.object(storage, 'commit_candidate', side_effect=fail_after):
            with self.assertRaisesRegex(sync.SyncError, '数据库已提交'):
                self.run_cli()
        path, report = self.report()
        self.assertTrue(report['committed'])
        storage.recover_outputs(path)

    def test_dead_annotation_link_blocks_by_default_and_can_be_skipped(self):
        import sqlite3
        from contextlib import closing
        # Reproduce a note whose second entry points at an annotation that no
        # longer exists, which is the real-world case that stopped every run.
        note_key = 'zotero://open-pdf/library/items/ATT?page=1&annotation=ANN'
        dead_key = 'zotero://open-pdf/library/items/ATT?page=1&annotation=GONE'
        with closing(sqlite3.connect(self.root / 'zotero.sqlite')) as db:
            note = (
                f'<p><a href="{note_key}">readiness</a>: <code>n. readiness definition</code></p>'
                f'<p><a href="{dead_key}">vanished</a>: <code>n. vanished definition</code></p>'
            )
            db.execute('UPDATE itemNotes SET note=? WHERE title=?', (note, 'Vocabulary'))
            db.commit()

        with self.assertRaisesRegex(sync.SyncError, '无法对应到有效 annotation'):
            self.run_cli()
        self.assertEqual(storage.fingerprint(self.collection), self.before)

        self.assertEqual(self.run_cli('--skip-invalid-sources'), 0)
        _, report = self.latest(stage='complete')
        self.assertTrue(report['committed'])
        self.assertEqual(report['stage'], 'complete')
        self.assertEqual(report['skipped_sources'], [
            {'paragraph_index': 1, 'word': 'vanished', 'source': dead_key,
             'reason': 'annotation_not_found_or_deleted'},
        ])
        self.assertEqual(report['export']['skipped_invalid_sources'], 1)
        # The healthy entry still syncs; the dead one is recorded, not silently lost.
        self.assertEqual(report['sync']['added'], 1)
        self.assertEqual(report['clean_package']['notes'], 1)
        review = Path(report['outputs']['review_tsv']).read_text(encoding='utf-8')
        self.assertIn('vanished\tskipped_invalid_source\tannotation_not_found_or_deleted', review)
        self.assertIn('GONE', review)
        # A later run without the flag must still refuse rather than drop the entry.
        with self.assertRaises(sync.SyncError):
            self.run_cli()

    def test_skipped_existing_note_preserves_content_and_review_history(self):
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(self.root / 'zotero.sqlite')) as db:
            db.execute("insert into items values (5, 'HEALTHY', 1)")
            db.execute("insert into itemAnnotations select 5,parentItemID,text,pageLabel,position from itemAnnotations where itemID=2")
            db.execute("update itemNotes set note=note || ?", (
                '<p><a href="zotero://open-pdf/library/items/ATT?annotation=HEALTHY">healthy</a>: <code>adj. healthy</code></p>',))
            db.commit()
        self.assertEqual(self.run_cli(), 0)
        Collection, _ = sync._configure_anki(sync.DEFAULT_ANKI_PACKAGES)
        col = Collection(str(self.collection))
        try:
            nid = col.db.scalar("select id from notes where flds like 'readiness%'")
            note = col.get_note(nid)
            note['Notes'] = 'Personal note'
            note.add_tag('PersonalTag')
            col.update_note(note)
            cid = col.db.scalar('select id from cards')
            col.db.execute('update cards set reps=7,ivl=12 where id=?', cid)
            col.db.execute('insert into revlog values (123456789,?,0,3,12,6,2500,1000,1)', cid)
            before = {table: col.db.all(f'select * from {table}')
                      for table in ('notes', 'cards', 'revlog')}
            self.assertTrue(note['Example'])
        finally:
            col.close()
        with closing(sqlite3.connect(self.root / 'zotero.sqlite')) as db:
            db.execute('insert into deletedItems values (2)')
            db.commit()
        # One source is now invalid. Repeated opt-in runs must preserve the
        # complete note row, not merely its ID or personal Notes field.
        for _ in range(2):
            self.assertEqual(self.run_cli('--skip-invalid-sources'), 0)
            _, report = self.latest(stage='complete')
            self.assertEqual(report['plan']['preserved'], [nid])
            self.assertEqual(report['sync']['updated'], 0)
            self.assertEqual(report['sync']['marked_missing'], 0)
            self.assertEqual(report['clean_package']['notes'], 1)
            col = Collection(str(self.collection))
            try:
                for table, rows in before.items():
                    self.assertEqual(col.db.all(f'select * from {table}'), rows, table)
            finally:
                col.close()

        with closing(sqlite3.connect(self.root / 'zotero.sqlite')) as db:
            db.execute('insert into deletedItems values (5)')
            db.commit()
        fingerprint = storage.fingerprint(self.collection)
        with self.assertRaisesRegex(sync.SyncError, '解析结果为空'):
            self.run_cli('--skip-invalid-sources')
        self.assertEqual(storage.fingerprint(self.collection), fingerprint)

    def test_unsafe_repository_output_is_rejected(self):
        with self.assertRaises(sync.SyncError):
            sync.check_output_directory(sync.local_config.ROOT / 'unsafe-results')

    def test_starting_app_between_preflight_and_commit_blocks_commit(self):
        with patch.object(sync, '_running_applications', side_effect=[[], ['Anki']]):
            with self.assertRaises(sync.SyncError):
                self.run_cli()
        self.assertEqual(storage.fingerprint(self.collection), self.before)

    def test_wrong_environment_never_opens_personal_databases(self):
        with patch.object(sync.runtime_check, 'check_runtime', side_effect=RuntimeError('wrong runtime')), patch.object(storage, 'consistent_backup') as backup:
            with self.assertRaises(RuntimeError):
                self.run_cli()
            backup.assert_not_called()
        self.assertEqual(storage.fingerprint(self.collection), self.before)
