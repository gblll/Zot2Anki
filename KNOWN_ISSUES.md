# Known limitations / 已知限制

Status: v0.2.0-rc.3, draft pre-release candidate in a public repository. Regression results do not constitute a stable-version guarantee.

## Remaining gates / 剩余门禁

- GitHub Support confirmed removal of unreferenced commits on 2026-09-07. Authenticated browser checks on 2026-09-08 showed 404 for both known affected commit pages. This closes the known-object cleanup gate within that scope; it is not a comprehensive cache audit. The repository is public; rc.2 was published as a pre-release on 2026-09-08. RC.3 is prepared as a Draft Pre-release with exact-commit asset acceptance.
- Original project code is now licensed under [MIT](LICENSE). The preserved v0.2.0-rc.1 draft assets predate this change; rc.2 includes the license files. Third-party licenses and applicable AGPL obligations remain in effect; see [third-party notices](THIRD_PARTY_NOTICES.md). Python, Anki and PyMuPDF runtimes are not bundled.
- Validated runtime: Windows x64, Python 3.13, Anki 26.5, PyMuPDF 1.28.2; local NTFS. Other platforms, runtime combinations, network/cloud-synced profiles and FAT/exFAT output folders are outside RC acceptance.
- One Zotero Note per collection. Source switching, splits, merges, ambiguous historical adoption and missing owned notes that were manually deleted require manual resolution. The RC refuses to guess.
- Keep Anki/Zotero closed throughout sync. A collection lock cannot prevent unrelated tools from writing. Disk faults or later changes to the committed DB may require manual recovery; never blindly resync to finish exports.
- clean packages support text and built-in TTS only. Local titles/examples without public verification are omitted. Privacy checks enforce structure and provenance; users must still review the learning text itself and its sharing rights.
- Voice availability, Anki mobile rendering and the old Zotero plugin lifecycle are not verified by this RC. Plugin source and tests are retained, but no XPI is released. TTS depends on available voices.
- Scanned PDFs need external OCR. Unusual pronunciation and incomplete context remain visible as review items.
- `--dry-run` can create private reports, snapshots, TSVs and cache entries, but never commits Anki. Existing missing entries continue to count toward the large-removal threshold.

原创代码已选择 MIT，第三方条款仍须遵守。GitHub 已确认清理未引用提交，两个已知旧提交页面经登录核验均显示 404；该结论限于已核验范围。仓库已公开，rc.2 已公开预发布；rc.3 按准确提交验收并准备为发行草稿。本轮只验收合成数据，不代表日常真实资料或移动端已通过验收。RC 的平台、来源绑定、冲突处理、恢复、分享与 PDF 边界如上；不包含插件实机或移动端兼容承诺。

## Fixed with regressions / 已有回归验证的修复

| Original issue | Safe behavior and regression |
| --- | --- |
| Split overwrote one note twice / 拆分覆盖 | Complete matching rejects multiple inputs occupying one owned note; `test_sync_identity`. |
| Partial changes after failure / 失败后部分写入 | Changes stay in candidate until commit; pre/post-commit fault tests in `test_sync_transaction`. |
| Same-type private cards were adopted/missing / 私人卡误接管 | Ownership ledger and exact legacy adoption; `test_sync_identity`. |
| Empty/damaged source marked everything missing / 来源损坏 | Empty/invalid/lost links stop before updates; `test_example_safety`, `test_sync_identity`. |
| clean leaked private notes/tags / 分享包泄露 | Fresh collection, explicit allowlists, adversarial raw DB and media checks; `test_sync_packages`. |
| Inconsistent HTML Word/Front / 转义不一致 | Single escaping with legacy entity matching; Python and JS regressions. |
| Backup omitted WAL / 备份遗漏 WAL | SQLite backup plus integrity check; `test_sync_safety`. |
| Cross-library source collision / 跨库混淆 | Compound source lookup and deletion checks; `test_example_safety`. |
| Invalid source sent online / 无效来源外发 | Filter before lookup; unresolved sources never call providers. |
| Failed request cached forever / 故障长期缓存 | Failure is not an empty success, with TTL and refresh tests. |
| Prefix matched another word / 词边界错误 | Whole-word/phrase matching with cross-line hyphens, including negative cases. |

Final release assets include a sanitized acceptance summary for the exact target commit. Consult that summary and the corresponding Windows CI run rather than assuming a draft is stable.
