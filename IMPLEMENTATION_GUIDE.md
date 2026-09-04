# Operations and recovery / 操作与恢复

The RC entry point is `Syne_Zot2Anki.cmd`, backed by the project's `.venv`. See the bilingual README for installation and configuration.

## Source format / 来源格式

Use one vocabulary entry per paragraph, one complete Zotero annotation link, then a definition. Synthetic example:

```html
<p><a href="zotero://open-pdf/library/items/TESTITEM?page=1&amp;annotation=TESTKEY">sample</a>: <code>🔉 英 [ˈsɑːmpəl] n. 示例</code></p>
```

Group sources use `zotero://open-pdf/groups/<group-id>/items/<attachment-key>?annotation=<annotation-key>`. The identifiers above are placeholders. Library/group, attachment and annotation must resolve together in Zotero and must not be deleted. Definitions without recognized pronunciation are retained with a review flag; broken source identities cannot enter synchronization. Empty paragraphs are ignored; an initial plain paragraph matching the Note title is allowed. Other non-vocabulary text paragraphs are rejected in strict sync, because a lost source link cannot safely be distinguished from an intentional comment.

生词使用一个段落、一条完整来源链接，后接释义。空段落以及首段与 Note 标题一致的普通文字可保留；其他无法识别来源的文字段落会停止同步。解析为空、链接损坏或来源已删除，不能通过 `--allow-large-removal` 绕过。音标格式异常会保留释义并标记待复核。

## Ownership and migration / 归属与迁移

The collection config key `zot2anki_source_binding_v1` stores the Note binding and managed note IDs with compound source identities. Do not edit this config manually. The RC binds a collection to one Note; a different source requires a separate collection/profile. Renaming the same Note is safe if its item identity is unchanged and the local title setting is updated.

On first adoption, only notes carrying `Zotero2Anki` with complete source sets uniquely matching an input entry are owned. Same-type private cards remain unowned. Ambiguous legacy matches stop the run; unmatched historical items are listed in `excluded`. If a template change would affect an unowned card, move that private card to a separate note type in Anki before retrying.

来源绑定保存在 collection 内，不依赖文件名或项目名称。首次迁移不依靠单词猜测历史归属。历史项目无法确认归属时列入报告；交叉或重复归属会停止同步。未托管笔记不更新、不标记缺失。请勿通过手改内部绑定或移除冲突检查来解决问题。

Fields remain `Word`, `Symbol`, `Chn`, `Example`, `Source`, `ZoteroKeys`, `Notes`. Only the first six and managed tags are refreshed. Existing GUIDs, note/card IDs, personal Notes, non-managed tags and scheduling remain in place. Missing entries retain history and return to active status when the same source reappears. Splits/merges require resolving the source structure before retrying; the RC has no automatic identity reassignment.

## Commit protocol / 提交协议

1. Check the pinned runtime before personal DB access; reject unsafe output locations.
2. Acquire an OS collection lock and fingerprint the original.
3. Use SQLite's backup interface, including committed WAL pages, and validate the backup.
4. Parse valid sources, plan every match/conflict/removal, and check shared-template impact.
5. Open a candidate beside the original on the same filesystem. Only the candidate receives model migrations, notes and ownership changes.
6. Export explicit personal note IDs and build clean from a separate empty collection. Validate all physical package DBs and media maps; compare personal IDs, fields and raw review data.
7. Close and validate the candidate. Require apps closed, no original WAL data and an unchanged original fingerprint, then atomically replace.
8. Publish already prepared files without overwriting. A durable journal records commit intent, candidate hash, commit result and remaining files.

The OS lock serializes this tool's runs. It does not control other database tools; do not open either application or edit database files during synchronization. Use a local writable filesystem supporting atomic replacement and hard links (the Windows acceptance baseline is NTFS). Network shares, cloud-synced profiles and FAT/exFAT output directories are not validated. Personal media stay in place; only referenced files are copied into the disposable export area.

运行时不要启动应用或用其他工具改库。锁只约束本工具；提交前会再次检查应用、WAL 和原库指纹。候选库位于原库同一文件系统，个人媒体原位保留。发行基线为本地 NTFS，不支持以网络共享或云同步目录作为验收依据。

## Failure and recovery / 失败与恢复

Reports and backups are private. Keep the report, backup and `.run-<id>` staging folder together. The journal has `stage`, `committed`, `before`, `candidate_fingerprint`, `after`, `plan`, `conflicts`, `excluded`, `privacy`, `artifacts` and `outputs` where available.

