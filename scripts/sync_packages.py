"""Explicit-note personal exports and fresh, text-only sharing packages."""
from contextlib import closing
from dataclasses import replace
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import zipfile

try:
    from .source_identity import escaped_word, word_identity
    from .sync_plan import FIELDS
    from .sync_storage import StorageError, sha256
    from . import export_vocabulary_note as vocabulary
except ImportError:
    from source_identity import escaped_word, word_identity
    from sync_plan import FIELDS
    from sync_storage import StorageError, sha256
    import export_vocabulary_note as vocabulary

SHARE_MODEL = 'Zot2Anki Shared Vocabulary v1'
SHARE_DECK = 'Zot2Anki Shared Vocabulary'
SHARE_FRONT = '{{Word}}<br>{{Symbol}}{{tts en_US:Word}}'
SHARE_BACK = '{{FrontSide}}<hr>{{Chn}}<hr>{{Example}}<br>{{Source}}'
SHARE_CSS = '.card { font-family: sans-serif; font-size: 22px; text-align: left; }'
# Anki requires config 1 even for a new-card package. This fixed default contains
# no profile preferences, learned FSRS parameters, search text or review state.
SHARE_DCONF = {'1': {'id': 1, 'name': 'Default', 'mod': 0, 'usn': 0, 'maxTaken': 60,
    'autoplay': True, 'timer': 0, 'replayq': True, 'dyn': False,
    'new': {'bury': False, 'delays': [1.0, 10.0], 'initialFactor': 2500, 'ints': [1, 4, 0], 'order': 1, 'perDay': 20},
    'rev': {'bury': False, 'ease4': 1.3, 'hardFactor': 1.2, 'ivlFct': 1.0, 'maxIvl': 36500, 'perDay': 200},
    'lapse': {'delays': [10.0], 'leechAction': 1, 'leechFails': 8, 'minInt': 1, 'mult': 0.0}}}


def share_guid(word):
    return 'z2as1_' + hashlib.sha256(('Zot2Anki/share/v1/' + word_identity(word)).encode()).hexdigest()[:32]


def plain_field(value):
    # Only learning text crosses the boundary; no arbitrary HTML, remote media,
    # script, or local files can be retained by a nested tag or HTML attribute.
    value = re.sub(r'<(script|style)\b[^>]*>.*?</\1\s*>', '', value, flags=re.I | re.S)
    value = re.sub(r'<(?:br\s*/?|/?(?:div|p|hr))>', '\n', value, flags=re.I)
    value = re.sub(r'<[^>]*>', '', value)
    value = html.unescape(value)
    value = re.sub(r'\[sound:[^\]]*\]', '', value, flags=re.I)
    return html.escape(value, quote=True).replace('\n', '<br>')


def share_fields(card):
    public = [replace(e, source_href='', page_label='', url='https://doi.org/' + e.doi)
              for e in card.examples if e.kind == 'online' and
              e.verified_provider in ('crossref', 'europe_pmc') and
              re.fullmatch(r'10\.\d{4,9}/[^\s<>"\']+', e.doi)]
    return [escaped_word(card.word), plain_field(card.symbol_html), plain_field(card.chn_html),
            vocabulary.render_examples(public, card.word),
            '<br>'.join(vocabulary._example_metadata(e) for e in public), '', '']


def copy_required_media(collection, note_ids, source_media: Path) -> list[str]:
    required = set()
    for nid in note_ids:
        note = collection.get_note(nid)
        required.update(collection.media.files_in_str(note.mid, '\x1f'.join(note.fields)))
        # Referenced template resources, including Anki's underscore convention,
        # are copied by name only. Do not copy all underscore files in a profile.
        model = note.note_type()
        for value in [model['css']] + [t[k] for t in model['tmpls'] for k in ('qfmt', 'afmt')]:
            required.update(collection.media.files_in_str(note.mid, value))
            required.update(re.findall(r'url\([\'\"]?([^\)\'\"]+)', value))
    target = Path(collection.media.dir())
    copied = []
    for name in sorted(required):
        if re.match(r'^(?:https?|data):', name, re.I):
            continue
        if Path(name).name != name or ':' in name or name in ('.', '..'):
            raise StorageError('媒体引用不是安全的单层文件名')
        source = source_media / name
        if not source.is_file():
            raise StorageError('personal 包所需媒体缺失：' + name)
        if source.is_symlink() or source.resolve().parent != source_media.resolve():
            raise StorageError('媒体引用越过个人媒体目录')
        shutil.copyfile(source, target / name)
        copied.append(name)
    return copied


