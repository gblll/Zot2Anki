# Zotero2Anki

[English](README.md) | [简体中文](README.zh-CN.md)

Sync vocabulary already organized in a Zotero Note into Anki. The core goal is simple: add new words, update existing cards, and preserve review history and personal notes.

> Development snapshot, not a stable release. Known issues include conflicting updates when a merged entry is split, partial writes after a failed sync, and incomplete filtering of sharing packages. Read [Known issues](KNOWN_ISSUES.md), test on a separate Anki profile, and keep backups. A file named `clean.apkg` is **not** guaranteed safe to share.

## What it does

- Reads one Zotero Note selected by its exact title, without modifying Zotero.
- Parses vocabulary, pronunciation, definitions, and annotation links into a fixed Anki template.
- Matches existing notes by Zotero annotation identifier first, then by normalized word.
- Updates managed fields while preserving personal `Notes` and existing review data in ordinary one-to-one updates.
- Marks entries missing from Zotero with `MissingFromZotero`; it does not delete them from the main collection.

Zotero owns the vocabulary content. Anki owns review progress and personal `Notes`. Edits made in Anki to managed fields may be overwritten by the next sync.

PDF example extraction, optional online examples, and APKG export are additional features. The older Zotero plugin sources are retained, but the local scripts are the primary workflow.

## Requirements and first setup

The launcher targets Windows. You need Zotero, Anki desktop, and Python compatible with Anki's bundled Python packages. The integration workflow has been tested with Python 3.13 and Anki 26.5; other combinations require verification. The source syntax requires Python 3.10 or newer.

Run commands below from the repository folder:

```powershell
python -m pip install -r requirements.txt
Copy-Item config.example.json config.local.json
```

Only copy the example on first setup; do not overwrite an existing private configuration.

## Private configuration

Edit `config.local.json` on your own computer. It is ignored by Git and must not be uploaded.

| Setting | Meaning |
| --- | --- |
| `database` | Zotero database. The example uses `~/Zotero/zotero.sqlite`; change it for a custom data directory. |
| `note_title` | Exact title of your vocabulary Note. `Vocabulary` is only an example. |
| `anki_profile` | Your Anki profile folder name. No profile is selected automatically. |
| `collection` | Optional explicit path to `collection.anki2`, instead of selecting a profile. |
| `anki_packages`, `anki_exe` | Leave empty for the standard per-user Windows Anki installation; fill in for a custom installation. |
| `output_dir` | Keep `dist` to use the repository's privacy exclusions. |
| `no_online` | `true` by default: no online example queries. Set `false` only if you want external services to receive vocabulary search terms. |
| `review_annotation_keys` | Optional local-only annotation identifiers to flag for manual review. |

The Anki profile root is derived from the current user's Windows application-data folder; set `anki_root` for a custom root. JSON paths can use forward slashes, `~`, and environment variables. Relative JSON paths start at the configuration file's folder. If both `collection` and `anki_profile` are set, `collection` wins. Command-line options override local configuration.

Both PowerShell and Python use the same configuration resolver. Real paths, profile names, Note titles, and annotation identifiers belong in the local file, not source code or documentation.

## Run a sync

Save your Zotero edits, then **fully close Zotero and Anki yourself**. Double-click `Sync-Zotero2Anki.cmd`, or run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/sync_vocabulary.ps1
```

The launcher checks the environment, backs up the collection, performs the sync, exports files, and writes a report. It reopens Anki only after success. Failures leave the window open with an error summary. It never force-closes Zotero or Anki.

Optional desktop shortcut:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install_desktop_shortcut.ps1
```

The shortcut is named **Sync Zotero2Anki**. Its target is resolved from your local checkout; the shortcut itself is not versioned. The project can live in any folder.

Advanced entry points:

```powershell
python scripts/sync_vocabulary.py --help
python scripts/export_vocabulary_note.py --help
python scripts/export_vocabulary_note.py --no-examples --no-online
```

The export-only command writes TSV without opening or modifying Anki. The Python sync entry point does not reopen Anki. Full sync still requires the PDF dependency when online queries are disabled.

## Cards and outputs

Deck and note type: `Zotero2Anki Vocabulary`.

Fields: `Word`, `Symbol`, `Chn`, `Example`, `Source`, `ZoteroKeys`, `Notes`. Only `Notes` is reserved for personal edits. Templates live in `anki-template/`.

Local outputs under `dist/` include vocabulary TSV, review TSV, a sync report, collection backups, logs, example caches, and two APKG variants. Reports and logs may contain local paths and source information.

- `personal.apkg` includes learning progress and personal notes. Treat it as private.
- `clean.apkg` is intended to omit progress and personal notes, but its filtering has known gaps. Do not publish it without a separate privacy review.
- Even an export without personal notes can contain vocabulary, source titles, DOI links, and Zotero identifiers. It is not anonymous.

Generated files, databases, backups, PDFs, shortcuts, and private configurations are excluded by `.gitignore`. Ignoring a file does not delete it or remove it from earlier commits. Do not force-add private files. If you change the output folder, keep it outside the checkout or add an ignore rule before running.

## Tests and documentation

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
python tests/integration_anki.py
node --test tests/core.test.js
```

The Anki integration test creates temporary collections with synthetic data; it does not sync real vocabulary or change your existing collection. Existing tests do not cover every known sync boundary. Repository privacy tests are basic guardrails, not a comprehensive secret scanner.

- [Implementation and operations guide](IMPLEMENTATION_GUIDE.md)
- [Known issues and limitations](KNOWN_ISSUES.md)
- [Legacy plugin manual tests](tests/MANUAL-INTEGRATION.md)

No open-source license has been selected. The card template is custom-made; licensing of bundled third-party components needs separate review before a public release.
