"""Release version validation must precede filesystem writes."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import build_release


class ReleaseVersionTests(unittest.TestCase):
    def test_valid_versions_come_from_selected_commit(self):
        for version in ('0.2.0-rc.1', '0.2.0-rc.2', '12.34.56-rc.10'):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as folder:
                output = Path(folder) / 'release'
                def fake_git(*args):
                    if args == ('show', 'selected:VERSION'):
                        return (version + '\n').encode()
                    if args == ('show', '-s', '--format=%ct', 'selected'):
                        return b'1788508800'
                    raise AssertionError(args)
                with patch.object(build_release, 'release_files', return_value=('selected', [])), patch.object(build_release, 'git', side_effect=fake_git):
                    archive, manifest = build_release.build(output, 'selected')
                    self.assertEqual(archive.name, f'Zot2Anki-v{version}-windows.zip')
                    self.assertEqual(manifest['version'], version)
                    self.assertEqual(manifest['commit'], 'selected')
                    self.assertEqual(build_release.inspect_zip(archive), manifest)
                    before = archive.read_bytes()
                    with self.assertRaisesRegex(RuntimeError, 'output exists'):
                        build_release.build(output, 'selected')
                    self.assertEqual(archive.read_bytes(), before)

    def test_invalid_versions_do_not_create_outputs(self):
        for version in ('', '0.2.0', 'v0.2.0-rc.2', '0.2.0-rc.2/../x',
                        '../0.2.0-rc.2', '0.2.0-rc.2\\x', '0.2.0-rc.2+meta',
                        '0.2.0-rc.-1', '０.2.0-rc.2', '0.2.0-rc.2\nextra'):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as folder:
                output = Path(folder) / 'release'
                with patch.object(build_release, 'release_files', return_value=('selected', [])), patch.object(build_release, 'git', return_value=version.encode()):
                    with self.assertRaisesRegex(RuntimeError, 'Unexpected RC version'):
                        build_release.build(output)
                self.assertFalse(output.exists())
