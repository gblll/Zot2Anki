"""Validate generated personal/clean APKG files through Anki's official importer."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import sync_vocabulary as sync


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_package(
    collection_class,
    request_class,
    condition,
    package: Path,
    *,
    clean: bool,
    expected_notes: int,
    expected_cards: int,
) -> dict:
    with zipfile.ZipFile(package) as archive:
        names = archive.namelist()
        forbidden = [name for name in names if name.lower().endswith((".pdf", ".sqlite", ".sqlite-wal"))]
        assert not forbidden, forbidden
    with tempfile.TemporaryDirectory(prefix="zotero2anki-apkg-validation-") as directory:
        collection = collection_class(str(Path(directory) / "collection.anki2"))
        try:
            request = request_class(
                package_path=str(package),
                options={
                    "merge_notetypes": True,
                    "update_notes": condition.IMPORT_ANKI_PACKAGE_UPDATE_CONDITION_ALWAYS,
                    "update_notetypes": condition.IMPORT_ANKI_PACKAGE_UPDATE_CONDITION_ALWAYS,
                    "with_scheduling": not clean,
                    "with_deck_configs": True,
                },
            )
            collection.import_anki_package(request)
            note_ids = list(collection.find_notes(f'note:"{sync.DEFAULT_NOTETYPE}"'))
            card_ids = list(collection.find_cards(f'note:"{sync.DEFAULT_NOTETYPE}"'))
            model = collection.models.by_name(sync.DEFAULT_NOTETYPE)
            assert model is not None
            assert sync._field_names(model) == sync.DESIRED_FIELDS
            assert "{{#Example}}" in model["tmpls"][0]["afmt"]
            assert len(note_ids) == expected_notes
            assert len(card_ids) == expected_cards
            notes = [collection.get_note(note_id) for note_id in note_ids]
            assert all(note["Word"] and note["Example"] and note["ZoteroKeys"] for note in notes)
            if clean:
                assert not collection.find_notes("tag:MissingFromZotero")
            deck_names = {
                str(collection.decks.get(collection.get_card(card_id).did)["name"])
                for card_id in card_ids
            }
            assert deck_names == {sync.DEFAULT_DECK}
            nonempty_notes = sum(bool(note["Notes"]) for note in notes)
            scheduled = sum(collection.get_card(card_id).queue != 0 for card_id in card_ids)
            reviewed = sum(collection.get_card(card_id).reps > 0 for card_id in card_ids)
            if clean:
                assert nonempty_notes == 0 and scheduled == 0 and reviewed == 0
            collection.import_anki_package(request)
            assert len(collection.find_notes(f'note:"{sync.DEFAULT_NOTETYPE}"')) == expected_notes
            assert len(collection.find_cards(f'note:"{sync.DEFAULT_NOTETYPE}"')) == expected_cards
            return {
                "notes": len(note_ids),
                "cards": len(card_ids),
                "nonempty_personal_notes": nonempty_notes,
                "scheduled_cards": scheduled,
                "reviewed_cards": reviewed,
                "decks": sorted(deck_names),
                "notetype_id": int(model["id"]),
                "template_ord": int(model["tmpls"][0]["ord"]),
                "zip_entries": len(names),
                "sha256": sha256(package),
                "repeat_import_duplicates": 0,
            }
        finally:
            collection.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--anki-packages", type=Path, default=sync.DEFAULT_ANKI_PACKAGES)
    args = parser.parse_args()
    collection_class, _exporter = sync._configure_anki(args.anki_packages)
    from anki.import_export_pb2 import ImportAnkiPackageRequest, ImportAnkiPackageUpdateCondition

    report = json.loads(args.report.read_text(encoding="utf-8"))
    personal = Path(report["outputs"]["personal_apkg"])
    clean = Path(report["outputs"]["clean_apkg"])
    personal_notes = int(report["final"]["notes"])
    personal_cards = int(report["final"]["cards"])
    clean_notes = int(report["clean_package"]["active_notes"])
    results = {
        "personal": validate_package(
            collection_class,
            ImportAnkiPackageRequest,
            ImportAnkiPackageUpdateCondition,
            personal,
            clean=False,
            expected_notes=personal_notes,
            expected_cards=personal_cards,
        ),
        "clean": validate_package(
            collection_class,
            ImportAnkiPackageRequest,
            ImportAnkiPackageUpdateCondition,
            clean,
            clean=True,
            expected_notes=clean_notes,
            expected_cards=clean_notes,
        ),
    }
    assert results["personal"]["sha256"] == report["outputs"]["personal_sha256"]
    assert results["clean"]["sha256"] == report["outputs"]["clean_sha256"]
    assert results["personal"]["notetype_id"] == results["clean"]["notetype_id"]
    assert results["personal"]["template_ord"] == results["clean"]["template_ord"]
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