def _rewrite_package(path, *, clean=False):
    # The legacy compatibility database is replaced with the same audited
    # collection, so validators and older importers see no hidden second dataset.
    with tempfile.TemporaryDirectory(prefix='zot2anki-package-') as root:
        database = Path(root) / 'raw.sqlite'
        with zipfile.ZipFile(path) as original:
            database.write_bytes(original.read('collection.anki21'))
            extras = {n: original.read(n) for n in original.namelist() if n not in ('collection.anki21', 'collection.anki2')}
        if clean:
            with closing(sqlite3.connect(database)) as db:
                db.execute("update col set conf='{}',dconf=?,tags='{}',crt=0,mod=0,scm=0,ls=0,usn=0", (json.dumps(SHARE_DCONF),))
                db.execute("update notes set mod=0,usn=0,tags='',flags=0,data=''")
                db.execute("update cards set mod=0,usn=0,type=0,queue=0,due=0,ivl=0,factor=0,reps=0,lapses=0,left=0,odue=0,odid=0,flags=0,data=''")
                db.execute('delete from revlog')
                db.execute('delete from graves')
                db.commit()
                db.execute('vacuum')
        data = database.read_bytes()
        with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as output:
            for name, value in extras.items():
                output.writestr(name, value)
            output.writestr('collection.anki21', data)
            output.writestr('collection.anki2', data)


def export_personal(collection, note_ids, path):
    from anki.import_export_pb2 import ExportAnkiPackageOptions
    from anki.collection import NoteIdsLimit
    if path.exists() or not note_ids:
        raise StorageError('personal 输出路径已存在或笔记集合为空')
    collection.export_anki_package(
        out_path=str(path),
        options=ExportAnkiPackageOptions(with_scheduling=True, with_deck_configs=True, with_media=True, legacy=True),
        limit=NoteIdsLimit(note_ids=list(note_ids)))
    _rewrite_package(path)
    return validate_package(path, expected_note_ids=set(note_ids))


def build_clean(Collection, cards, path):
    if path.exists():
        raise StorageError('clean 输出路径已存在')
    with tempfile.TemporaryDirectory(prefix='zot2anki-share-') as root:
        collection = Collection(str(Path(root) / 'collection.anki2'))
        try:
            model = collection.models.new(SHARE_MODEL)
            for name in FIELDS:
                collection.models.add_field(model, collection.models.new_field(name))
            template = collection.models.new_template('Vocabulary')
            template.update(qfmt=SHARE_FRONT, afmt=SHARE_BACK)
            collection.models.add_template(model, template)
            model['css'] = SHARE_CSS
            collection.models.add(model)
            model = collection.models.by_name(SHARE_MODEL)
            deck = collection.decks.id(SHARE_DECK)
            note_ids, expected = [], {}
            for card in cards:
                note = collection.new_note(model)
                note.fields = share_fields(card)
                note.guid = share_guid(card.word)
                note.tags = []
                collection.add_note(note, deck)
                note_ids.append(note.id)
                expected[note.guid] = note.fields
            export_personal(collection, note_ids, path)
        finally:
            collection.close()
    _rewrite_package(path, clean=True)
    result = validate_package(path, clean=True, expected_fields=expected)
    result['omitted_unverified_local_sources'] = len(cards)
    result['omitted_local_examples'] = sum(e.kind != 'online' for c in cards for e in c.examples)
    return result


