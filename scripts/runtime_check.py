"""Verify runtime capabilities before opening a source or personal database."""
from dataclasses import replace
import importlib.metadata
import platform
from pathlib import Path
import sys
import tempfile


def _probe_backend(Collection) -> None:
    """Exercise the sync/export/import contract using disposable synthetic data."""
    try:
        from . import sync_vocabulary as sync, sync_plan, sync_packages, sync_storage
        from .export_vocabulary_note import Card
    except ImportError:
        import sync_vocabulary as sync, sync_plan, sync_packages, sync_storage
        from export_vocabulary_note import Card

    stage = '创建临时数据库'
    try:
        with tempfile.TemporaryDirectory(prefix='zot2anki-check-') as temporary:
            directory = Path(temporary)
            database = directory / 'collection.anki2'
            personal, clean = directory / 'personal.apkg', directory / 'clean.apkg'
            source = 'zotero://open-pdf/library/items/PROBEATT?annotation=PROBEANN'
            entry = Card('compatibility', '', 'synthetic definition', '',
                         f'<a href="{source}">Synthetic source</a>', ['PROBEANN'],
                         ['Zotero2Anki'], [source], [], [], '')
            binding = {'library_id': 1, 'note_key': 'PROBENOTE'}
            collection = Collection(str(database))
            try:
                stage = '笔记类型创建和更新'
                # User templates may depend on fonts/images in their personal
                # media folder. Probe only synthetic templates and media here;
                # the actual templates are validated with the candidate sync.
                front = '{{Word}}<br>{{Symbol}}'
                back = '{{FrontSide}}<hr>{{Chn}}<br>{{Example}}<br>{{Notes}}'
                css = '.card { font-family: sans-serif; }'
                model = sync._ensure_notetype(collection, front, back, css)
                model = sync._ensure_notetype(collection, front, back, css)
                deck = int(collection.decks.id(sync.DEFAULT_DECK))
                stage = '词条同步与身份保留'
                plan = sync_plan.plan_sync(collection, [entry], binding)
                stats = sync_plan.execute_plan(collection, [entry], plan, model, deck)
                nid = stats['owned_note_ids'][0]
                note = collection.get_note(nid)
                private_notes = 'Synthetic personal note <img src="probe.png">'
                note['Notes'] = private_notes
                note.add_tag('ProbePersonal')
                collection.update_note(note)
                guid = note.guid
                cid = collection.db.scalar('select id from cards where nid=?', nid)
                collection.db.execute('update cards set type=2,queue=2,reps=7,ivl=21,due=80 where id=?', cid)
                collection.db.execute(
                    'insert into revlog(id,cid,usn,ease,ivl,lastIvl,factor,time,type) '
                    'values (123456789,?,0,3,21,6,2500,1000,1)', cid)
                schedule_query = 'select id,nid,type,queue,reps,ivl,due from cards order by id'
                schedule = collection.db.all(schedule_query)
                reviews = collection.db.all('select * from revlog order by id')
                entry = replace(entry, word='compatibility updated', chn_html='updated definition')
                plan = sync_plan.plan_sync(collection, [entry], binding)
                stats = sync_plan.execute_plan(collection, [entry], plan, model, deck)
                note = collection.get_note(nid)
                if (stats['owned_note_ids'] != [nid] or note.guid != guid
                        or note['Word'] != entry.word or note['Notes'] != private_notes
                        or 'ProbePersonal' not in note.tags
                        or collection.db.all(schedule_query) != schedule
                        or collection.db.all('select * from revlog order by id') != reviews):
                    raise RuntimeError('更新未保留笔记身份、个人字段或复习记录')
                stage = '媒体读取和 personal 包导出'
                source_media = directory / 'source-media'
                source_media.mkdir()
                (source_media / 'probe.png').write_bytes(b'synthetic compatibility media')
                sync_packages.copy_required_media(collection, [nid], source_media)
                sync_packages.export_personal(collection, [nid], personal)
            finally:
                collection.close()

            stage = '数据库保存和重新打开'
            sync_storage.validate_database(database)
            collection = Collection(str(database))
            try:
                note = collection.get_note(nid)
                if (note.guid != guid or note['Word'] != entry.word or note['Notes'] != private_notes
                        or collection.get_config(sync_plan.LEDGER_KEY)['binding'] != binding
                        or collection.db.all(schedule_query) != schedule
                        or collection.db.all('select * from revlog order by id') != reviews):
                    raise RuntimeError('重新打开后笔记或复习记录不一致')
            finally:
                collection.close()

            stage = 'clean 包导出与隐私校验'
            sync_packages.build_clean(Collection, [entry], clean)
            stage = 'APKG 导入和重复导入'
            from anki.import_export_pb2 import ImportAnkiPackageRequest
            collection = Collection(str(directory / 'import.anki2'))
            try:
                collection.import_anki_package(ImportAnkiPackageRequest(package_path=str(personal)))
                imported = collection.get_note(nid)
                if imported.guid != guid or imported['Notes'] != private_notes:
                    raise RuntimeError('personal 包导入结果不一致')
                for _ in range(2):
                    collection.import_anki_package(ImportAnkiPackageRequest(package_path=str(clean)))
                shared_ids = collection.find_notes(f'note:"{sync_packages.SHARE_MODEL}"')
                if len(shared_ids) != 1 or collection.db.scalar('select count(*) from notes') != 2:
                    raise RuntimeError('clean 包导入产生重复词条或覆盖个人笔记')
                shared = collection.get_note(shared_ids[0])
                if (shared['Word'] != entry.word or shared['Chn'] != entry.chn_html
                        or shared['Notes'] or collection.get_note(nid)['Notes'] != private_notes):
                    raise RuntimeError('clean 包导入内容不一致')
            finally:
                collection.close()
    except Exception as exc:
        raise RuntimeError(f'{stage}失败：{exc}') from exc


def check_runtime(root: Path, packages: Path, configure_anki):
    if sys.platform != 'win32' or platform.machine().lower() not in ('amd64', 'x86_64'):
        raise RuntimeError('RC 仅支持 Windows x64')
    if sys.version_info[:2] != (3, 13):
        raise RuntimeError('RC 需要 Python 3.13；请运行 scripts/setup.ps1')
    if Path(sys.prefix).resolve() != (root / '.venv').resolve():
        raise RuntimeError('请使用项目 .venv；先运行 scripts/setup.ps1')
    if importlib.metadata.version('PyMuPDF') != '1.28.2':
        raise RuntimeError('PyMuPDF 版本不匹配；请重新运行 scripts/setup.ps1')
    import pymupdf
    try:
        Collection, Exporter = configure_anki(packages)
    except Exception as exc:
        raise RuntimeError(f'无法加载当前 Anki 后端：{exc}。个人数据库尚未打开。') from exc
    # Version is diagnostic information, not a compatibility allowlist. New
    # patch/minor releases use the same capability probe without code changes.
    try:
        from anki.buildinfo import version
    except ImportError:
        version = 'unknown'
    version = str(version)
    try:
        _probe_backend(Collection)
    except Exception as exc:
        raise RuntimeError(f'Anki {version} 兼容性检查未通过：{exc}。个人数据库尚未打开。') from exc
    return Collection, Exporter, {'platform': 'Windows x64', 'python': platform.python_version(),
                                  'anki': version, 'pymupdf': pymupdf.VersionBind,
                                  'anki_compatibility': 'passed'}
