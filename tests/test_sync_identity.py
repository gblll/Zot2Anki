"""Use Anki's real backend against disposable collections, never a user's profile."""
from pathlib import Path
import tempfile
import unittest

from scripts import sync_vocabulary as sync
from scripts import sync_plan
from scripts.export_vocabulary_note import Card

BINDING = {'library_id': 1, 'note_key': 'TESTNOTE'}


def card(word, *keys):
    source = ''.join(f'<a href="zotero://open-pdf/library/items/ATT?annotation={key}">source</a>' for key in keys)
    return Card(word, '', 'meaning', '', source, list(keys), ['Zotero2Anki'], len(keys), [], [], '')


class IdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.Collection, _ = sync._configure_anki(sync.DEFAULT_ANKI_PACKAGES)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.col = self.Collection(str(Path(self.temp.name) / 'collection.anki2'))
        self.model = sync._ensure_notetype(self.col, '{{Word}}', '{{Chn}}', '')
        self.deck = self.col.decks.id(sync.DEFAULT_DECK)

    def tearDown(self):
        self.col.close()
        self.temp.cleanup()

    def run_sync(self, cards, **kw):
        plan = sync_plan.plan_sync(self.col, cards, BINDING, **kw)
        return sync_plan.execute_plan(self.col, cards, plan, self.model, self.deck)

    def test_repeat_rename_missing_and_restore_preserve_personal_state(self):
        self.run_sync([card('one', 'A'), card('two', 'B')])
        note_id = self.col.find_notes('one')[0]
        note = self.col.get_note(note_id)
        note['Notes'] = 'private notes'
        note.add_tag('private')
        guid = note.guid
        self.col.update_note(note)
        cards_before = self.col.db.all('select id,nid from cards order by id')
        self.run_sync([card('renamed', 'A')])
        self.run_sync([card('renamed', 'A'), card('two', 'B')])
        result = self.run_sync([card('renamed', 'A'), card('two', 'B')])
        self.assertEqual(result['added'], 0)
        self.assertEqual(self.col.get_note(note_id).guid, guid)
        self.assertEqual(self.col.get_note(note_id)['Notes'], 'private notes')
        self.assertIn('private', self.col.get_note(note_id).tags)
        self.assertEqual(self.col.db.all('select id,nid from cards order by id'), cards_before)
        self.assertFalse(self.col.find_notes('tag:MissingFromZotero'))

    def test_split_and_merge_conflicts_make_no_changes(self):
        self.run_sync([card('one', 'A', 'B'), card('two', 'C')])
        before = self.col.db.all('select * from notes')
        for cards in [[card('split1', 'A'), card('split2', 'B')],
                      [card('merged', 'A', 'C')],
                      [card('first', 'A'), card('second', 'A')]]:
            with self.assertRaises(sync_plan.PlanError):
                self.run_sync(cards)
            self.assertEqual(self.col.db.all('select * from notes'), before)

    def test_unowned_notes_are_neither_word_matched_nor_missing(self):
        private = self.col.new_note(self.model)
        private['Word'] = 'one'
        private['Notes'] = 'private'
        self.col.add_note(private, self.deck)
        self.run_sync([card('one', 'A')])
        self.assertEqual(len(self.col.find_notes('note:"' + sync.DEFAULT_NOTETYPE + '"')), 2)
        self.assertEqual(self.col.get_note(private.id)['Notes'], 'private')
        self.assertEqual(self.col.get_note(private.id).tags, [])

    def test_tagged_full_source_migration_only(self):
        old = self.col.new_note(self.model)
        old['Word'] = 'one'
        old['Source'] = card('one', 'A').source_html
        old.tags = ['Zotero2Anki']
        self.col.add_note(old, self.deck)
        orphan = self.col.new_note(self.model)
        orphan['Word'] = 'unknown'
        orphan.tags = ['Zotero2Anki']
        self.col.add_note(orphan, self.deck)
        plan = sync_plan.plan_sync(self.col, [card('renamed', 'A')], BINDING)
        self.assertEqual(plan['matches'], [old.id])
        self.assertIn(orphan.id, [entry['note_id'] for entry in plan['excluded']])
        sync_plan.execute_plan(self.col, [card('renamed', 'A')], plan, self.model, self.deck)
        self.assertEqual(self.col.get_note(old.id)['ZoteroKeys'], 'A')
        self.assertNotIn('MissingFromZotero', self.col.get_note(orphan.id).tags)

    def test_source_switch_empty_and_large_removal_stop(self):
        self.run_sync([card(str(i), 'K' + str(i)) for i in range(10)])
        for cards, binding in [([], BINDING), ([card('0', 'K0')], dict(BINDING, note_key='OTHER'))]:
            with self.assertRaises(sync_plan.PlanError):
                sync_plan.plan_sync(self.col, cards, binding, allow_large_removal=True)
        with self.assertRaises(sync_plan.PlanError):
            self.run_sync([card('0', 'K0')])
        self.run_sync([card('0', 'K0')], allow_large_removal=True)

    def test_shared_model_migration_refuses_private_changes(self):
        private = self.col.new_note(self.model)
        private['Word'] = 'private'
        self.col.add_note(private, self.deck)
        plan = sync_plan.plan_sync(self.col, [card('one', 'A')], BINDING)
        with self.assertRaises(sync_plan.PlanError):
            sync_plan.check_model_migration(self.col, plan, '{{Word}}', 'new template', '')

    def test_escaped_word_fallback_is_managed_only(self):
        self.run_sync([card('<word>', 'A')])
        self.run_sync([card('&lt;word&gt;', 'B')])
        notes = self.col.find_notes('note:"' + sync.DEFAULT_NOTETYPE + '"')
        self.assertEqual(len(notes), 1)
        self.assertEqual(self.col.get_note(notes[0])['Word'], '&lt;word&gt;')
