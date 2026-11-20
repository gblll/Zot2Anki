from pathlib import Path
from contextlib import closing
import sqlite3
import json
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from scripts import sync_packages as packages, sync_vocabulary as sync
from scripts.vocabulary_examples import ExampleCandidate
from tests.test_sync_identity import card


class PackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.Collection, _ = sync._configure_anki(sync.DEFAULT_ANKI_PACKAGES)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_personal_exports_exact_ids_and_scheduling(self):
        col = self.Collection(str(self.root / 'collection.anki2'))
        try:
            model = sync._ensure_notetype(col, '{{Word}}', '{{Notes}}', '')
            deck = col.decks.id(sync.DEFAULT_DECK)
            managed = col.new_note(model)
            managed['Word'] = 'managed'
            managed['Notes'] = 'private notes <img src="private.png">'
            managed.tags = ['private_tag', 'MissingFromZotero']
            col.add_note(managed, deck)
            private = col.new_note(model)
            private['Word'] = 'unrelated secret'
            col.add_note(private, deck)
            (Path(col.media.dir()) / 'private.png').write_bytes(b'synthetic image')
            col.db.execute('update cards set type=2,queue=2,reps=7,ivl=21,due=80 where nid=?', managed.id)
            out = self.root / 'personal.apkg'
            packages.export_personal(col, [managed.id], out)
        finally:
            col.close()
        with zipfile.ZipFile(out) as z:
            raw = self.root / 'raw.sqlite'
            raw.write_bytes(z.read('collection.anki21'))
            db = sqlite3.connect(raw)
            try:
                self.assertEqual(db.execute('select count(*) from notes').fetchone()[0], 1)
                self.assertIn('private notes', db.execute('select flds from notes').fetchone()[0])
                self.assertEqual(db.execute('select queue,reps,ivl,due from cards').fetchone(), (2,7,21,80))
                self.assertIn(b'private.png', z.read('media'))
                media = json.loads(z.read('media'))
                image = next(key for key, name in media.items() if name == 'private.png')
                self.assertEqual(z.read(image), b'synthetic image')
            finally:
                db.close()

    def test_clean_raw_privacy_and_reimport_isolation(self):
        vocabulary = card('word', 'SECRETANN')
        vocabulary.source_html += '<a href="file:///private">Private paper title</a>'
        vocabulary.example_html = '<img src="secret.png">private local sentence'
        vocabulary.chn_html = 'meaning <img src="secret.png">[sound:secret.mp3]'
        vocabulary.tags += ['private_tag']
        vocabulary.examples = [ExampleCandidate('private local sentence with word', 'local_sentence', title='private paper')]
        clean = self.root / 'clean.apkg'
        stats = packages.build_clean(self.Collection, [vocabulary], clean)
        self.assertEqual(stats['notes'], 1)
        self.assertEqual(stats['media'], 0)
        with zipfile.ZipFile(clean) as z:
            data = z.read('collection.anki21')
            for private in (b'SECRETANN', b'private_tag', b'private paper', b'secret.png', b'secret.mp3'):
                self.assertNotIn(private, data)
        col = self.Collection(str(self.root / 'import.anki2'))
        try:
            model = sync._ensure_notetype(col, '{{Word}}', '{{Notes}}', '')
            personal = col.new_note(model)
            personal['Word'] = 'word'
            personal['Notes'] = 'keep my notes'
            col.add_note(personal, 1)
            guid = personal.guid
            from anki.import_export_pb2 import ImportAnkiPackageRequest
            options = dict(merge_notetypes=True, with_scheduling=True,
                           with_deck_configs=True)
            col.import_anki_package(ImportAnkiPackageRequest(package_path=str(clean), options=options))
            col.import_anki_package(ImportAnkiPackageRequest(package_path=str(clean), options=options))
            self.assertEqual(col.db.scalar('select count(*) from notes'), 2)
            self.assertEqual(col.get_note(personal.id).guid, guid)
            self.assertEqual(col.get_note(personal.id)['Notes'], 'keep my notes')
            # A separately generated package must merge by stable shared GUID too.
            another = self.root / 'another.apkg'
            vocabulary.chn_html = 'updated public meaning'
            packages.build_clean(self.Collection, [vocabulary], another)
            col.import_anki_package(ImportAnkiPackageRequest(package_path=str(another), options=options))
            self.assertEqual(col.db.scalar('select count(*) from notes'), 2)
            shared_id = next(nid for nid in col.find_notes('') if nid != personal.id)
            self.assertEqual(col.get_note(shared_id)['Chn'], 'updated public meaning')
            self.assertEqual(col.get_note(personal.id)['Notes'], 'keep my notes')
        finally:
            col.close()

    def test_sequential_clean_builds_update_by_default_and_keep_reviews(self):
        from anki.import_export_pb2 import ImportAnkiPackageRequest
        item = card('word', 'A')
        first, second = self.root / 'first.apkg', self.root / 'second.apkg'
        packages.build_clean(self.Collection, [item], first)
        item.chn_html = 'new definition'
        packages.build_clean(self.Collection, [item], second)
        col = self.Collection(str(self.root / 'import.anki2'))
        try:
            col.import_anki_package(ImportAnkiPackageRequest(package_path=str(first)))
            nid, cid = col.db.scalar('select id from notes'), col.db.scalar('select id from cards')
            first_revision = col.db.scalar('select mod from notes')
            self.assertGreater(first_revision, 0)
            col.db.execute('update cards set type=2,queue=2,reps=7,ivl=21,due=80 where id=?', cid)
            col.db.execute('insert into revlog values (123456789,?,0,3,21,6,2500,1000,1)', cid)
            reviews = col.db.all('select * from revlog')
            schedule = col.db.all('select id,nid,type,queue,reps,ivl,due from cards')
            result = col.import_anki_package(ImportAnkiPackageRequest(package_path=str(second)))
            self.assertEqual(len(result.log.updated), 1)
            self.assertEqual(col.get_note(nid)['Chn'], 'new definition')
            self.assertGreater(col.db.scalar('select mod from notes'), first_revision)
            self.assertEqual(col.db.all('select * from revlog'), reviews)
            self.assertEqual(col.db.all('select id,nid,type,queue,reps,ivl,due from cards'), schedule)
        finally:
            col.close()

    def test_build_clock_wait_is_bounded_if_wall_clock_stalls_or_reverses(self):
        for wall, monotonic in [(100.5, [0, 2]), (99.0, [0])]:
            with self.subTest(wall=wall), patch.object(packages.time, 'time', return_value=wall), \
                    patch.object(packages.time, 'monotonic', side_effect=monotonic), \
                    patch.object(packages.time, 'sleep') as sleep:
                with self.assertRaises(packages.StorageError):
                    packages._wait_for_next_build_second(100)
                sleep.assert_not_called()

    def test_css_media_accepts_whitespace_quotes_and_multiple_notes(self):
        source = self.root / 'original-media'
        source.mkdir()
        for name in ('_font.woff2', '_background (1).png', '_plain.png'):
            (source / name).write_bytes(name.encode())
        col = self.Collection(str(self.root / 'media.anki2'))
        try:
            css = '''@font-face { src: url( "_font.woff2" ); }
                     .card { background: URL( '_background (1).png' ); }
                     .front { background: url(  _plain.png  ); }'''
            model = sync._ensure_notetype(col, '{{Word}}', '{{Notes}}', css)
            ids = []
            for word in ('one', 'two'):
                note = col.new_note(model)
                note['Word'] = word
                col.add_note(note, 1)
                ids.append(note.id)
            copied = packages.copy_required_media(col, ids, source)
            self.assertEqual(set(copied), {'_font.woff2', '_background (1).png', '_plain.png'})
            for name in copied:
                self.assertEqual((Path(col.media.dir()) / name).read_bytes(), (source / name).read_bytes())
        finally:
            col.close()

    def test_clean_preserves_literal_entities_as_distinct_words(self):
        words = ['<word>', '&lt;word&gt;']
        self.assertNotEqual(*[packages.share_guid(word) for word in words])
        path = self.root / 'literal.apkg'
        result = packages.build_clean(self.Collection, [card(word, str(index)) for index, word in enumerate(words)], path)
        self.assertEqual(result['notes'], 2)
        with zipfile.ZipFile(path) as package:
            raw = self.root / 'literal.sqlite'
            raw.write_bytes(package.read('collection.anki21'))
        with closing(sqlite3.connect(raw)) as db:
            fields = {row[0].split('\x1f')[0] for row in db.execute('select flds from notes')}
        self.assertEqual(fields, {'&lt;word&gt;', '&amp;lt;word&amp;gt;'})

    def test_only_verified_public_examples_survive(self):
        item = card('word', 'A')
        item.examples = [ExampleCandidate('A public sentence contains the word in context.', 'online',
                                          title='Public paper', doi='10.1000/test', verified_provider='crossref')]
        fields = packages.share_fields(item)
        self.assertIn('Public paper', fields[3])
        self.assertNotIn('zotero://', ''.join(fields))

    def test_validator_rejects_hidden_notes_metadata_media_and_raw_schedule(self):
        source = self.root / 'clean.apkg'
        packages.build_clean(self.Collection, [card('word', 'A')], source)
        with zipfile.ZipFile(source) as z:
            base = {name: z.read(name) for name in z.namelist()}
        mutations = [
            "update notes set tags=' private_tag '",
            "update cards set queue=2,reps=5,ivl=12",
            "update col set conf='{\"private_setting\":\"secret\"}'",
            "update notes set sfld='secret side channel'",
            "update notes set mod=9999999999",
            "update col set mod=123456789",
            "update cards set mod=123456789",
            "create table secrets(value); insert into secrets values('secret')",
            "insert into notes select id+1,'private-guid',mid,mod,usn,tags,flds,sfld,csum,flags,data from notes",
        ]
        for index, sql in enumerate(mutations):
            with self.subTest(sql=sql):
                raw = self.root / f'attack-{index}.sqlite'
                raw.write_bytes(base['collection.anki21'])
                db = sqlite3.connect(raw)
                try:
                    db.executescript(sql)
                    db.commit()
                finally:
                    db.close()
                attack = self.root / f'attack-{index}.apkg'
                with zipfile.ZipFile(attack, 'w') as z:
                    for name, data in base.items():
                        z.writestr(name, raw.read_bytes() if name in ('collection.anki21', 'collection.anki2') else data)
                with self.assertRaises(packages.StorageError):
                    packages.validate_package(attack, clean=True)
        attack = self.root / 'media-attack.apkg'
        with zipfile.ZipFile(attack, 'w') as z:
            for name, data in base.items():
                z.writestr(name, b'{"0":"private.png"}' if name == 'media' else data)
            z.writestr('0', b'private media')
        with self.assertRaises(packages.StorageError):
            packages.validate_package(attack, clean=True)

        different = self.root / 'different-databases.apkg'
        raw = self.root / 'different.sqlite'
        raw.write_bytes(base['collection.anki21'])
        db = sqlite3.connect(raw)
        try:
            db.execute('update notes set mod=0')
            db.commit()
        finally:
            db.close()
        with zipfile.ZipFile(different, 'w') as z:
            for name, data in base.items():
                z.writestr(name, raw.read_bytes() if name == 'collection.anki2' else data)
        with self.assertRaisesRegex(packages.StorageError, '物理数据库不一致'):
            packages.validate_package(different, clean=True)
        with self.assertRaisesRegex(packages.StorageError, '构建时间'):
            packages.validate_package(source, clean=True, expected_build_revision=0)

    def test_validator_checks_unused_model_and_deck_metadata(self):
        source = self.root / 'clean.apkg'
        packages.build_clean(self.Collection, [card('word', 'A')], source)
        with zipfile.ZipFile(source) as z:
            base = {name: z.read(name) for name in z.namelist()}
        for column in ('models', 'decks'):
            raw = self.root / (column + '.sqlite')
            raw.write_bytes(base['collection.anki21'])
            db = sqlite3.connect(raw)
            try:
                value = json.loads(db.execute('select ' + column + ' from col').fetchone()[0])
                next(iter(value.values()))['private_metadata'] = 'secret'
                db.execute('update col set ' + column + '=?', (json.dumps(value),))
                db.commit()
            finally:
                db.close()
            attack = self.root / (column + '.apkg')
            with zipfile.ZipFile(attack, 'w') as z:
                for name, data in base.items():
                    z.writestr(name, raw.read_bytes() if name in ('collection.anki21', 'collection.anki2') else data)
            with self.assertRaises(packages.StorageError):
                packages.validate_package(attack, clean=True)
