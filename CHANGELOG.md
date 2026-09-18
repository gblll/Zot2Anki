# Changelog

## 0.2.0-rc.4

Windows public pre-release published on 2026-09-15. This is not a stable release; the rc.1, rc.2 and rc.3 releases, tags and assets remain unchanged.

### What's changed

#### Added

- **Anki 26.09 backend support:** Runs against Anki 26.05 and Anki 26.09. Python and Anki runtimes are still installed separately; they are not bundled in the ZIP.
- **Sync progress:** The Windows launcher shows configuration loading, file checks and sync-engine startup, then displays an animated elapsed-time indicator while synchronization is running.

#### Improved

- **Long-running sync feedback:** The launcher drains Python's standard output and error streams concurrently, so progress remains visible and the process is not blocked by a full output pipe.

#### Fixed

- **Package export compatibility:** The release no longer imports Anki's deprecated `AnkiPackageExporter` wrapper. Personal and clean packages continue to use `Collection.export_anki_package`.

### Download

- Windows source package: `Zot2Anki-v0.2.0-rc.4-windows.zip`

### First launch and validation

- Baseline: Windows x64, Python 3.13, Anki 26.05 or 26.09, PyMuPDF 1.28.2 and a local NTFS directory.
- Anki 26.05 and 26.09 each passed 120 Python tests and the Windows clean-install workflow; 8 JavaScript tests and a separately invoked 28-test synthetic Anki integration suite also passed. Unicode/space paths, offline dry-run, repeated sync, raw APKG privacy checks, the release allowlist and reproducible ZIP builds also passed.
- This acceptance used synthetic data only. No mobile or legacy-plugin real-device acceptance is claimed, and no XPI or private data is included.

### 更新内容

#### 新增

- **Anki 26.09 后端支持：** 现在支持 Anki 26.05 和 Anki 26.09。Python 与 Anki 运行时仍需单独安装，发行 ZIP 不包含这些运行时。
- **同步进度：** Windows 启动器显示配置加载、文件检查和同步引擎启动阶段；同步运行期间显示动画和已用时间。

#### 改进

- **长时间同步反馈：** 启动器并发读取 Python 的标准输出和错误输出，持续显示进度，也不会因输出管道积满而阻塞。

#### 修复

- **制包兼容性：** 不再导入 Anki 已弃用的 `AnkiPackageExporter` 包装器；个人包和 clean 分享包继续使用 `Collection.export_anki_package`。

### 下载

- Windows 源码发行包：`Zot2Anki-v0.2.0-rc.4-windows.zip`

### 首次启动与验收

- 运行基线：Windows x64、Python 3.13、Anki 26.05 或 26.09、PyMuPDF 1.28.2，以及本地 NTFS 目录。
- Anki 26.05 和 26.09 各通过 120 项 Python 测试及 Windows 全新安装流程；另有 8 项 JavaScript 测试和单独运行的 28 项合成 Anki 集成测试通过。中文和空格路径、离线预演、重复同步、原始 APKG 隐私检查、发行文件允许名单和 ZIP 可重复构建也已通过。
- 本轮仅使用合成数据验收，不声明移动端或旧插件实机通过；不包含 XPI 或私人资料。

## 0.2.0-rc.3

Windows public pre-release published on 2026-09-13. This is not a stable release; the rc.1 and rc.2 releases, tags and assets remain unchanged.

### What's changed

#### Added

- **Opt-in invalid-source skipping:** `--skip-invalid-sources` / `-SkipInvalidSources` skips only entries whose Zotero annotation has been deleted. Each skipped word, link and reason is written to `skipped_sources` in the run journal and to the review TSV. Healthy entries continue to sync.
- **Journal citation display:** Source citations use Zotero's journal abbreviation when available, fall back to the full title otherwise, use italic text without parentheses, add conservative abbreviation punctuation and wrap long titles with theme-aware colors.

#### Improved

- **Safe handling of skipped entries:** A skipped entry remains in the Zotero Note, so its existing Anki card is left untouched: content, identity, tags, personal Notes and review history are preserved, and it is not marked missing. If no valid entries remain, synchronization stops without committing.
- **Legacy note adoption:** Existing managed cards can be adopted on the first successful run when their source identity matches uniquely; the shared-template check no longer blocks every later run because of the old field lookup bug.

#### Fixed

- **Online lookup safety:** Text without a resolved Zotero annotation context is never sent to an online example provider.
- **Shared-template migration:** Tagged legacy entries whose source disappeared are reported and left untouched. The migration is refused only when an unrelated, unowned card would be affected.

### Download

- Windows source package: `Zot2Anki-v0.2.0-rc.3-windows.zip`

### First launch and validation

- Baseline: Windows x64, Python 3.13, Anki 26.5, PyMuPDF 1.28.2 and a local NTFS directory. Runtimes are installed separately; no XPI is included.
- 119 Python tests, 8 JavaScript tests and a separately invoked 28-test synthetic Anki integration suite passed, together with clean installation in a Unicode/space path, offline dry-run, repeated sync, release allowlist validation, reproducible ZIP hashes and exact-commit Windows CI.
- Invalid-source preservation was checked with disposable synthetic databases covering repeated sync, legacy cards, partial invalid sources and the all-invalid stop path. This release does not claim mobile or legacy-plugin real-device acceptance.

