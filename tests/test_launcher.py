import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import venv


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

    def test_launcher_locates_sync_without_changing_the_callers_directory(self):
        self.assertNotIn('cd /d', self.launcher.lower())
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

    def test_powershell_keeps_long_syncs_responsive_without_pipe_deadlocks(self):
        self.assertIn("ReadToEndAsync()", self.sync_script)
        self.assertIn("$stdoutTask = $process.StandardOutput.ReadToEndAsync()", self.sync_script)
        self.assertIn("$stderrTask = $process.StandardError.ReadToEndAsync()", self.sync_script)
        self.assertIn("while (-not $process.HasExited)", self.sync_script)
        self.assertIn("$process.ExitCode", self.sync_script)
        self.assertIn("TotalSeconds", self.sync_script)

    def test_launcher_uses_only_project_venv(self):
        self.assertIn('.venv', self.sync_script)
        self.assertNotIn('Get-Command python', self.sync_script)
        self.assertIn('"--$name"', self.sync_script)
        for flag in ('check', 'dry-run', 'allow-large-removal', 'refresh-examples', 'skip-invalid-sources'):
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


@unittest.skipUnless(sys.platform == "win32" and shutil.which("powershell.exe"), "Windows PowerShell required")
class LauncherProcessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="zot2anki-launcher-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name).resolve()
        cls.install = cls.root / "安装 [test] folder"
        cls.scripts = cls.install / "scripts"
        cls.scripts.mkdir(parents=True)
        cls.caller = cls.root / "调用 folder"
        cls.caller.mkdir()
        # The copied launcher can only reach disposable Python stubs. No
        # project dependencies, application packages or personal DBs are used.
        venv.EnvBuilder(with_pip=False).create(cls.install / ".venv")
        shutil.copyfile(ROOT / "scripts/sync_vocabulary.ps1", cls.scripts / "sync_vocabulary.ps1")
        shutil.copyfile(ROOT / "Syne_Zot2Anki.cmd", cls.install / "Syne_Zot2Anki.cmd")
        (cls.scripts / "sync_vocabulary.py").write_text(
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "Path(os.environ['Z2A_TEST_SYNC_LOG']).write_text(json.dumps({'argv': sys.argv[1:], 'cwd': os.getcwd()}), encoding='utf-8')\n"
            "if os.environ.get('Z2A_TEST_COMPLETE'):\n"
            "    report = Path(os.environ['Z2A_TEST_REPORT'])\n"
            "    report.write_text(json.dumps({'stage': 'complete', 'committed': True, 'profile': os.environ['Z2A_TEST_PROFILE'], 'collection': 'synthetic.anki2'}), encoding='utf-8')\n"
            "    print('Sync complete. Report: ' + str(report))\n",
            encoding="utf-8",
        )
        (cls.scripts / "local_config.py").write_text(
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "Path(os.environ['Z2A_TEST_CONFIG_LOG']).write_text(json.dumps(sys.argv[1:]), encoding='utf-8')\n"
            "print(json.dumps({'anki_exe': os.environ['Z2A_TEST_ANKI_EXE'], 'anki_root': os.environ['Z2A_TEST_ANKI_ROOT']}))\n",
            encoding="utf-8",
        )
        # Bind parameters inside PowerShell so its own native-command parser
        # cannot alter the inputs before the launcher under test receives them.
        cls.driver = cls.root / "driver.ps1"
        cls.driver.write_text(
            "param([string]$Script, [string]$InputFile, [string]$WorkingDirectory)\n"
            "$ErrorActionPreference = 'Stop'\n"
            "Set-Location -LiteralPath $WorkingDirectory\n"
            "$values = Get-Content -LiteralPath $InputFile -Raw -Encoding UTF8 | ConvertFrom-Json\n"
            "$parameters = @{}\n"
            "foreach ($property in $values.PSObject.Properties) { $parameters[$property.Name] = $property.Value }\n"
            "& $Script @parameters\n"
            "exit $LASTEXITCODE\n",
            encoding="utf-8",
        )
        cls.anki_exe = cls.root / "synthetic Anki.exe"
        compiler = cls.root / "compile.ps1"
        compiler.write_text(
            "param([string]$Output)\n"
            "$ErrorActionPreference = 'Stop'\n"
            "Add-Type -OutputAssembly $Output -OutputType WindowsApplication -TypeDefinition @'\n"
            "using System;\nusing System.IO;\nusing System.Text;\n"
            "public static class SyntheticAnki { public static void Main(string[] args) {\n"
            "for (int i = 0; i < args.Length; i++) args[i] = Convert.ToBase64String(Encoding.UTF8.GetBytes(args[i]));\n"
            "string output = Environment.GetEnvironmentVariable(\"Z2A_TEST_ANKI_LOG\");\n"
            "File.WriteAllLines(output + \".pending\", args); File.Move(output + \".pending\", output);\n"
            "} }\n'@\n",
            encoding="utf-8",
        )
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(compiler), str(cls.anki_exe)],
            check=True, capture_output=True, timeout=30,
        )

    def setUp(self):
        self.sync_log = self.root / "sync-argv.json"
        self.config_log = self.root / "config-argv.json"
        self.anki_log = self.root / "anki-argv.txt"
        for path in (self.sync_log, self.config_log, self.anki_log):
            path.unlink(missing_ok=True)
        self.anki_root = str(self.root / "配置 根目录") + "\\"
        self.profile = '测试 "quoted" profile\\'
        self.environment = dict(os.environ, Z2A_TEST_SYNC_LOG=str(self.sync_log),
                                Z2A_TEST_CONFIG_LOG=str(self.config_log), Z2A_TEST_ANKI_LOG=str(self.anki_log),
                                Z2A_TEST_REPORT=str(self.root / "合成 report.json"), Z2A_TEST_PROFILE=self.profile,
                                Z2A_TEST_ANKI_EXE=str(self.anki_exe), Z2A_TEST_ANKI_ROOT=self.anki_root)
        self.environment.pop("Z2A_TEST_COMPLETE", None)

    def run_powershell(self, **parameters):
        inputs = self.root / "parameters.json"
        inputs.write_text(json.dumps(parameters, ensure_ascii=False), encoding="utf-8")
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(self.driver),
             str(self.scripts / "sync_vocabulary.ps1"), str(inputs), str(self.caller)],
            cwd=self.root, env=self.environment, capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(self.sync_log.read_text(encoding="utf-8"))

    def test_powershell_preserves_quotes_backslashes_unicode_and_switches(self):
        title = '中文 "quoted" title \\"slash quote" ending\\\\'
        output = str(self.root / "输出 folder") + "\\"
        config = str(self.root / "配置 settings.json")
        result = self.run_powershell(Config=config, NoteTitle=title, OutputDir=output,
                                     DryRun=True, NoOnline=True, AllowLargeRemoval=True,
                                     RefreshExamples=True, SkipInvalidSources=True, NoOpenAnki=True)
        argv = result["argv"]
        for flag, value in (("--config", config), ("--note-title", title), ("--output-dir", output)):
            self.assertEqual(argv[argv.index(flag) + 1], value)
        self.assertCountEqual(argv[-5:], ["--no-online", "--dry-run", "--allow-large-removal",
                                          "--refresh-examples", "--skip-invalid-sources"])
        self.assertEqual(result["cwd"], str(self.caller))

    def test_cmd_resolves_relative_config_from_the_callers_directory(self):
        result = subprocess.run(
            [str(self.install / "Syne_Zot2Anki.cmd"), "-Config", "relative config.json", "-DryRun", "-NoOpenAnki"],
            cwd=self.caller, env=self.environment, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        recorded = json.loads(self.sync_log.read_text(encoding="utf-8"))
        self.assertEqual(recorded["cwd"], str(self.caller))
        argv = recorded["argv"]
        self.assertEqual(argv[argv.index("--config") + 1], "relative config.json")

    def test_completed_sync_preserves_config_and_anki_arguments(self):
        self.environment["Z2A_TEST_COMPLETE"] = "1"
        title = '中文 "quoted" title\\'
        config = str(self.root / "配置 folder") + "\\"
        self.run_powershell(Config=config, NoteTitle=title, AnkiRoot=self.anki_root)
        argv = json.loads(self.config_log.read_text(encoding="utf-8"))
        for flag, value in (("--config", config), ("--note-title", title), ("--anki-root", self.anki_root)):
            self.assertEqual(argv[argv.index(flag) + 1], value)
        deadline = time.monotonic() + 5
        while not self.anki_log.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(self.anki_log.is_file(), "Synthetic Anki was not launched")
        recorded = [base64.b64decode(line).decode("utf-8") for line in self.anki_log.read_text(encoding="utf-8-sig").splitlines()]
        self.assertEqual(recorded, ["-b", self.anki_root, "-p", self.profile])

    def test_no_open_anki_skips_configuration_reload_and_launch(self):
        self.environment["Z2A_TEST_COMPLETE"] = "1"
        self.run_powershell(NoOpenAnki=True)
        self.assertFalse(self.config_log.exists())
        self.assertFalse(self.anki_log.exists())


if __name__ == "__main__":
    unittest.main()
