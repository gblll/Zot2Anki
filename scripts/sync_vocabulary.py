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
import uuid
from typing import Any

try:
    from scripts import local_config, sync_plan, sync_storage, sync_packages, runtime_check
    from scripts import export_vocabulary_note as vocabulary
    from scripts.vocabulary_examples import extract_annotation_key
except ModuleNotFoundError:
    import local_config, sync_plan, sync_storage, sync_packages, runtime_check
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
                "无法读取本地进程列表；请在允许查询进程的 Windows 终端重试。不会绕过应用状态检查。"
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


def sync_cards(collection, cards, model, deck_id, *, binding, allow_large_removal=False):
    plan = sync_plan.plan_sync(collection, cards, binding, allow_large_removal=allow_large_removal)
    return sync_plan.execute_plan(collection, cards, plan, model, deck_id)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="同步 Zotero 生词本到 Anki，并生成 TSV/APKG。")
    parser.add_argument("--config", type=Path, help="Private JSON settings (default: config.local.json)")
    parser.add_argument("--database", type=Path)
    parser.add_argument("--note-title")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--collection", type=Path)
    parser.add_argument("--anki-packages", type=Path)
    parser.add_argument("--anki-profile")
    parser.add_argument("--anki-root", type=Path)
    parser.add_argument("--anki-exe", type=Path)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-large-removal", action="store_true")
    parser.add_argument("--refresh-examples", action="store_true")
    parser.add_argument("--recover", type=Path, help="Finish output publication for a committed run journal")
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


def check_output_directory(output_dir: Path):
    root = local_config.ROOT.resolve()
    if output_dir.is_relative_to(root) and (root / '.git').exists():
        relative = (output_dir / 'privacy-probe.json').relative_to(root)
        result = subprocess.run(['git', 'check-ignore', '--no-index', '--quiet', str(relative)], cwd=root)
        if result.returncode != 0:
            raise SyncError('仓库内输出目录未被 Git 忽略，停止运行')


def _profile_name(args):
    # Only a canonical Anki profile path is safe to use with Anki's -p option.
    collection = args.collection.resolve()
    root = args.anki_root.resolve()
    if collection.name == 'collection.anki2' and collection.parent.parent == root:
        return collection.parent.name
    return None


