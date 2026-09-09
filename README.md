# Zot2Anki

[English](README.md) | [简体中文](README.zh-CN.md)

**v0.2.0-rc.3 — Windows pre-release candidate.** Sync one Zotero vocabulary Note into Anki while preserving card identity, personal Notes and review history. The repository is public; this candidate is prepared as a Draft Pre-release, not a stable release.

Local example citations and source links display the paper title followed by the italic journal and the page, separated by middle dots without parentheses. Zotero `journalAbbreviation` takes priority, falling back to `publicationTitle`; absent journals are omitted. Recognized shortened words receive missing periods (e.g. `Nat Commun` → `Nat. Commun.`); full words and initialisms such as `IEEE` and `ACS` remain intact. Maintain these fields in Zotero and sync to refresh citations while retaining review history. Online examples retain their own public provenance; local journal metadata is excluded from clean packages.

## Install

Validated baseline: **Windows x64, Python 3.13, Anki 26.5**, and PyMuPDF **1.28.2**. Python and Anki must already be installed; they are not bundled. Other combinations fail the runtime gate before personal databases are opened.

Extract the Windows ZIP to a writable local folder. Chinese characters and spaces are supported. From that folder:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1
Copy-Item config.example.json config.local.json
```

Copy the configuration only on first installation. Setup creates the project's `.venv`, installs the exact Windows PDF wheel with its SHA256 checked, and opens a disposable collection to verify the Anki backend. Use `-Python <python-executable>` or `-AnkiPackages <app_packages-folder>` for nonstandard installations. Setup downloads dependencies; daily synchronization is offline by default.

## Configure

Edit the ignored `config.local.json` locally. Set `note_title` to the exact Zotero Note title, then set `anki_profile` or an explicit `collection` path. No profile is selected implicitly.

| Setting | Meaning |
| --- | --- |
| `database` | Zotero SQLite file; defaults to the current user's Zotero folder. |
| `note_title` | Exact, unique vocabulary Note title. |
| `anki_profile`, `anki_root` | Anki profile folder name and optional custom root. |
| `collection` | Explicit collection path; overrides a stored profile. |
| `anki_packages`, `anki_exe` | Custom Anki installation paths; empty uses current-user defaults. |
| `output_dir` | `dist` is recommended. A directory inside a Git checkout must be ignored by Git. |
| `no_online` | Defaults to `true`. Setting `false` permits vocabulary terms to be sent to Crossref/Europe PMC for fallback examples. |
| `review_annotation_keys` | Optional local annotation identifiers requiring manual review. |

CLI options override the JSON, which overrides defaults. Relative JSON paths start at the configuration file; relative CLI paths start at the shell's working directory. An explicit CLI profile/root replaces a stored collection unless a CLI collection is also supplied. Keep real paths, Note titles, databases, reports and APKGs out of Git.

## Run

Save edits and **normally exit Zotero and Anki yourself**. The tool never force-closes them.

```powershell
.\Syne_Zot2Anki.cmd -Check
.\Syne_Zot2Anki.cmd -DryRun
.\Syne_Zot2Anki.cmd
```

`-Check` tests only the environment. `-DryRun` produces a private match/change report without committing to Anki. Normal operation prepares a consistent backup, plans the complete match, updates a candidate database, validates its packages, then replaces the original database. The collection-level lock prevents duplicate runs. Unmerged WAL, a newly started application, a changed original, identity conflicts and damaged vocabulary sources prevent commit.

A successful report identifies the updated collection. The Windows launcher opens Anki with the exact profile only when it can derive that profile from the configured root. Custom collection paths receive a result location instead. Add `-NoOpenAnki` to suppress reopening.

| PowerShell | Python | Purpose |
| --- | --- | --- |
| `-Check` | `--check` | Environment only. |
| `-DryRun` | `--dry-run` | Match plan without database commit. |
| `-AllowLargeRemoval` | `--allow-large-removal` | Allow the removal-count threshold only. |
| `-RefreshExamples` | `--refresh-examples` | Bypass online cache when online lookup is enabled. |
| `-NoOnline` | `--no-online` | Force offline operation. |
| `-Recover <report>` | `--recover <report>` | Finish outputs of an already committed run. |

Direct commands use `.venv/Scripts/python.exe scripts/sync_vocabulary.py`; the direct Python command does not launch Anki. Export-only TSV remains available through `scripts/export_vocabulary_note.py`. Full sync requires PDF support even offline. An optional desktop shortcut can be created with `scripts/install_desktop_shortcut.ps1`.

## Identity and outputs

Each collection binds to one Zotero Note in this RC. Library/group, attachment and annotation form the source identity. Word fallback applies only to already managed notes. Splits, merges and ambiguous identities stop the entire run. Migration adopts only previously tagged notes with complete, uniquely matching source links; unowned notes are listed and left alone. Shared-template changes affecting unowned notes are refused.

The personal deck, note type, sync tag and seven fields retain their historical `Zotero2Anki` identifiers. Changing those names would disconnect existing cards. Missing managed notes are tagged rather than deleted. Missing counts at or above `max(5, ceil(managed_count × 20%))` stop by default.

Every run uses a time plus random ID and never overwrites existing artifacts:

- Vocabulary TSV and review TSV.
- **personal.apkg**: only this source's managed note IDs, including missing entries, personal Notes, tags, review history and required media. Treat it as private.
- **clean.apkg**: current valid vocabulary built in a fresh database, with a distinct sharing note type and stable sharing GUID. No Notes, private tags, review logs, scheduling, Zotero links/identifiers or private media. Only text and built-in TTS are supported. Unverified local titles/examples are omitted; public provider examples retain verified public metadata. This boundary does not assess publication rights or whether your learning text itself is appropriate to share.
- A consistent collection backup and a private JSON run journal with stages, binding, matches, exclusions, hashes, privacy checks and recovery information.

Only share the clean package after reviewing its learning text. Never share the personal package, backup, TSV, cache or local report. See [operations and recovery](IMPLEMENTATION_GUIDE.md), [known limitations](KNOWN_ISSUES.md), [changes](CHANGELOG.md), and [third-party notices](THIRD_PARTY_NOTICES.md).

## Validation and release status

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -t . -v
node --test tests/core.test.js
.\.venv\Scripts\python.exe tests/integration_anki.py
```

Windows CI uses only synthetic Zotero/PDF/Anki fixtures, checks raw APKG data, and installs the allowlisted ZIP in a fresh Chinese/space path. Actual materials are validated only on consistent copies. The older Zotero plugin's source and pure-function tests remain; no XPI or real-device compatibility promise is included.

GitHub Support confirmed removal of unreferenced commits on 2026-09-07. On 2026-09-08, both known affected commit pages returned 404 in an authenticated browser; this verifies those two pages, not every possible historical cache. The repository is public and rc.2 was published as a pre-release on 2026-09-08. RC.3 adds journal display improvements and requires assets and acceptance for its exact commit. The rc.1 draft and rc.2 release, tags and assets remain unchanged. RC.3 acceptance uses synthetic data only; historical real-data checks are not new RC.3 acceptance results.

## License

Zot2Anki's original code and documentation are licensed under the [MIT License](LICENSE), copyright 2026 gblll. Third-party code and dependencies retain their own licenses; see [third-party notices](THIRD_PARTY_NOTICES.md).

The current implementation directly imports the Anki Python backend and PyMuPDF. MIT does not replace their AGPL or other applicable terms. Distribution of a combined program must comply with the applicable AGPL conditions, including corresponding-source and notice requirements. Separately installing dependencies does not by itself remove those obligations. This repository does not grant rights to users' documents or learning materials.
