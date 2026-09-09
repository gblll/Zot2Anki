# Changelog

## 0.2.0-rc.3

Windows pre-release candidate prepared as a draft in the public repository. Existing rc.1 and rc.2 tags and assets are preserved.

- 期刊格式改为无括号斜体，按缩写词补齐句点（`Nat. Commun.`），保留完整单词和首字母缩写。

- 原文例句与来源链接增加 Zotero 期刊缩写，缺失时回退期刊全名；支持主题颜色及长标题换行。
- 保持在线出处和 clean 分享允许名单，补充期刊显示、旧卡升级、复习记录保留与重复同步回归验证。
- 本轮按准确提交完成合成数据、Windows CI 和全新安装验收；结果随发行附件提供，不沿用历史真实资料验收结论。
- 仓库已公开，rc.2 于 2026-09-08 公开预发布；修正文档中的旧准备状态，rc.3 发行条目保持草稿。

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

本次补齐来源归属、冲突预检、一致性备份、副本提交、提交后恢复、分享允许名单、例句与缓存、固定运行环境、Windows CI 和双语文档。旧插件保留源码与测试，不附 XPI。制作此候选版时，旧 GitHub 对象和未选择的项目许可证阻止公开发行，仅准备私有预发布草稿；后续许可调整见上方 Unreleased。
