import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import local_config as config
from scripts import export_vocabulary_note as exporter
from scripts import sync_vocabulary as sync


class LocalConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.path = self.root / "settings.json"
        self.default_patch = patch.object(config, "DEFAULT_CONFIG", self.path)
        self.default_patch.start()
        self.addCleanup(self.default_patch.stop)

    def write_config(self, **values):
        self.path.write_text(json.dumps(values, ensure_ascii=False), encoding="utf-8")

    def test_no_implicit_profile_selection(self):
        with self.assertRaisesRegex(config.ConfigError, "note_title"):
            config.resolve_config()
        with self.assertRaisesRegex(config.ConfigError, "No profile is chosen"):
            config.resolve_config(overrides={"note_title": "Vocabulary"})

    def test_explicit_missing_config_is_rejected(self):
        with self.assertRaisesRegex(config.ConfigError, "Configuration not found"):
            config.resolve_config(self.path)

    def test_relative_json_paths_and_unicode_profile(self):
        self.write_config(note_title="测试笔记", anki_root="test-data", anki_profile="测试用户", output_dir="exports")
        values = config.resolve_config()
        self.assertEqual(values["collection"], self.root / "test-data" / "测试用户" / "collection.anki2")
        self.assertEqual(values["output_dir"], self.root / "exports")
        self.assertTrue(values["no_online"])

    def test_cli_paths_take_precedence_and_use_cwd(self):
        self.write_config(note_title="Old", collection="old.anki2", no_online=False)
        values = config.resolve_config(overrides={"note_title": "New", "collection": Path("new.anki2"), "no_online": True})
        self.assertEqual(values["note_title"], "New")
        self.assertEqual(values["collection"], Path("new.anki2").resolve())
        self.assertTrue(values["no_online"])

    def test_explicit_profile_can_override_stored_collection(self):
        self.write_config(note_title="Vocabulary", collection="old.anki2", anki_root="profiles")
        values = config.resolve_config(overrides={"anki_profile": "Testing"})
        self.assertEqual(values["collection"], self.root / "profiles" / "Testing" / "collection.anki2")

    def test_explicit_collection_wins_over_profile(self):
        self.write_config(note_title="Vocabulary", anki_profile="Testing")
        target = self.root / "explicit.anki2"
        values = config.resolve_config(overrides={"collection": target})
        self.assertEqual(values["collection"], target)

    def test_empty_optional_values_use_environment_defaults(self):
        self.write_config(note_title="Vocabulary", collection="test.anki2", anki_packages="", anki_exe="")
        values = config.resolve_config()
        self.assertEqual(values["anki_packages"], config.DEFAULT_ANKI_PACKAGES.resolve())
        self.assertEqual(values["anki_exe"], (config.DEFAULT_ANKI_INSTALL / "Anki.exe").resolve())

    def test_environment_and_home_expansion(self):
        self.write_config(note_title="Vocabulary", collection="$Z2A_TEST_PATH/test.anki2", database="~/Zotero/zotero.sqlite")
        with patch.dict("os.environ", {"Z2A_TEST_PATH": str(self.root)}):
            values = config.resolve_config()
        self.assertEqual(values["collection"], self.root / "test.anki2")
        self.assertEqual(values["database"], Path.home() / "Zotero" / "zotero.sqlite")

    def test_invalid_configuration_fails_early(self):
        for extra in ({"no_online": "false"}, {"note_title": 42}, {"unknown": True},
                      {"review_annotation_keys": "TESTKEY"}, {"anki_profile": "../escape"}):
            with self.subTest(extra=extra):
                values = {"note_title": "Vocabulary", "anki_profile": "Testing"}
                values.update(extra)
                self.write_config(**values)
                with self.assertRaises(config.ConfigError):
                    config.resolve_config()

    def test_malformed_json_and_non_object_are_rejected(self):
        for content in ("{", "[]", "null"):
            self.path.write_text(content, encoding="utf-8")
            with self.assertRaises(config.ConfigError):
                config.resolve_config()

    def test_export_does_not_require_anki_profile(self):
        self.write_config(note_title="Vocabulary")
        args = exporter._build_argument_parser().parse_args([])
        config.apply_config(args, require_collection=False)
        self.assertEqual(args.note_title, "Vocabulary")
        self.assertFalse(hasattr(args, "collection"))

    def test_python_and_launcher_resolve_same_settings(self):
        self.write_config(note_title="测试笔记", collection="collection.anki2", no_online=False, review_annotation_keys=["testkey"])
        args = sync._parser().parse_args(["--config", str(self.path)])
        config.apply_config(args)
        result = subprocess.run(
            [sys.executable, str(config.ROOT / "scripts/local_config.py"), "--config", str(self.path)],
            check=True, capture_output=True, text=True,
        )
        values = json.loads(result.stdout)
        for key in ("database", "collection", "anki_packages", "output_dir"):
            self.assertEqual(values[key], str(getattr(args, key)))
        self.assertEqual(values["note_title"], args.note_title)
        self.assertEqual(values["no_online"], args.no_online)
        self.assertEqual(args.review_annotation_keys, ["TESTKEY"])

    def test_example_configuration_requires_profile_selection(self):
        with self.assertRaisesRegex(config.ConfigError, "No profile is chosen"):
            config.resolve_config(config.ROOT / "config.example.json")


if __name__ == "__main__":
    unittest.main()