def validate_package(path, *, clean=False, expected_note_ids=None, expected_fields=None):
    """Inspect every physical DB and every media entry, before any importer runs."""
    with zipfile.ZipFile(path) as package, tempfile.TemporaryDirectory() as root:
        names = package.namelist()
        if len(names) != len(set(names)):
            raise StorageError('APKG 含重复文件名')
        media = json.loads(package.read('media'))
        if not isinstance(media, dict) or any(not key.isdigit() or not isinstance(value, str) or Path(value).name != value for key, value in media.items()):
            raise StorageError('APKG 媒体映射非法')
        if set(names) != {'meta', 'media', 'collection.anki21', 'collection.anki2'} | set(media):
            raise StorageError('APKG 含未声明文件')
        if clean and media:
            raise StorageError('clean 包含媒体')
        for name in ('collection.anki21', 'collection.anki2'):
            dbpath = Path(root) / name
            dbpath.write_bytes(package.read(name))
            with closing(sqlite3.connect(dbpath)) as db:
                db.row_factory = sqlite3.Row
                if db.execute('pragma integrity_check').fetchone()[0] != 'ok':
                    raise StorageError('APKG 数据库损坏')
                notes = db.execute('select * from notes').fetchall()
                cards = db.execute('select * from cards').fetchall()
                nids = {n['id'] for n in notes}
                if expected_note_ids is not None and nids != set(expected_note_ids):
                    raise StorageError('APKG 含不在允许名单中的笔记或缺失笔记')
                if any(c['nid'] not in nids for c in cards) or {c['nid'] for c in cards} != nids:
                    raise StorageError('APKG 卡片归属不完整')
                col = db.execute('select * from col').fetchone()
                models, decks = json.loads(col['models']), json.loads(col['decks'])
                if any(str(n['mid']) not in models for n in notes) or any(str(c['did']) not in decks for c in cards):
                    raise StorageError('APKG 类型/牌组引用非法')
                if clean:
                    if len(models) != 1 or next(iter(models.values()))['name'] != SHARE_MODEL:
                        raise StorageError('clean 包含私人笔记类型')
                    model = next(iter(models.values()))
                    if ([f['name'] for f in model['flds']] != FIELDS or model['css'] != SHARE_CSS or
                            len(model['tmpls']) != 1 or model['tmpls'][0]['qfmt'] != SHARE_FRONT or model['tmpls'][0]['afmt'] != SHARE_BACK):
                        raise StorageError('clean 模板未通过允许名单')
                    if any(d['name'] not in ('Default', SHARE_DECK) for d in decks.values()):
                        raise StorageError('clean 包含私人牌组')
                    if any(col[k] != '{}' for k in ('conf', 'tags')) or json.loads(col['dconf']) != SHARE_DCONF:
                        raise StorageError('clean 包含内部配置')
                    if db.execute('select count(*) from revlog').fetchone()[0] or db.execute('select count(*) from graves').fetchone()[0]:
                        raise StorageError('clean 包含复习或删除日志')
                    actual = {}
                    for note in notes:
                        fields = note['flds'].split('\x1f')
                        if len(fields) != 7 or fields[5:] != ['', ''] or note['tags'].strip() or note['data']:
                            raise StorageError('clean 字段/标签包含私人数据')
                        if note['guid'] != share_guid(fields[0]) or note['guid'] in actual:
                            raise StorageError('clean GUID 不稳定或重复')
                        if re.search(r'zotero://|\[sound:|<(?:img|audio|video|script|iframe)\b', note['flds'], re.I):
                            raise StorageError('clean 含内部链接或媒体')
                        actual[note['guid']] = fields
                    if expected_fields is not None and actual != expected_fields:
                        raise StorageError('clean 学习内容未通过允许名单')
                    for card in cards:
                        if any(card[k] != 0 for k in ('type','queue','due','ivl','factor','reps','lapses','left','odue','odid','flags')) or card['data']:
                            raise StorageError('clean 原始调度数据未清除')
        return {'validated': True, 'notes': len(notes), 'cards': len(cards), 'media': len(media), 'sha256': sha256(path)}
