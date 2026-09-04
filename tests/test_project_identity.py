"""Check new project branding without breaking stored user data identifiers."""

import json
from pathlib import Path
import re
import unittest
from unittest.mock import patch

from scripts import export_vocabulary_note as exporter
from scripts import sync_vocabulary as sync


ROOT = Path(__file__).resolve().parents[1]


class ProjectIdentityTests(unittest.TestCase):
    def test_manifest_uses_new_name_but_preserves_installed_addon_id(self):
        manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "Zot2Anki")
        self.assertEqual(manifest["applications"]["zotero"]["id"], "zotero2anki@local.invalid")

    def test_anki_note_type_deck_and_tags_remain_compatible(self):
        self.assertEqual(sync.DEFAULT_DECK, "Zotero2Anki Vocabulary")
        self.assertEqual(sync.DEFAULT_NOTETYPE, "Zotero2Anki Vocabulary")
        self.assertIn("Zotero2Anki", sync.MANAGED_TAGS)
        self.assertIn("#notetype:" + sync.DEFAULT_NOTETYPE, exporter.ANKI_HEADERS)
        records = exporter.parse_note_html(
            '<p><a href="zotero://open-pdf/library/items/TEST?annotation=TESTKEY">word</a>: '
            '<code>🔉 英 [wɜːd] n. 单词</code></p>'
        )
        cards, _ = exporter.build_cards(records)
        self.assertIn("Zotero2Anki", cards[0].tags)

    def test_plugin_entry_points_match_renamed_file_and_globals(self):
        bootstrap = (ROOT / "bootstrap.js").read_text(encoding="utf-8")
        plugin = (ROOT / "zot2anki.js").read_text(encoding="utf-8")
        core = (ROOT / "core.js").read_text(encoding="utf-8")
        self.assertIn('rootURI + "zot2anki.js"', bootstrap)
        self.assertIn("Zot2Anki.init", bootstrap)
        self.assertIn("var Zot2Anki =", plugin)
        self.assertIn("Zot2AnkiCore.buildCards", plugin)
        self.assertIn("var Zot2AnkiCore =", core)
        self.assertIn("module.exports = Zot2AnkiCore", core)

    def test_localized_ui_references_exist_in_both_languages(self):
        pane = (ROOT / "preferences/preferences.xhtml").read_text(encoding="utf-8")
        plugin = (ROOT / "zot2anki.js").read_text(encoding="utf-8")
        self.assertIn('href="zot2anki.ftl"', pane)
        self.assertIn('insertFTLIfNeeded("zot2anki.ftl")', plugin)
        references = set(re.findall(r'data-l10n-id="([^"]+)"', pane))
        references.update(re.findall(r'l10nID: "([^"]+)"', plugin))
        for language in ("en-US", "zh-CN"):
            text = (ROOT / "locale" / language / "zot2anki.ftl").read_text(encoding="utf-8")
            available = set(re.findall(r"^([a-z0-9-]+)\s*=", text, re.MULTILINE))
            self.assertTrue(references <= available, language)

    def test_launcher_cannot_bypass_python_process_check(self):
        self.assertTrue((ROOT / 'Syne_Zot2Anki.cmd').is_file())
        with patch.dict('os.environ', {'ZOT2ANKI_APPS_CLOSED_CHECKED': '1'}), patch.object(sync.sys, 'platform', 'win32'), patch.object(sync.subprocess, 'run') as process:
            process.return_value.returncode = 0
            process.return_value.stdout = '"anki.exe"'
            self.assertIn('Anki', sync._running_applications())
            self.assertEqual(process.call_count, 2)


if __name__ == "__main__":
    unittest.main()
