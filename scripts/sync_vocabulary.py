#!/usr/bin/env python3
"""Synchronize the Zotero vocabulary note into Anki and build deck packages."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any

try:
    from scripts import local_config
    from scripts import export_vocabulary_note as vocabulary
    from scripts.vocabulary_examples import extract_annotation_key
except ModuleNotFoundError:
    import local_config
    import export_vocabulary_note as vocabulary
    from vocabulary_examples import extract_annotation_key


DEFAULT_ANKI_PACKAGES = local_config.DEFAULT_ANKI_PACKAGES
# Persistent Anki identifiers stay unchanged when the project is rebranded.
# Changing these would disconnect this sync from existing notes and cards.
DEFAULT_DECK = "Zotero2Anki Vocabulary"
DEFAULT_NOTETYPE = "Zotero2Anki Vocabulary"
DESIRED_FIELDS = ["Word", "Symbol", "Chn", "Example", "Source", "ZoteroKeys", "Notes"]
MANAGED_TAGS = {
    "Zotero2Anki",
    "NeedsReview",
    "ContextFragment",
    "OnlineExample",
    "NoExample",
    "ExampleNeedsReview",
    "OCRRequired",
    "MissingSource",
    "MissingFromZotero",
}


class SyncError(RuntimeError):
    pass


def _configure_anki(packages: Path):
    packages = packages.expanduser().resolve()
    if not (packages / "anki" / "collection.pyc").exists() and not (packages / "anki" / "collection.py").exists():
        raise SyncError(f"找不到 Anki Python 包：{packages}")
    sys.path.insert(0, str(packages))
    from anki.collection import Collection
    from anki.exporting import AnkiPackageExporter

    return Collection, AnkiPackageExporter


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _running_applications() -> list[str]:
    if os.environ.get("ZOT2ANKI_APPS_CLOSED_CHECKED") == "1":
        return []
    if sys.platform != "win32":
        return []
    running: list[str] = []
    for label, executable in (("Zotero", "zotero.exe"), ("Anki", "anki.exe")):
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {executable}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
        )
        if result.returncode != 0:
            raise SyncError(
                "无法确认 Zotero/Anki 是否已关闭。请改用 scripts/sync_vocabulary.ps1 运行。"
            )
        if executable.casefold() in result.stdout.casefold():
            running.append(label)
    return running


def _field_names(model: dict) -> list[str]:
    return [str(field["name"]) for field in model["flds"]]


def _ensure_notetype(collection, front: str, back: str, css: str) -> dict:
    model = collection.models.by_name(DEFAULT_NOTETYPE)
    if model is None:
        model = collection.models.new(DEFAULT_NOTETYPE)
        for name in DESIRED_FIELDS:
            collection.models.add_field(model, collection.models.new_field(name))
        template = collection.models.new_template("Card 1")
        template["qfmt"] = front
        template["afmt"] = back
        collection.models.add_template(model, template)
        model["css"] = css
        collection.models.add(model)
        model = collection.models.by_name(DEFAULT_NOTETYPE)
        if model is None:
            raise SyncError("创建 Anki 笔记类型失败")
        return model

    extra = set(_field_names(model)) - set(DESIRED_FIELDS)
    if extra:
        raise SyncError(f"笔记类型包含未知字段，已停止以避免数据损失：{sorted(extra)}")
    for name in DESIRED_FIELDS:
        model = collection.models.by_name(DEFAULT_NOTETYPE)
        assert model is not None
        if name not in _field_names(model):
            collection.models.add_field(model, collection.models.new_field(name))
    for target_index, name in enumerate(DESIRED_FIELDS):
        model = collection.models.by_name(DEFAULT_NOTETYPE)
        assert model is not None
        current_index = _field_names(model).index(name)
        if current_index != target_index:
            collection.models.reposition_field(model, model["flds"][current_index], target_index)
    model = collection.models.by_name(DEFAULT_NOTETYPE)
    assert model is not None
    if len(model["tmpls"]) != 1:
        raise SyncError(f"笔记类型应只有一个卡片模板，实际为 {len(model['tmpls'])}")
    model["tmpls"][0]["qfmt"] = front
    model["tmpls"][0]["afmt"] = back
    model["css"] = css
    collection.models.save(model)
    saved = collection.models.by_name(DEFAULT_NOTETYPE)
    assert saved is not None
    return saved


def _keys_from_source(source_html: str) -> list[str]:
    decoded = html.unescape(source_html or "")
    return list(dict.fromkeys(match.upper() for match in re.findall(r"[?&]annotation=([A-Z0-9]+)", decoded, re.I)))


def _split_keys(value: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"[A-Z0-9]+", (value or "").upper())))


def _set_managed_tags(note, desired: list[str]) -> None:
    preserved = [tag for tag in note.tags if tag not in MANAGED_TAGS]
    note.tags = list(dict.fromkeys(preserved + desired))


def sync_cards(collection, cards: list[vocabulary.Card], model: dict, deck_id: int) -> dict[str, Any]:
    note_ids = list(collection.find_notes(f'note:"{DEFAULT_NOTETYPE}"'))
    key_to_note: dict[str, int] = {}
    word_to_notes: dict[str, list[int]] = {}
    migrated_keys = 0
    for note_id in note_ids:
        note = collection.get_note(note_id)
        keys = _split_keys(note["ZoteroKeys"])
        if not keys:
            keys = _keys_from_source(note["Source"])
            if keys:
                note["ZoteroKeys"] = " ".join(keys)
                collection.update_note(note)
                migrated_keys += 1
        for key in keys:
            existing = key_to_note.get(key)
            if existing is not None and existing != int(note_id):
                raise SyncError(f"annotation key {key} 同时属于多条 Anki 笔记")
            key_to_note[key] = int(note_id)
        word_to_notes.setdefault(vocabulary.dedupe_key(note["Word"]), []).append(int(note_id))

    added = 0
    updated = 0
    unchanged = 0
    restored = 0
    seen: set[int] = set()
    for card in cards:
        candidate_ids = {key_to_note[key] for key in card.zotero_keys if key in key_to_note}
        if len(candidate_ids) > 1:
            raise SyncError(f"{card.word} 的来源对应多条 Anki 笔记：{sorted(candidate_ids)}")
        note_id = next(iter(candidate_ids), None)
        if note_id is None:
            by_word = word_to_notes.get(vocabulary.dedupe_key(card.word), [])
            if len(by_word) > 1:
                raise SyncError(f"规范化单词 {card.word} 对应多条 Anki 笔记")
            note_id = by_word[0] if by_word else None
        if note_id is None:
            note = collection.new_note(model)
            note["Word"] = card.word
            note["Symbol"] = card.symbol_html
            note["Chn"] = card.chn_html
            note["Example"] = card.example_html
            note["Source"] = card.source_html
            note["ZoteroKeys"] = " ".join(card.zotero_keys)
            note["Notes"] = ""
            note.tags = list(card.tags)
            collection.add_note(note, deck_id)
            added += 1
            seen.add(int(note.id))
            continue
        note = collection.get_note(note_id)
        had_missing_tag = "MissingFromZotero" in note.tags
        before = (tuple(note.fields), tuple(note.tags))
        note["Word"] = card.word
        note["Symbol"] = card.symbol_html
        note["Chn"] = card.chn_html
        note["Example"] = card.example_html
        note["Source"] = card.source_html
        note["ZoteroKeys"] = " ".join(card.zotero_keys)
        _set_managed_tags(note, list(card.tags))
        after = (tuple(note.fields), tuple(note.tags))
        if after != before:
            collection.update_note(note)
            updated += 1
        else:
            unchanged += 1
        if had_missing_tag and "MissingFromZotero" not in note.tags:
            restored += 1
        seen.add(int(note_id))

    marked_missing = 0
    for note_id in note_ids:
        note = collection.get_note(note_id)
        if int(note_id) in seen:
            continue
        elif "MissingFromZotero" not in note.tags:
            note.add_tag("MissingFromZotero")
            collection.update_note(note)
            marked_missing += 1
    return {
        "existing_before": len(note_ids),
        "migrated_zotero_keys": migrated_keys,
        "added": added,
        "updated": updated,
        "unchanged": unchanged,
        "marked_missing": marked_missing,
        "restored": restored,
    }


def _export_package(exporter_class, collection, deck_id: int, path: Path, *, include_sched: bool) -> None:
    if path.exists():
        raise SyncError(f"输出文件已存在：{path}")
    exporter = exporter_class(collection)
    # Current Anki exporters expose deckIds() as a method and select a deck via did.
    exporter.did = deck_id
    exporter.includeSched = include_sched
    exporter.includeMedia = True
    exporter.exportInto(str(path))
    if not path.is_file() or path.stat().st_size == 0:
        raise SyncError(f"Anki 包生成失败：{path}")


def _build_clean_package(
    collection_class,
    exporter_class,
    collection_path: Path,
    output_path: Path,
) -> dict[str, int]:
    with tempfile.TemporaryDirectory(prefix="zot2anki-clean-") as temp_dir:
        temp_root = Path(temp_dir)
        temp_collection = temp_root / "collection.anki2"
        shutil.copy2(collection_path, temp_collection)
        (temp_root / "collection.media").mkdir()
        collection = collection_class(str(temp_collection))
        try:
            missing = list(
                collection.find_notes(
                    f'note:"{DEFAULT_NOTETYPE}" tag:Zotero2Anki tag:MissingFromZotero'
                )
            )
            if missing:
                collection.remove_notes(missing)
            active = list(collection.find_notes(f'note:"{DEFAULT_NOTETYPE}" tag:Zotero2Anki'))
            for note_id in active:
                note = collection.get_note(note_id)
                if note["Notes"]:
                    note["Notes"] = ""
                    collection.update_note(note)
            deck = collection.decks.by_name(DEFAULT_DECK)
            if deck is None:
                raise SyncError(f"临时 collection 中找不到牌组：{DEFAULT_DECK}")
            _export_package(exporter_class, collection, int(deck["id"]), output_path, include_sched=False)
            return {"active_notes": len(active), "excluded_missing": len(missing)}
        finally:
            collection.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="同步 Zotero 生词本到 Anki，并生成 TSV/APKG。")
    parser.add_argument("--config", type=Path, help="Private JSON settings (default: config.local.json)")
    parser.add_argument("--database", type=Path)
    parser.add_argument("--note-title")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--collection", type=Path)
    parser.add_argument("--anki-packages", type=Path)
    parser.add_argument("--front", type=Path, default=local_config.ROOT / "anki-template/front.html")
    parser.add_argument("--back", type=Path, default=local_config.ROOT / "anki-template/back.html")
    parser.add_argument("--css", type=Path, default=local_config.ROOT / "anki-template/styling.css")
    parser.add_argument("--no-online", action="store_true", default=None)
    parser.add_argument("--timestamp")
    return parser


def _configure_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    _configure_utf8_console()
    args = _parser().parse_args(argv)
    local_config.apply_config(args)
    running = _running_applications()
    if running:
        raise SyncError(
            f"检测到 {'、'.join(running)} 正在运行。请手动关闭后重试；脚本不会自动终止应用。"
        )
    timestamp = args.timestamp or datetime.now().strftime("%Y%m%d-%H%M")
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    collection_path = args.collection.expanduser().resolve()
    if not collection_path.is_file():
        raise SyncError(f"找不到 Anki collection：{collection_path}")
    for template_path in (args.front, args.back, args.css):
        if not template_path.is_file():
            raise SyncError(f"找不到模板文件：{template_path}")
    collection_class, exporter_class = _configure_anki(args.anki_packages)

    backup_dir = output_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"collection-before-sync-{timestamp}.anki2"
    if backup_path.exists():
        raise SyncError(f"备份文件已存在：{backup_path}")
    shutil.copy2(collection_path, backup_path)

    note, cards, export_stats, tsv_path, review_path, database_mode = vocabulary.export_note(
        args.database,
        args.note_title,
        output_dir,
        timestamp,
        extract_examples=True,
        online_fallback=not args.no_online,
        cache_path=output_dir / "cache" / "academic-examples.json",
        review_annotation_keys=args.review_annotation_keys,
    )
    front = args.front.read_text(encoding="utf-8")
    back = args.back.read_text(encoding="utf-8")
    css = args.css.read_text(encoding="utf-8")
    personal_path = output_dir / f"zot2anki-vocabulary-{timestamp}.personal.apkg"
    clean_path = output_dir / f"zot2anki-vocabulary-{timestamp}.clean.apkg"

    collection = collection_class(str(collection_path))
    try:
        model = _ensure_notetype(collection, front, back, css)
        deck_id = int(collection.decks.id(DEFAULT_DECK))
        sync_stats = sync_cards(collection, cards, model, deck_id)
        final_notes = len(collection.find_notes(f'note:"{DEFAULT_NOTETYPE}" tag:Zotero2Anki'))
        final_cards = len(collection.find_cards(f'note:"{DEFAULT_NOTETYPE}" tag:Zotero2Anki'))
        _export_package(exporter_class, collection, deck_id, personal_path, include_sched=True)
    finally:
        collection.close()

    clean_stats = _build_clean_package(
        collection_class,
        exporter_class,
        collection_path,
        clean_path,
    )
    report = {
        "timestamp": timestamp,
        "note": {"title": note.title, "key": note.key},
        "database_mode": database_mode,
        "export": export_stats,
        "sync": sync_stats,
        "final": {"notes": final_notes, "cards": final_cards},
        "clean_package": clean_stats,
        "outputs": {
            "tsv": str(tsv_path),
            "review_tsv": str(review_path),
            "personal_apkg": str(personal_path),
            "personal_sha256": _sha256(personal_path),
            "clean_apkg": str(clean_path),
            "clean_sha256": _sha256(clean_path),
            "backup": str(backup_path),
        },
    }
    report_path = output_dir / f"zot2anki-sync-{timestamp}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Sync complete. Report: {report_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (SyncError, vocabulary.ExportError, OSError, RuntimeError) as exc:
        print(f"同步失败：{exc}", file=sys.stderr)
        raise SystemExit(2)