def main(argv: list[str] | None = None) -> int:
    _configure_utf8_console()
    args = _parser().parse_args(argv)
    local_config.apply_config(args, require_collection=not (args.check or args.recover),
                              require_source=not (args.check or args.recover))
    Collection, _Exporter, environment = runtime_check.check_runtime(
        local_config.ROOT, args.anki_packages, _configure_anki)
    if args.check:
        print(json.dumps({'environment': environment, 'status': 'ok'}, ensure_ascii=False))
        return 0
    if args.recover:
        if _running_applications():
            raise SyncError('请手动关闭 Anki 和 Zotero 后恢复产物')
        state = sync_storage.recover_outputs(args.recover.resolve())
        print('数据库已提交，剩余产物整理完成：' + str(args.recover))
        return 0
    running = _running_applications()
    if running:
        raise SyncError('检测到 ' + '、'.join(running) + ' 正在运行；请手动关闭后重试。')
    output_dir = args.output_dir.resolve()
    check_output_directory(output_dir)
    collection_path = args.collection.resolve()
    if not collection_path.is_file():
        raise SyncError('找不到 Anki collection')
    timestamp = args.timestamp or datetime.now().strftime('%Y%m%d-%H%M%S')
    if not re.fullmatch(r'[0-9A-Za-z_-]+', timestamp):
        raise SyncError('运行时间标识含非法字符')
    run_id = timestamp + '-' + uuid.uuid4().hex[:12]
    output_dir.mkdir(parents=True, exist_ok=True)
    staging = output_dir / ('.run-' + run_id)
    staging.mkdir(exist_ok=False)
    report_path = output_dir / ('zot2anki-sync-' + run_id + '.json')
    backup = output_dir / 'backups' / ('collection-before-sync-' + run_id + '.anki2')
    backup.parent.mkdir(parents=True, exist_ok=True)
    state = {'run_id': run_id, 'stage': 'preflight', 'committed': False,
             'collection': str(collection_path), 'profile': _profile_name(args),
             'environment': environment, 'conflicts': [], 'excluded': [],
             'artifacts': [], 'outputs': {'backup': str(backup)},
             'recovery': 'After commit, use --recover with this report. Never rerun sync to finish outputs.'}
    sync_storage.atomic_json(report_path, state)
    try:
        with sync_storage.CollectionLock(collection_path):
            before = sync_storage.fingerprint(collection_path)
            state['before'] = before
            sync_storage.consistent_backup(collection_path, backup)
            if sync_storage.fingerprint(collection_path) != before:
                raise SyncError('生成备份时原库发生变化，停止同步')
            state['stage'] = 'parsing'
            sync_storage.atomic_json(report_path, state)
            note, cards, export_stats, tsv, review, mode = vocabulary.export_note(
                args.database, args.note_title, staging, run_id,
                extract_examples=True, online_fallback=not args.no_online,
                cache_path=output_dir / 'cache' / 'academic-examples.json',
                review_annotation_keys=args.review_annotation_keys,
                refresh_examples=args.refresh_examples, strict=True)
            binding = {'library_id': note.library_id, 'note_key': note.key}
            state.update(binding=binding, export=export_stats, database_mode=mode)
            front, back, css = [p.read_text(encoding='utf-8') for p in (args.front, args.back, args.css)]
            with tempfile.TemporaryDirectory(prefix='.zot2anki-candidate-', dir=collection_path.parent) as temporary:
                candidate = Path(temporary) / 'collection.anki2'
                sync_storage.consistent_backup(backup, candidate)
                collection = Collection(str(candidate))
                try:
                    plan = sync_plan.plan_sync(collection, cards, binding, allow_large_removal=args.allow_large_removal)
                    state.update(stage='planned', plan=plan, excluded=plan['excluded'])
                    sync_plan.check_model_migration(collection, plan, front, back, css)
                    sync_storage.atomic_json(report_path, state)
                    if args.dry_run:
                        state['stage'] = 'dry_run'
                        sync_storage.atomic_json(report_path, state)
                        print('Dry run complete. Report: ' + str(report_path))
                        return 0
                    state['stage'] = 'executing_candidate'
                    sync_storage.atomic_json(report_path, state)
                    model = _ensure_notetype(collection, front, back, css)
                    deck_id = int(collection.decks.id(DEFAULT_DECK))
                    stats = sync_plan.execute_plan(collection, cards, plan, model, deck_id)
                    state['sync'] = stats
                    owned_ids = stats['owned_note_ids']
                    sync_packages.copy_required_media(collection, owned_ids, collection_path.parent / 'collection.media')
                    state['stage'] = 'exporting'
                    sync_storage.atomic_json(report_path, state)
                    personal = staging / ('zot2anki-vocabulary-' + run_id + '.personal.apkg')
                    clean = staging / ('zot2anki-vocabulary-' + run_id + '.clean.apkg')
                    state['personal_package'] = sync_packages.export_personal(collection, owned_ids, personal)
                    state['clean_package'] = sync_packages.build_clean(Collection, cards, clean)
                    state['privacy'] = {'clean_allowlist': 'passed', 'local_metadata': 'omitted unless verified publicly',
                                        'private_media_in_clean': 0, 'online_enabled': not args.no_online}
                    state['final'] = {'notes': len(owned_ids), 'cards': state['personal_package']['cards']}
                finally:
                    collection.close()
                sync_storage.validate_database(candidate)
                state['candidate_fingerprint'] = sync_storage.fingerprint(candidate)
                for key, path in [('tsv', tsv), ('review_tsv', review), ('personal_apkg', personal), ('clean_apkg', clean)]:
                    final = output_dir / path.name
                    if final.exists():
                        raise SyncError('输出路径冲突')
                    state['artifacts'].append({'staged': str(path), 'final': str(final), 'sha256': sync_storage.sha256(path)})
                    state['outputs'][key] = str(final)
                state['stage'] = 'committing'
                sync_storage.atomic_json(report_path, state)
                state['after'] = sync_storage.commit_candidate(collection_path, candidate, before, _running_applications)
                state.update(stage='committed', committed=True)
                sync_storage.atomic_json(report_path, state)
        sync_storage.recover_outputs(report_path)
        print('Sync complete. Report: ' + str(report_path))
        print('Updated Anki profile: ' + (state['profile'] or '(custom collection; see report)'))
        return 0
    except Exception as exc:
        # A journal write can fail immediately after replacement. The candidate
        # hash makes the commit detectable without guessing or syncing twice.
        if getattr(exc, 'committed', False):
            state.update(committed=True, stage='committed')
        if state.get('stage') in ('committing', 'committed', 'finalizing'):
            try:
                if sync_storage.fingerprint(collection_path) == state.get('candidate_fingerprint'):
                    state.update(committed=True, stage='committed', after=state['candidate_fingerprint'])
            except OSError:
                pass
        state['error'] = str(exc)
        state['conflicts'] = getattr(exc, 'conflicts', [])
        if hasattr(exc, 'binding'):
            state['binding'] = exc.binding
        if not state['committed']:
            state['failed_stage'] = state['stage']
            state['stage'] = 'failed_before_commit'
        try:
            sync_storage.atomic_json(report_path, state)
        except OSError:
            pass
        prefix = '数据库已提交；请用 --recover 整理剩余产物。' if state['committed'] else '原 Anki 数据库未提交。'
        raise SyncError(prefix + ' Report: ' + str(report_path) + ' / ' + str(exc)) from exc


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (SyncError, vocabulary.ExportError, OSError, RuntimeError) as exc:
        print(f'同步失败：{exc}', file=sys.stderr)
        raise SystemExit(2)
