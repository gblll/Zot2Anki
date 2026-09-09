# Acceptance / 验收

All automated tests use temporary synthetic data. Use the project `.venv`, Python 3.13 and Anki 26.5. CI can set `ZOT2ANKI_TEST_ANKI_PACKAGES` for its disposable backend; this variable changes only tests, never production application detection.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -t . -v
node --test tests/core.test.js
.\.venv\Scripts\python.exe tests/integration_anki.py
```

## Original audit regressions

| Audit family | Regression |
| --- | --- |
| Split double write | `test_sync_identity`: split/merge/input conflicts and unchanged notes. |
| Partial write after late failure | `test_sync_transaction`: migration, write, export and commit faults; original hash unchanged. |
| Unmanaged same-type cards | `test_sync_identity`: no word adoption/missing marker; shared-model migration refusal. |
| Empty/damaged source | `test_sync_identity`, `test_example_safety`: empty input and deleted source link stop. |
| Private APKG leakage / misleading validator | `test_sync_packages`: explicit personal IDs; unused model/deck metadata, extra notes/tables, tags/media and raw scheduling rejected. |
| Literal HTML / repeated escaping | Python direct/TSV and `core.test.js` legacy Front regressions. |
| WAL missing from backup | `test_sync_safety`: committed WAL present in SQLite backup, original WAL blocks commit. |
| Cross-library annotation collision | `test_example_safety`: same annotation key in different libraries and attachment/deletion filtering. |
| Invalid source outbound lookup | `test_example_safety`, `test_export_vocabulary_note`: provider never sees invalid source text. |
| Failed query cached forever | `test_example_safety`: retry after failure, separate TTLs, explicit refresh. |
| Prefix/substring word match | `test_example_safety`, `test_vocabulary_examples`: word boundaries and PDF cross-line hyphens. |

Additional tests cover source changes, adoption, restored missing notes, repeated sync, preserved card identity/Notes/review state, clean re-import isolation, synthetic PDF extraction, default offline operation, run locks, output collisions, recovery, environment gating and applications starting before commit.

## Clean install

Build only allowlisted Git objects at a verified commit:

```powershell
.\.venv\Scripts\python.exe scripts/build_release.py --output dist/acceptance-release
.\.venv\Scripts\python.exe tests/clean_install.py dist/acceptance-release/Zot2Anki-v0.2.0-rc.3-windows.zip --report dist/install-acceptance.json
```

The second command creates a new Chinese/space directory and `.venv`, runs setup, environment checks, dry-run and two full syncs through the extracted PowerShell launcher, and checks CMD argument forwarding. It does not select a real profile or launch Anki. To reuse a hash-verified wheel directory offline, pass `--wheelhouse <directory>`.

## Actual data acceptance

Never run experiments against the daily database. Normally close applications yourself and create SQLite-backup snapshots. Capture original fingerprints before/after snapshotting. Copy only referenced PDFs/media into a private, ignored acceptance folder. Use a separate collection and config for every trial. Compare GUID, note/card IDs, personal Notes, queue/repetition/interval/due values and review logs across repeated syncs, and inspect physical package databases.

Invalid source records must be rejected with no commit. If the actual Note contains stale annotations, preserve that failing copy and a local detail report; a separate copy may remove those invalid input paragraphs for the positive-path trial. Explicitly record the filtered count, unowned history count and remaining daily-use data repair requirement. Never silently edit the real Note to pass acceptance.

真实资料只能使用一致性副本。需要保留原库指纹、无效来源明细以及过滤后的正向验收范围。来源失效时应验证拒绝提交；不能修改正式资料或关闭保护来制造成功结果。

## Release gate

The exact release commit must pass unit/legacy tests, raw package privacy tests, clean-install verification and the Windows CI workflow. Build the ZIP from that commit's `release-files.txt`; inspect every payload entry and hash. Save a sanitized summary alongside the SHA256 list. Keep the repository public and create only a Draft Pre-release. Record the 2026-09-07 Support cleanup confirmation and the 2026-09-08 authenticated 404 checks for the two known old commit pages, without claiming a comprehensive cache audit. For rc.3, preserve rc.1 and rc.2 releases, tags and assets, fast-forward main only to the verified final commit, and bind the new tag, ZIP manifest, acceptance summary and CI to that same commit. Repository visibility changes, deletion, history rewrite, support messages and publishing the draft are outside this workflow. Historical real-data acceptance belongs to rc.1 commit 1230dac and is not a new rc.3 acceptance result; rc.3 acceptance uses synthetic data only.
