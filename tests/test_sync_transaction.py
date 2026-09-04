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

    def report(self):
        paths = list((self.root / 'output').glob('zot2anki-sync-*.json'))
        return paths[-1], json.loads(paths[-1].read_text(encoding='utf-8'))

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
            with self.subTest(stage=name), patch.object(module, name, side_effect=OSError('synthetic disk/permission failure')):
                with self.assertRaises(sync.SyncError):
                    self.run_cli()
                self.assertEqual(storage.fingerprint(self.collection), self.before)

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

    def test_unsafe_repository_output_is_rejected(self):
        with self.assertRaises(sync.SyncError):
            sync.check_output_directory(sync.local_config.ROOT / 'unsafe-results')
