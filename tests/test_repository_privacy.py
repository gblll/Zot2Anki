"""Basic source-control guardrails, not a comprehensive secret scanner."""

from pathlib import Path
import re
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("git") and (ROOT / ".git").exists(), "Git checkout required")
class RepositoryPrivacyTests(unittest.TestCase):
    def test_versioned_files_do_not_contain_machine_paths_or_private_artifacts(self):
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=ROOT, check=True, capture_output=True,
        )
        for filename in result.stdout.decode("utf-8").split("\0"):
            if not filename:
                continue
            with self.subTest(file=filename):
                relative = Path(filename)
                self.assertNotEqual(relative.name, "config.local.json")
                self.assertNotIn(relative.suffix.lower(), {".anki2", ".apkg", ".sqlite", ".lnk", ".bundle", ".pdf"})
                self.assertFalse(filename.startswith(("dist/", ".zotero-test-")))
                content = (ROOT / relative).read_text(encoding="utf-8")
                self.assertIsNone(re.search(r"\b[A-Za-z]:[\\/]", content), "Hard-coded drive path found")
                self.assertIsNone(re.search(r"/(?:Users|home)/[^/\s]+/", content), "Hard-coded user home found")

    def test_private_config_shortcuts_and_recovery_bundles_are_ignored(self):
        filenames = ["config.local.json", "private.local.json", "private.lnk", "recovery.bundle", "dist/report.json"]
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", *filenames],
            cwd=ROOT, check=True, capture_output=True, text=True,
        )
        self.assertEqual(result.stdout.splitlines(), filenames)


if __name__ == "__main__":
    unittest.main()
