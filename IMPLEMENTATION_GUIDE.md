# Implementation and operations guide

[English overview](README.md) | [中文概览](README.zh-CN.md) | [Known issues](KNOWN_ISSUES.md)

## Scope

This experimental local tool reads vocabulary organized in a Zotero Note and updates an Anki collection. It is not a background service. Identity conflicts and partial-write failures remain unresolved. Start with a dedicated test profile and synthetic vocabulary.

## Configuration

Copy `config.example.json` to `config.local.json` once. Set the exact Note title and either the Anki profile folder name or an explicit collection path. No profile is chosen automatically. See the README for each setting.

PowerShell and Python share `scripts/local_config.py`. Precedence is command-line options, private JSON, then generic current-user defaults. Relative JSON paths start at the configuration file's folder; relative command-line paths start at the shell's working directory. Empty optional strings use defaults; unknown keys and invalid types are rejected.

To inspect resolved settings without running a sync:

```powershell
python scripts/local_config.py
```

This prints private paths. Do not post the output publicly without redacting it.

For a separate test configuration, create `testing.local.json` (also ignored):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/sync_vocabulary.ps1 -Config testing.local.json
python scripts/sync_vocabulary.py --config testing.local.json
```

PowerShell accepts `-Database`, `-NoteTitle`, `-Collection`, `-AnkiProfile`, `-AnkiRoot`, `-AnkiPackages`, `-AnkiExe`, `-OutputDir`, and `-NoOnline`. An explicit profile/root overrides a stored collection unless `-Collection` is also provided. Python options are listed by `--help`.

## Expected Note format

Each vocabulary paragraph contains an annotation link whose text is the word or phrase, followed by its definition, normally in a code element. Synthetic example:

```html
<p><a href="zotero://open-pdf/library/items/TESTITEM?page=1&amp;annotation=TESTKEY">sample</a>: <code>🔉 英 [ˈsɑːmpəl] n. 示例</code></p>
```

The identifiers above are placeholders. Use real Zotero-generated links in your private Note. The parser normalizes words and combines duplicates. Missing definitions and unusual formatting are retained where possible and flagged for review. Private annotation-specific review rules belong in `review_annotation_keys`, not public source or fixtures.

## Daily operation and shortcuts

1. Save your vocabulary edits in Zotero.
2. Manually close Zotero and Anki completely.
3. Run `Sync-Zotero2Anki.cmd` or the PowerShell entry point.
4. Review the completion message and generated review TSV.
5. Check the configured Anki profile after the application opens.

Opening Anki does not itself select a specific profile. The launcher stops if either application is running; it never terminates them automatically. It disables console Quick Edit during the run, saves detailed logs, and verifies the report's run identifier before reopening Anki.

The optional installer creates a generic **Sync Zotero2Anki** shortcut pointing to the local checkout. Recreate it after moving the project. Existing shortcuts are not automatically renamed or removed.

## Sync behavior and templates

The script backs up `collection.anki2`, reads Zotero through a read-only SQLite connection, and exports parsed vocabulary. It then updates the `Zotero2Anki Vocabulary` note type and deck, applies vocabulary updates, exports packages, and writes a report.

Fields, in order: `Word`, `Symbol`, `Chn`, `Example`, `Source`, `ZoteroKeys`, `Notes`.

The migration can add missing fields to an older supported note type while preserving existing identifiers. Unknown extra fields or an unexpected number of templates cause an error. Not every custom note type is supported. Edit the files in `anki-template/` to change the managed template; test in a separate profile before syncing your main collection.

Annotation identifiers are the preferred match key, normalized words a fallback. Source links can supply missing `ZoteroKeys`. Ordinary one-to-one updates retain personal `Notes`, custom tags, and scheduling; managed fields and tags can change. Missing entries are tagged `MissingFromZotero` instead of being deleted from the main collection.

There is no complete preflight plan or rollback guarantee. Splitting or merging previously matched entries can create conflicts, and failures may occur after earlier updates have been saved.

## Examples and network privacy

The local extractor uses annotation metadata to locate PDF text and keeps at most three deduplicated examples per word. Fragments and scanned PDFs receive review tags; no OCR is performed.

Online lookup is disabled by default. Setting `no_online` to `false` allows fallback queries to Crossref and Europe PMC using vocabulary search terms. These services receive the searched terms. The intended request payload does not upload the Zotero database, full PDFs, or Anki collection. Matching and negative-cache behavior have known limitations.

## Outputs and sharing

Default local outputs under `dist/` include vocabulary and review TSV, a JSON report with statistics/paths/hashes, collection backups, logs, example caches, and personal/clean APKG variants. Treat all of them as potentially private. Collection backups can contain unrelated decks.

The clean-package process clears personal notes only for selected managed notes, then exports by deck; unrelated notes in that deck may survive filtering. Vocabulary, source links, and publication information also remain. Neither APKG variant should be committed or assumed anonymous.

TSV columns are `Word`, `Symbol`, `Chn`, `Example`, `Source`, `ZoteroKeys`, `Tags`. For manual import, use the matching note type, enable HTML, map the first six fields by name and the seventh to tags, and leave `Notes` unmapped. Manual TSV import does not implement the Python sync's identifier-based matching, so it is not an equivalent update path for renamed words.

Test APKG imports in an empty profile. Packages are snapshots, not a substitute for a tested multi-device workflow. Zotero links require the corresponding library on the receiving device; TTS uses that device's voices and does not bundle them.

## Failure and recovery

If a sync fails, do not assume nothing changed or immediately rerun it repeatedly. Keep the log, report if present, and pre-sync backup. Close Anki before inspecting or restoring collection files. Preserve the current state too: reverting to a backup loses changes made after the backup.

Validate a recovery copy in a separate profile before replacing live data. The automatic collection backup is not a complete backup of the Anki profile and media folder; keep independent Anki backups. Automatic rollback and concurrent-run locking still need implementation.

## Validation

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
python tests/integration_anki.py
node --test tests/core.test.js
```

Integration tests use synthetic notes in temporary collections and check ordinary additions, identifier-based updates, retained GUIDs/personal notes/review data, missing-entry tags, and package reimport. They need compatible Anki packages; use `--anki-packages` for a custom location.

`tests/validate_apkg.py --report <local-report-file>` can inspect generated packages, but its checks are limited and do not establish privacy safety. Real PDF extraction, mobile rendering, and legacy plugin lifecycle still need manual validation.

## Repository boundary

Version source, templates, synthetic tests, and generic docs only. Private configuration, shortcuts, databases, exports, logs, caches, test profiles, and recovery bundles are ignored. Outputs outside `dist/` require another ignore rule or a location outside the checkout.

Inspect staged files and reachable history before publishing. Ignoring a file does not sanitize earlier commits. History rewrites require coordination and cannot erase other people's copies. No license has been selected. The card template is custom-made; bundled third-party components, such as Anki Persistence, need a separate licensing review before a public release.
