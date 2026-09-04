"""Read-only ownership planning, followed by execution on a disposable collection."""
from copy import deepcopy
import math

try:
    from .source_identity import identities_from_html, escaped_word, word_identity
except ImportError:
    from source_identity import identities_from_html, escaped_word, word_identity

LEDGER_KEY = 'zot2anki_source_binding_v1'
MODEL_NAME = 'Zotero2Anki Vocabulary'
FIELDS = ['Word', 'Symbol', 'Chn', 'Example', 'Source', 'ZoteroKeys', 'Notes']
MANAGED_TAGS = {'Zotero2Anki', 'NeedsReview', 'ContextFragment', 'OnlineExample',
                'NoExample', 'ExampleNeedsReview', 'OCRRequired', 'MissingSource', 'MissingFromZotero'}


class PlanError(RuntimeError):
    def __init__(self, message, conflicts=None):
        super().__init__(message)
        self.conflicts = conflicts or [message]


def plan_sync(collection, cards, binding: dict, *, allow_large_removal=False) -> dict:
    if not cards:
        raise PlanError('解析结果为空，停止同步')
    if not binding.get('note_key') or not isinstance(binding.get('library_id'), int):
        raise PlanError('缺少来源 Note 身份')
    ledger = deepcopy(collection.get_config(LEDGER_KEY, None))
    if ledger is not None and (ledger.get('version') != 1 or ledger.get('binding') != binding):
        raise PlanError('此 collection 已绑定另一篇 Zotero Note；RC 不支持更换来源')
    all_ids = set(map(int, collection.find_notes(f'note:"{MODEL_NAME}"')))
    notes = {nid: collection.get_note(nid) for nid in all_ids}
    owned = deepcopy(ledger['notes']) if ledger else {}
    if not set(map(int, owned)).issubset(all_ids):
        raise PlanError('托管笔记已被删除或更换类型；请恢复后重试，不能猜测归属')
    incoming = [identities_from_html(card.source_html, require_all=True) for card in cards]
    conflicts = []
    by_source = {}
    for index, (card, sources) in enumerate(zip(cards, incoming)):
        if not sources or not word_identity(card.word):
            conflicts.append({'input': index, 'reason': 'invalid_source_or_empty_word'})
        for source in sources:
            if source in by_source:
                conflicts.append({'inputs': [by_source[source], index], 'reason': 'source_used_twice', 'source': source})
            by_source[source] = index
    excluded = []
    migrated = []
    if ledger is None:
        # A tag alone is insufficient: legacy links must exactly identify a
        # unique current card. Unknown history is explicitly left unowned.
        for nid, note in notes.items():
            sources = identities_from_html(note['Source'], require_all=True) if 'Source' in note else []
            candidates = [i for i, values in enumerate(incoming) if sources and set(values) == set(sources)]
            if 'Zotero2Anki' in note.tags and len(candidates) == 1:
                owned[str(nid)] = {'sources': sources, 'word': word_identity(note['Word'])}
                migrated.append(nid)
            else:
                excluded.append({'note_id': nid, 'reason': 'legacy_unattributed' if 'Zotero2Anki' in note.tags else 'unmanaged'})
                if 'Zotero2Anki' in note.tags and sources and any(set(sources) & set(v) for v in incoming):
                    conflicts.append({'note_id': nid, 'reason': 'ambiguous_legacy_sources'})
    else:
        excluded = [{'note_id': nid, 'reason': 'unmanaged'} for nid in sorted(all_ids - set(map(int, owned)))]
    source_owners, word_owners = {}, {}
    for nid_text, entry in owned.items():
        nid = int(nid_text)
        for source in entry['sources']:
            source_owners.setdefault(source, set()).add(nid)
        word_owners.setdefault(word_identity(notes[nid]['Word']), set()).add(nid)
    for source, owners in source_owners.items():
        if len(owners) > 1:
            conflicts.append({'source': source, 'notes': sorted(owners), 'reason': 'duplicate_owned_identity'})
    matches = []
    used = {}
    for index, (card, sources) in enumerate(zip(cards, incoming)):
        candidates = set().union(*(source_owners.get(s, set()) for s in sources)) if sources else set()
        if not candidates:
            candidates = word_owners.get(word_identity(card.word), set())
        if len(candidates) > 1:
            conflicts.append({'input': index, 'notes': sorted(candidates), 'reason': 'multiple_old_notes'})
        nid = next(iter(candidates)) if len(candidates) == 1 else None
        if nid is not None and nid in used:
            conflicts.append({'inputs': [used[nid], index], 'note_id': nid, 'reason': 'old_note_used_twice'})
        if nid is not None:
            used[nid] = index
        matches.append(nid)
    if conflicts:
        raise PlanError('来源存在身份冲突；整次同步已停止', conflicts)
    missing = sorted(set(map(int, owned)) - set(used))
    threshold = max(5, math.ceil(len(owned) * .20))
    if len(missing) >= threshold and not allow_large_removal:
        raise PlanError(f'缺失 {len(missing)} 条，达到保护阈值 {threshold}；确认来源完整后可使用 --allow-large-removal')
    return {'binding': binding, 'owned': owned, 'matches': matches, 'sources': incoming,
            'missing': missing, 'excluded': excluded, 'migrated': migrated,
            'conflicts': [], 'removal_threshold': threshold,
            'new_count': sum(nid is None for nid in matches)}


