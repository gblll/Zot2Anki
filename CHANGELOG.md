# Changelog

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

### Unresolved release gates

The repository remains private. Known old GitHub objects and the choice of a project license still block public distribution. Support contact is only drafted locally. No main merge, public release or repository visibility change is part of this candidate.

### 中文说明

本次补齐来源归属、冲突预检、一致性备份、副本提交、提交后恢复、分享允许名单、例句与缓存、固定运行环境、Windows CI 和双语文档。旧插件保留源码与测试，不附 XPI。旧 GitHub 对象和项目许可证仍是公开发行门禁，本次仅准备私有预发布草稿。
