"""End-to-end check against the Anki installation bundled on this machine."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import export_vocabulary_note as vocabulary
from scripts import sync_vocabulary as sync


def card(word: str, key: str) -> vocabulary.Card:
    href = f"zotero://open-pdf/library/items/ATTACH?page=1&annotation={key}"
    return vocabulary.Card(
        word=word,
        symbol_html="<span>/wɜːd/</span>",
        chn_html="n. 测试释义",
        example_html="<div class=\"z2a-examples\">A verified example sentence contains the word.</div>",
        source_html=f'<a href="{href}">来源</a>',
        zotero_keys=[key],
        tags=["Zotero2Anki"],
        sources=[href],
        examples=[],
        review_reasons=[],
        original_definition_html="n. 测试释义",
    )


def run(packages: Path, template_dir: Path) -> None:
    collection_class, exporter_class = sync._configure_anki(packages)
    from anki.import_export_pb2 import (
        ImportAnkiPackageRequest,
        ImportAnkiPackageUpdateCondition,
    )

    front = (template_dir / "front.html").read_text(encoding="utf-8")
    back = (template_dir / "back.html").read_text(encoding="utf-8")
    css = (template_dir / "styling.css").read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="zot2anki-anki-integration-") as directory:
        root = Path(directory)
        source_path = root / "source.anki2"
        collection = collection_class(str(source_path))
        try:
            model = sync._ensure_notetype(collection, front, back, css)
            deck_id = int(collection.decks.id(sync.DEFAULT_DECK))
            first = sync.sync_cards(collection, [card("first", "KEYONE"), card("second", "KEYTWO")], model, deck_id)
            assert first["added"] == 2
            note_id = int(collection.find_notes("Word:first")[0])
            note = collection.get_note(note_id)
            original_guid = note.guid
            note["Notes"] = "personal note"
            collection.update_note(note)

            renamed = card("renamed", "KEYONE")
            renamed.chn_html = "n. updated"
            second = sync.sync_cards(collection, [renamed], model, deck_id)
            assert second["added"] == 0 and second["updated"] == 1 and second["marked_missing"] == 1
            updated_note = collection.get_note(note_id)
            assert updated_note.guid == original_guid
            assert updated_note["Word"] == "renamed" and updated_note["Notes"] == "personal note"
            assert len(collection.find_notes("tag:MissingFromZotero")) == 1
            reviewed = collection.get_card(collection.find_cards("Word:renamed")[0])
            reviewed.type = 2
            reviewed.queue = 2
            reviewed.due = 100
            reviewed.ivl = 10
            reviewed.factor = 2500
            reviewed.reps = 7
            collection.update_card(reviewed)

            personal = root / "personal.apkg"
            sync._export_package(exporter_class, collection, deck_id, personal, include_sched=True)
        finally:
            collection.close()

        clean = root / "clean.apkg"
        clean_stats = sync._build_clean_package(collection_class, exporter_class, source_path, clean)
        assert clean_stats == {"active_notes": 1, "excluded_missing": 1}

        for package, expected_notes in ((personal, 2), (clean, 1)):
            target = collection_class(str(root / f"import-{package.stem}.anki2"))
            try:
                target.import_anki_package(
                    ImportAnkiPackageRequest(
                        package_path=str(package),
                        options={
                            "merge_notetypes": True,
                            "update_notes": ImportAnkiPackageUpdateCondition.IMPORT_ANKI_PACKAGE_UPDATE_CONDITION_ALWAYS,
                            "update_notetypes": ImportAnkiPackageUpdateCondition.IMPORT_ANKI_PACKAGE_UPDATE_CONDITION_ALWAYS,
                            "with_scheduling": package == personal,
                            "with_deck_configs": True,
                        },
                    )
                )
                notes = list(target.find_notes(f'note:"{sync.DEFAULT_NOTETYPE}"'))
                assert len(notes) == expected_notes
                if package == clean:
                    only = target.get_note(notes[0])
                    assert only["Notes"] == ""
                    card_ids = target.find_cards(f'note:"{sync.DEFAULT_NOTETYPE}"')
                    assert all(
                        target.get_card(card_id).queue == 0 and target.get_card(card_id).reps == 0
                        for card_id in card_ids
                    )
                else:
                    imported = target.get_note(target.find_notes("Word:renamed")[0])
                    imported_card = target.get_card(target.find_cards("Word:renamed")[0])
                    assert imported["Notes"] == "personal note"
                    assert imported_card.queue == 2 and imported_card.reps == 7
            finally:
                target.close()
        print("Anki integration OK: update-by-key, Notes/GUID preservation, missing tag, personal/clean APKG round-trip")


def run_existing_migration(packages: Path, template_dir: Path, source_path: Path) -> None:
    collection_class, _exporter_class = sync._configure_anki(packages)
    front = (template_dir / "front.html").read_text(encoding="utf-8")
    back = (template_dir / "back.html").read_text(encoding="utf-8")
    css = (template_dir / "styling.css").read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="zot2anki-existing-migration-") as directory:
        copy_path = Path(directory) / "collection.anki2"
        shutil.copy2(source_path, copy_path)
        collection = collection_class(str(copy_path))
        try:
            note_ids = list(collection.find_notes(f'note:"{sync.DEFAULT_NOTETYPE}"'))
            card_ids = list(collection.find_cards(f'note:"{sync.DEFAULT_NOTETYPE}"'))
            before_guids = {int(note_id): collection.get_note(note_id).guid for note_id in note_ids}
            before_notes = {int(note_id): collection.get_note(note_id)["Notes"] for note_id in note_ids}
            before_schedule = {
                int(card_id): (
                    collection.get_card(card_id).queue,
                    collection.get_card(card_id).type,
                    collection.get_card(card_id).due,
                    collection.get_card(card_id).ivl,
                    collection.get_card(card_id).reps,
                )
                for card_id in card_ids
            }
            model = sync._ensure_notetype(collection, front, back, css)
            assert sync._field_names(model) == sync.DESIRED_FIELDS
            assert list(collection.find_notes(f'note:"{sync.DEFAULT_NOTETYPE}"')) == note_ids
            assert list(collection.find_cards(f'note:"{sync.DEFAULT_NOTETYPE}"')) == card_ids
            assert {int(note_id): collection.get_note(note_id).guid for note_id in note_ids} == before_guids
            assert {int(note_id): collection.get_note(note_id)["Notes"] for note_id in note_ids} == before_notes
            after_schedule = {
                int(card_id): (
                    collection.get_card(card_id).queue,
                    collection.get_card(card_id).type,
                    collection.get_card(card_id).due,
                    collection.get_card(card_id).ivl,
                    collection.get_card(card_id).reps,
                )
                for card_id in card_ids
            }
            assert after_schedule == before_schedule
            print(f"Existing collection migration OK: {len(note_ids)} notes/{len(card_ids)} cards, IDs/GUIDs/Notes/scheduling preserved")
        finally:
            collection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--anki-packages", type=Path, default=sync.DEFAULT_ANKI_PACKAGES)
    parser.add_argument("--template-dir", type=Path, default=Path("anki-template"))
    parser.add_argument("--existing-collection", type=Path)
    args = parser.parse_args()
    run(args.anki_packages, args.template_dir)
    if args.existing_collection:
        run_existing_migration(args.anki_packages, args.template_dir, args.existing_collection)