def check_model_migration(collection, plan, front, back, css):
    model = collection.models.by_name(MODEL_NAME)
    if model is None:
        return
    fields = [field['name'] for field in model['flds']]
    if set(fields) - set(FIELDS) or len(model['tmpls']) != 1:
        raise PlanError('笔记类型含未知字段或卡片模板数量不为一；停止迁移')
    changed = (fields != FIELDS or model['css'] != css or
               model['tmpls'][0]['qfmt'] != front or model['tmpls'][0]['afmt'] != back)
    if changed and plan['excluded']:
        raise PlanError('模板迁移会影响未托管笔记，已停止；请先在 Anki 中为私人卡片使用独立笔记类型')


def execute_plan(collection, cards, plan, model, deck_id):
    owned = deepcopy(plan['owned'])
    counts = {'existing_before': len(owned), 'migrated_zotero_keys': len(plan['migrated']),
              'added': 0, 'updated': 0, 'unchanged': 0, 'marked_missing': 0, 'restored': 0}
    for card, nid, sources in zip(cards, plan['matches'], plan['sources']):
        note = collection.get_note(nid) if nid is not None else collection.new_note(model)
        before = (tuple(note.fields), tuple(note.tags))
        missing_before = 'MissingFromZotero' in note.tags
        for name, value in zip(FIELDS[:6], [escaped_word(card.word), card.symbol_html, card.chn_html,
                                          card.example_html, card.source_html, ' '.join(card.zotero_keys)]):
            note[name] = value
        note.tags = list(dict.fromkeys([tag for tag in note.tags if tag not in MANAGED_TAGS] + list(card.tags)))
        if nid is None:
            collection.add_note(note, deck_id)
            counts['added'] += 1
        elif before != (tuple(note.fields), tuple(note.tags)):
            collection.update_note(note)
            counts['updated'] += 1
        else:
            counts['unchanged'] += 1
        counts['restored'] += int(missing_before)
        owned[str(note.id)] = {'sources': sources, 'word': word_identity(card.word)}
    for nid in plan['missing']:
        note = collection.get_note(nid)
        if 'MissingFromZotero' not in note.tags:
            note.add_tag('MissingFromZotero')
            collection.update_note(note)
            counts['marked_missing'] += 1
    collection.set_config(LEDGER_KEY, {'version': 1, 'binding': plan['binding'], 'notes': owned})
    counts['owned_note_ids'] = sorted(map(int, owned))
    return counts
