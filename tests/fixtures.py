"""Entirely synthetic Zotero/PDF/Anki fixtures for CI and failure injection."""
import json
from pathlib import Path
import sqlite3

from scripts import sync_vocabulary as sync


def create_source(root: Path):
    import pymupdf
    database = root / 'zotero.sqlite'
    pdf = root / 'storage' / 'ATT' / 'paper.pdf'
    pdf.parent.mkdir(parents=True)
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), 'The readiness metric was evaluated carefully across all enrolled participants.')
    rect = page.search_for('readiness')[0] * ~page.transformation_matrix
    position = json.dumps({'pageIndex': 0, 'rects': [list(rect)]})
    doc.save(pdf)
    doc.close()
    db = sqlite3.connect(database)
    try:
        db.executescript('''
            CREATE TABLE libraries (libraryID INTEGER PRIMARY KEY, type TEXT);
            CREATE TABLE groups (groupID INTEGER, libraryID INTEGER);
            CREATE TABLE items (itemID INTEGER PRIMARY KEY, key TEXT, libraryID INTEGER);
            CREATE TABLE itemNotes (itemID INTEGER, title TEXT, note TEXT);
            CREATE TABLE deletedItems (itemID INTEGER);
            CREATE TABLE itemAnnotations (itemID INTEGER, parentItemID INTEGER, text TEXT, pageLabel TEXT, position TEXT);
            CREATE TABLE itemAttachments (itemID INTEGER, parentItemID INTEGER, path TEXT);
            CREATE TABLE itemData (itemID INTEGER, fieldID INTEGER, valueID INTEGER);
            CREATE TABLE fields (fieldID INTEGER, fieldName TEXT);
            CREATE TABLE itemDataValues (valueID INTEGER, value TEXT);
            INSERT INTO libraries VALUES (1, 'user'), (2, 'group');
            INSERT INTO groups VALUES (123, 2);
            INSERT INTO items VALUES (1, 'NOTE', 1), (2, 'ANN', 1), (3, 'ATT', 1), (4, 'PAPER', 1);
            INSERT INTO itemAttachments VALUES (3, 4, 'storage:paper.pdf');
            INSERT INTO fields VALUES (1, 'title');
            INSERT INTO itemDataValues VALUES (1, 'Synthetic private paper title');
            INSERT INTO itemData VALUES (4, 1, 1);
        ''')
        db.execute('INSERT INTO itemAnnotations VALUES (2,3,?,?,?)', ('readiness', '1', position))
        db.execute('INSERT INTO itemNotes VALUES (1,?,?)', ('Vocabulary',
                   '<p><a href="zotero://open-pdf/library/items/ATT?page=1&amp;annotation=ANN">readiness</a>: <code>n. readiness definition</code></p>'))
        db.commit()
    finally:
        db.close()
    return database


def create_config(root: Path):
    database = create_source(root)
    collection = root / 'Anki2' / '测试 Profile' / 'collection.anki2'
    collection.parent.mkdir(parents=True)
    Collection, _ = sync._configure_anki(sync.DEFAULT_ANKI_PACKAGES)
    col = Collection(str(collection))
    col.close()
    config = root / 'config.local.json'
    config.write_text(json.dumps({'database': str(database), 'note_title': 'Vocabulary',
                     'collection': str(collection), 'anki_packages': str(sync.DEFAULT_ANKI_PACKAGES),
                     'anki_root': str(root / 'Anki2'), 'output_dir': str(root / 'output'), 'no_online': True}), encoding='utf-8')
    return config, collection
