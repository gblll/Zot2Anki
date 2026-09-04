# Zot2Anki

[English](README.md) | [简体中文](README.zh-CN.md)

**v0.2.0-rc.1：私有 Windows 预发布候选版。** 将一篇 Zotero 生词 Note 同步到 Anki，并保留卡片身份、个人 Notes 和复习历史。当前不是稳定版或公开发行版。

## 安装

验证基线为 **Windows x64、Python 3.13、Anki 26.5、PyMuPDF 1.28.2**。请先安装 Python 和 Anki；发行包不包含这些运行时。环境不匹配时，会在打开个人数据库前退出。

将 ZIP 解压到可写的本地目录，支持中文和空格路径。在解压目录执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1
Copy-Item config.example.json config.local.json
```

仅首次安装时复制示例，升级时保留原有配置。设置脚本创建项目 `.venv`，核对 SHA256 后安装固定版本 PDF 依赖，并通过临时 collection 检查 Anki 后端。非标准安装可传 `-Python <Python可执行文件>` 和 `-AnkiPackages <app_packages目录>`。安装依赖需要联网，日常同步默认离线。

## 本地配置

编辑被 Git 忽略的 `config.local.json`。`note_title` 必须是唯一、完全匹配的 Zotero Note 标题；设置 `anki_profile` 或明确的 `collection`，不会自动选择用户配置。

| 配置项 | 含义 |
| --- | --- |
| `database` | Zotero SQLite 文件，默认当前用户的 Zotero 目录。 |
| `note_title` | 生词 Note 的准确标题。 |
| `anki_profile`、`anki_root` | Anki 配置目录名称和可选自定义根目录。 |
| `collection` | 明确指定 collection；优先于 JSON 中的配置名称。 |
| `anki_packages`、`anki_exe` | 自定义 Anki 安装位置；留空使用当前用户默认位置。 |
| `output_dir` | 建议保留 `dist`；仓库内未被 Git 忽略的输出目录会被拒绝。 |
| `no_online` | 默认 `true`。改为 `false` 后，缺少本地完整例句时可将生词搜索词发送给 Crossref / Europe PMC。 |
| `review_annotation_keys` | 需要人工复核的本地 annotation 标识。 |

优先级为命令行、JSON、默认值。JSON 相对路径从配置文件所在目录解析，命令行相对路径从当前工作目录解析。命令行指定配置名称或根目录时，会替代 JSON 中的 collection，除非同时明确传入命令行 collection。真实路径、笔记名称、数据库、报告和 APKG 不应上传 Git。

## 日常使用

保存编辑，**自行正常退出 Zotero 和 Anki**。脚本不会强制关闭应用。

```powershell
.\Syne_Zot2Anki.cmd -Check
.\Syne_Zot2Anki.cmd -DryRun
.\Syne_Zot2Anki.cmd
```

`-Check` 仅检查环境。`-DryRun` 生成匹配计划和本地报告，不提交到 Anki。正常同步先制作一致性备份，完成全部匹配计划，再在候选数据库中更新和验证；最后检查原库与应用状态并原子替换。重复运行锁、未合并 WAL、应用重新启动、原库变化、身份冲突和来源格式损坏都会阻止提交。

成功报告明确显示更新的 collection。只有能根据配置根目录准确确定配置名称时，启动器才用该名称打开 Anki；自定义 collection 路径只显示结果位置。使用 `-NoOpenAnki` 可禁止自动打开。

| PowerShell | Python | 作用 |
| --- | --- | --- |
| `-Check` | `--check` | 只检查环境。 |
| `-DryRun` | `--dry-run` | 只生成匹配计划，不提交数据库。 |
| `-AllowLargeRemoval` | `--allow-large-removal` | 仅解除大量缺失的数量保护。 |
| `-RefreshExamples` | `--refresh-examples` | 联网已启用时，跳过缓存重新查询。 |
| `-NoOnline` | `--no-online` | 强制本次离线。 |
| `-Recover <报告>` | `--recover <报告>` | 仅整理已经提交的运行产物。 |

直接调用使用 `.venv/Scripts/python.exe scripts/sync_vocabulary.py`，Python 入口本身不会打开 Anki。单独导出 TSV 的入口仍为 `scripts/export_vocabulary_note.py`。完整同步在离线状态也需要 PDF 依赖。可通过 `scripts/install_desktop_shortcut.ps1` 创建桌面快捷方式。

## 匹配与产物

RC 每个 collection 只绑定一篇 Zotero Note。来源身份包含资料库或群组、附件及 annotation；单词回退只用于已托管笔记。拆分、合并和其他归属冲突会停止整次同步。首次迁移只接管带原同步标签、完整来源链接能唯一对应当前输入的旧笔记。归属不明项目列入报告，私人同类型笔记不更新、不标记缺失；会影响它们的共享模板迁移也会被拒绝。

个人牌组、笔记类型、同步标签及七个字段继续使用原有 `Zotero2Anki` 身份。缺失条目只加标签，不从个人库删除。当缺失数达到 `max(5, ceil(原托管数量 × 20%))` 时默认停止。

每次运行使用时间加随机标识，禁止覆盖现有产物：

- 生词 TSV 与待复核 TSV。
- **personal.apkg**：仅包含本次来源的托管笔记 ID，包括缺失词条、个人 Notes、标签、复习历史和必要媒体，必须按私人文件保存。
- **clean.apkg**：从空数据库构建，只保留当前有效词条，使用独立分享笔记类型和稳定分享 GUID。清除 Notes、私人标签、调度、复习日志、Zotero 链接与标识；只支持文本和内置 TTS，不包含私人媒体。未经公开元数据核验的本地题名和例句会被省略；经过公开服务核验的例句保留出处。这项检查不判断学习文本是否适合公开或是否拥有相应分享权利。
- 一致性备份与私人 JSON 运行日志，记录阶段、提交状态、来源绑定、匹配、排除项目、指纹、隐私校验和恢复信息。

分享前请检查 clean 中的学习内容。不要分享 personal、备份、TSV、缓存或本地报告。详见[操作与恢复](IMPLEMENTATION_GUIDE.md)、[已知限制](KNOWN_ISSUES.md)、[变更记录](CHANGELOG.md)和[第三方声明](THIRD_PARTY_NOTICES.md)。

## 验证与发行状态

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -t . -v
node --test tests/core.test.js
.\.venv\Scripts\python.exe tests/integration_anki.py
```

Windows CI 仅使用合成 Zotero、PDF 和 Anki 资料，直接检查 APKG 内数据库，并在含中文和空格的全新目录安装允许名单发行包。真实资料仅在一致性副本上验收。旧 Zotero 插件保留源码与纯函数测试；不附 XPI，不承诺插件实机兼容。

GitHub 上含个人信息的旧孤立对象仍是**公开发行门禁**，服务器端清理完成前仓库保持私有。现有 v0.2.0-rc.1 草稿及附件早于下述许可调整；最终发行需要重新构建附件，并验证其准确提交。

## 许可证

Zot2Anki 原创代码和文档采用 [MIT 许可证](LICENSE)，版权所有者为 gblll，年份为 2026。第三方代码和依赖保留各自许可证，详见[第三方声明](THIRD_PARTY_NOTICES.md)。

当前实现直接导入 Anki Python 后端和 PyMuPDF。MIT 不替代它们适用的 AGPL 或其他条款；分发组合程序时，仍须满足相应的 AGPL 条件，包括对应源码和许可声明要求。将依赖改为单独安装，本身不能免除这些义务。项目许可证不授予用户文献或学习材料的分享权利。