- `failed_before_commit`, `committed: false`: the original was not replaced. Fix the reported cause before starting a new run. An incomplete candidate is not a recovery database.
- `committing`: a crash may have happened around replacement. Do not assume success or failure. Recovery compares the current DB with the candidate fingerprint.
- `committed` / `finalizing`: the DB is already updated. **Do not repeat sync just to obtain missing exports.** Close applications and run the recovery command below.
- `complete`: database and outputs are complete. The report remains as the audit trail.
- `dry_run`: a match plan only; the database was not committed.

```powershell
.\.venv\Scripts\python.exe scripts/sync_vocabulary.py --recover <private-report.json>
```

Recovery verifies the committed DB fingerprint and every staged/final artifact hash. Already published matching files are accepted; conflicting files or a subsequently modified DB stop recovery. It never applies the note update plan again. If a journal could not be written after replacement, keep the original `committing` report: its candidate fingerprint can still prove the result. If the DB has since changed, preserve everything and resolve the state manually instead of rerunning blindly.

提交前失败时修正原因后再同步；提交后整理失败时使用 `--recover`。该命令只核验并完成剩余产物，不重跑笔记更新。若 Anki 已产生新复习记录导致指纹改变，自动恢复会拒绝，请保留现有数据库、备份和报告进行人工处理。

To roll back deliberately: close applications, preserve the current DB and its sidecars in a separate recovery folder, verify the pre-sync backup opens in an isolated Anki profile, then restore that backup as the configured collection. Restore into a new empty profile first whenever possible. A database backup does not replace a full media backup; this tool leaves original media untouched. Never copy only the main SQLite file from a running application, and never discard WAL files that may contain later reviews.

回滚前先正常关闭应用，另存当前数据库及相关文件，并在隔离配置中验证同步前备份可打开。优先恢复到新建的空配置。不要从运行中的应用只复制主库，也不要随意删除可能含新复习记录的 WAL 文件。数据库备份不等于完整媒体备份。

## Upgrade / 升级

Extract a new release beside the old installation. Keep the old copy until acceptance passes. Copy only your private configuration deliberately; relative paths now refer to the new configuration folder. Run setup again, then `-Check` and `-DryRun`. Recreate the desktop shortcut if the install path changed. Keep backups and run journals; do not upload them. This RC does not migrate a binding to another Zotero Note.

升级时解压到新目录，保留旧版和备份，重新执行设置、环境检查和 dry-run。移动配置后重新核对相对路径；项目移动后重建快捷方式。旧插件源码可保留，但不作为本次推荐安装入口。

## Examples and sharing / 例句与分享

Local PDF extraction supports text PDFs and cross-line hyphens. Scanned pages are reported for OCR; OCR is not bundled. Source lookup is constrained by library/group and attachment and excludes deleted sources before any text can reach an online provider. Offline is the default and `--refresh-examples` does not enable networking. Successful examples expire after 30 days, successful no-result queries after 1 day; failures are not durable empty results. Cache writes are atomic.

Clean packages retain vocabulary and definitions as escaped learning text, with no private media. Local titles and local PDF sentences are omitted unless public provenance can be established; this RC conservatively omits all local-source metadata and uses only verified provider metadata for shareable examples. Offline runs do not make verification requests. A fixed, public Anki default deck configuration is retained because the importer requires config 1; no personal deck preferences or learned parameters are copied. Public metadata verification does not grant copyright permission for publication.

clean 仅包含当前有效学习内容，使用独立分享身份，重复导入不会新增重复项，导回个人库不会覆盖个人卡。仅保留固定的 Anki 必需默认牌组配置。私人标签、Notes、来源标识、媒体和复习数据不进入 clean。私人内容若本来就写在单词或释义中，仍须自行检查后分享；自动结构校验不能理解所有自然语言隐私。

## Maintainer validation / 维护者验证

See `tests/MANUAL-INTEGRATION.md`. The 11 original audit families are mapped to regression tests there. Build only from a verified commit:

```powershell
.\.venv\Scripts\python.exe scripts/build_release.py --output dist/release-candidate
```

The builder reads `release-files.txt` and file bytes from Git objects at the chosen commit. It excludes local config, audit material, recovery bundles, DBs, private APKGs, runtimes and `.git`; it verifies paths, file hashes and obvious credential patterns. It does not publish a release. GitHub Draft Pre-release creation is a separate, private, authorized step after acceptance.
