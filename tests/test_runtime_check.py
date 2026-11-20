"""Exercise runtime compatibility against the installed Anki backend."""
from contextlib import ExitStack
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from scripts import runtime_check, sync_vocabulary as sync


class RuntimeCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.Collection, _ = sync._configure_anki(sync.DEFAULT_ANKI_PACKAGES)

    def check_runtime(self, configure_anki=None):
        return runtime_check.check_runtime(
            sync.local_config.ROOT, sync.DEFAULT_ANKI_PACKAGES,
            configure_anki or sync._configure_anki)

    def test_installed_backend_passes_real_sync_and_package_probe(self):
        import anki.buildinfo
        Collection, _, environment = self.check_runtime()
        self.assertIs(Collection, self.Collection)
        self.assertEqual(environment['anki'], anki.buildinfo.version)
        self.assertEqual(environment['anki_compatibility'], 'passed')
        self.assertEqual(environment['platform'], 'Windows x64')
        self.assertEqual(environment['pymupdf'], '1.28.2')

    def test_patch_and_future_version_strings_use_real_capabilities(self):
        # These labels use the installed native backend: the version is metadata,
        # while the same real sync/export/import operations decide compatibility.
        for version in ('26.09.3', '99.1.2.dev'):
            with self.subTest(version=version), patch('anki.buildinfo.version', version):
                _, _, environment = self.check_runtime()
                self.assertEqual(environment['anki'], version)
                self.assertEqual(environment['anki_compatibility'], 'passed')

    def test_probe_does_not_read_user_templates_or_require_their_media(self):
        template_root = (sync.local_config.ROOT / 'anki-template').resolve()
        read_text = Path.read_text

        def read_without_user_templates(path, *args, **kwargs):
            if path.resolve().is_relative_to(template_root):
                raise AssertionError('compatibility probe must not read user templates')
            return read_text(path, *args, **kwargs)

        # The real probe has only its own synthetic media. User templates can
        # reference fonts/images available solely in the personal collection;
        # even unavailable templates must not prevent the environment check.
        with patch.object(Path, 'read_text', read_without_user_templates):
            _, _, environment = self.check_runtime()
        self.assertEqual(environment['anki_compatibility'], 'passed')

    def test_changed_export_api_reports_version_stage_and_original_error(self):
        import anki.buildinfo
        with patch.object(self.Collection, 'export_anki_package',
                          side_effect=TypeError('synthetic export API mismatch')) as export:
            with self.assertRaises(RuntimeError) as caught:
                self.check_runtime()
        message = str(caught.exception)
        self.assertIn(anki.buildinfo.version, message)
        self.assertRegex(message, 'personal|导出')
        self.assertIn('synthetic export API mismatch', message)
        export.assert_called_once()

    def test_backend_import_failure_has_actionable_original_reason(self):
        configure = Mock(side_effect=ImportError('synthetic missing native DLL'))
        with self.assertRaisesRegex(RuntimeError, 'synthetic missing native DLL'):
            self.check_runtime(configure)
        configure.assert_called_once_with(sync.DEFAULT_ANKI_PACKAGES)

    def test_existing_platform_python_venv_and_pdf_requirements_remain(self):
        cases = [
            ('platform', patch.object(runtime_check.sys, 'platform', 'linux'), 'Windows x64'),
            ('architecture', patch.object(runtime_check.platform, 'machine', return_value='arm64'),
             'Windows x64'),
            ('python', patch.object(runtime_check.sys, 'version_info', (3, 14, 0)), 'Python 3.13'),
            ('venv', patch.object(runtime_check.sys, 'prefix',
                                  str(sync.local_config.ROOT / 'other-environment')), r'\.venv'),
            ('pdf', patch.object(runtime_check.importlib.metadata, 'version', return_value='0.0'),
             'PyMuPDF'),
        ]
        for name, invalid_environment, message in cases:
            with self.subTest(requirement=name), ExitStack() as stack:
                stack.enter_context(invalid_environment)
                configure = Mock(side_effect=AssertionError('backend accessed before runtime checks'))
                with self.assertRaisesRegex(RuntimeError, message):
                    self.check_runtime(configure)
                configure.assert_not_called()


if __name__ == '__main__':
    unittest.main()
