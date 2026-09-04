import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LauncherContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.launcher = (ROOT / "Syne_Zot2Anki.cmd").read_text(encoding="utf-8")
        cls.sync_script = (ROOT / "scripts" / "sync_vocabulary.ps1").read_text(
            encoding="utf-8"
        )
        cls.python_sync_script = (
            ROOT / "scripts" / "sync_vocabulary.py"
        ).read_text(encoding="utf-8")
        cls.shortcut_installer = (
            ROOT / "scripts" / "install_desktop_shortcut.ps1"
        ).read_text(encoding="utf-8")

    def test_launcher_calls_sync_from_its_own_directory(self):
        self.assertIn('cd /d "%~dp0"', self.launcher)
        self.assertIn("-NoProfile -ExecutionPolicy Bypass", self.launcher)
        self.assertIn('-File "%~dp0scripts\\sync_vocabulary.ps1"', self.launcher)

    def test_launcher_only_pauses_after_failure(self):
        self.assertIn('if not "%sync_exit%"=="0" (', self.launcher)
        self.assertEqual(self.launcher.lower().count("pause"), 1)
        self.assertIn("endlocal & exit /b %sync_exit%", self.launcher)

    def test_powershell_prevents_quick_edit_from_pausing_sync(self):
        self.assertIn("GetConsoleMode", self.sync_script)
        self.assertIn("SetConsoleMode", self.sync_script)
        self.assertIn("0x0040", self.sync_script)
        self.assertIn("Restore-ConsoleMode", self.sync_script)

    def test_launcher_uses_only_project_venv(self):
        self.assertIn('.venv', self.sync_script)
        self.assertNotIn('Get-Command python', self.sync_script)
        self.assertIn('"--$name"', self.sync_script)
        for flag in ('check', 'dry-run', 'allow-large-removal', 'refresh-examples'):
            self.assertIn(flag, self.sync_script)

    def test_success_requires_commit_and_known_profile(self):
        self.assertIn('$report.stage -ne "complete"', self.sync_script)
        self.assertIn('$report.committed', self.sync_script)
        self.assertIn('$report.profile -and -not $NoOpenAnki', self.sync_script)
        self.assertIn('"-p"', self.sync_script)

    def test_python_cli_does_not_print_the_full_report(self):
        self.assertNotIn("print(json.dumps(report", self.python_sync_script)
        self.assertIn("Sync complete. Report:", self.python_sync_script)

    def test_launcher_uses_shared_private_configuration(self):
        self.assertIn('"local_config.py"', self.sync_script)
        self.assertNotIn("FromBase64String", self.sync_script)
        self.assertIn('"Syne_Zot2Anki"', self.shortcut_installer)

    def test_shortcut_targets_launcher_and_uses_anki_icon(self):
        self.assertIn('"Syne_Zot2Anki.cmd"', self.shortcut_installer)
        self.assertIn("$shortcut.TargetPath = $launcher", self.shortcut_installer)
        self.assertIn("$shortcut.WorkingDirectory = $repoRoot", self.shortcut_installer)
        self.assertIn('$shortcut.IconLocation = "$ankiExe,0"', self.shortcut_installer)


if __name__ == "__main__":
    unittest.main()