### 更新内容

#### 新增

- **可选跳过失效来源：** `--skip-invalid-sources` / `-SkipInvalidSources` 只跳过 Zotero 批注已删除的条目。运行日志的 `skipped_sources` 和复核 TSV 会记录每个单词、链接及原因，其余有效条目继续同步。
- **期刊出处显示：** 优先使用 Zotero 期刊缩写，缺失时回退期刊全名；期刊使用无括号斜体，按可识别缩写保守补句点，并支持主题颜色和长标题换行。

#### 改进

- **跳过条目的安全处理：** 被跳过的条目仍在 Zotero Note 中，因此对应 Anki 卡片保持原样：内容、身份、标签、个人 Notes 和复习历史均保留，也不会标记为缺失。若没有任何有效条目，同步会停止且不提交。
- **旧笔记接管：** 只有来源身份唯一匹配的既有托管卡片，才能在首次成功运行时接管；修复旧字段读取问题后，共享模板检查不再无条件阻塞后续运行。

#### 修复

- **在线查询安全：** 未解析到有效 Zotero 批注上下文的文本不会发送给在线例句提供方。
- **共享模板迁移：** 来源已消失的带标签历史条目会进入报告并保持不变；只有可能影响无关未托管卡片时才拒绝迁移。

### 下载

- Windows 源码发行包：`Zot2Anki-v0.2.0-rc.3-windows.zip`

### 首次启动与验收

- 运行基线：Windows x64、Python 3.13、Anki 26.5、PyMuPDF 1.28.2，以及本地 NTFS 目录。运行时需单独安装，不包含 XPI。
- 119 项 Python 测试、8 项 JavaScript 测试和单独运行的 28 项合成 Anki 集成测试通过；中文和空格路径下的全新安装、离线预演、重复同步、发行文件允许名单、ZIP 可重复构建和准确提交的 Windows CI 也已通过。
- 失效来源保护已用临时合成数据库验证，覆盖重复同步、旧卡、部分来源失效和全部来源失效时停止的情况。本版不声明移动端或旧插件实机验收通过。

## 0.2.0-rc.2

Private Windows pre-release candidate; the rc.1 tag and draft are preserved.

- Read RC versions from the target commit and derive CI package paths from VERSION.
- Confirm known-object cleanup: GitHub Support reported removal on 2026-09-07; authenticated browser checks on 2026-09-08 returned 404 for both known affected commit pages. This does not claim a comprehensive cache audit.

- Ignore Anki's tag ordering when detecting content changes, preventing repeated updates of unchanged notes while preserving personal tags.
- Integrate the RC hardening and MIT licensing changes into main so the default launcher supports Check, DryRun and recovery. Existing draft tags and assets remain unchanged.
- License original Zot2Anki code and documentation under MIT, copyright 2026 gblll.
- Preserve third-party license terms, include Anki's license notice and the AGPL v3 text, and explain the obligations of distributing a combined program using the Anki/PyMuPDF dependencies.
- Include license files in the source ZIP allowlist. Existing v0.2.0-rc.1 assets and tag are unchanged; the final release must be rebuilt and validated from its exact commit.
- 原创代码和文档采用 MIT；保留第三方许可与相应 AGPL 义务，并将许可文件纳入发行包。已确认清理并核验两个已知旧提交页面为 404；rc.2 保持私有草稿，公开发行尚未完成。

## 0.2.0-rc.1

Private Windows pre-release candidate; not a stable or public release.

- Add collection-bound source ownership, complete conflict planning, conservative legacy migration and large-removal protection.
- Stage all database changes on a consistent copy; validate WAL-aware backups, use an OS run lock, recheck original fingerprints and commit atomically.
- Record commit state and recover remaining output files without applying sync twice.
- Export personal packages by explicit note IDs with raw identity/review checks. Build clean packages from empty collections with independent stable sharing identities, strict metadata allowlists and no private media.
- Filter source queries by library/group and attachment, reject deleted/broken sources before online lookup, fix word boundaries and HTML escaping, and add expiring atomic example caches.
- Fix launchers to use the project .venv and add setup, check, dry-run, refresh, removal override and recovery interfaces.
- Add Windows synthetic CI, original audit regressions, raw APKG attack fixtures, PDF extraction, recovery faults and clean-install/package checks.
- Add bilingual installation/recovery/sharing guidance and third-party notices. Keep legacy plugin source/tests without an XPI asset.

### Release gates when this candidate was prepared

When v0.2.0-rc.1 was prepared, the repository remained private, known old GitHub objects and the unselected project license blocked public distribution, and the support request was a local draft. This candidate did not merge main, publish a release or change repository visibility. See 0.2.0-rc.2 above for subsequent licensing changes.

### 中文说明

本次补齐来源归属、冲突预检、一致性备份、副本提交、提交后恢复、分享允许名单、例句与缓存、固定运行环境、Windows CI 和双语文档。旧插件保留源码与测试，不附 XPI。制作此候选版时，旧 GitHub 对象和未选择的项目许可证阻止公开发行，仅准备私有预发布草稿；后续许可调整见上方发行条目。
