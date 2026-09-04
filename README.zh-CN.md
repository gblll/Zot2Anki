# Zot2Anki

[English](README.md) | [简体中文](README.zh-CN.md)

将已整理在 Zotero Note 中的生词同步到 Anki。核心目标很简单：新增生词创建新卡，修改生词更新原卡，同时保留复习记录和个人笔记。

> 当前是开发版本，不是稳定发行版。已知问题包括合并词条拆分后的更新冲突、同步失败后可能已保存部分修改，以及分享包过滤不完整。请先阅读[已知问题](KNOWN_ISSUES.md)，在独立 Anki 配置中测试并保留备份。名为 `clean.apkg` 的文件也**不能保证可以安全分享**。

## 工具做什么

- 按精确标题读取一篇 Zotero Note，不修改 Zotero。
- 将单词、音标、释义和批注链接整理为固定格式的 Anki 卡片。
- 优先按 Zotero 批注标识匹配原笔记，再按规范化单词查找。
- 在普通一对一更新中修改受管理字段，保留个人 `Notes` 和已有复习数据。
- 对 Zotero 中消失的词条添加 `MissingFromZotero` 标签，不从主数据库自动删除。

Zotero 管理生词内容，Anki 管理复习进度和个人 `Notes`。在 Anki 中修改受同步管理的字段，下次同步时可能被覆盖。

PDF 例句提取、可选联网例句和 APKG 导出属于附加功能。旧 Zotero 插件源码保留，但目前主要使用本地脚本。

## 首次准备

启动器面向 Windows。需要 Zotero、Anki 桌面版，以及与 Anki 自带 Python 包兼容的 Python。集成流程已在 Python 3.13、Anki 26.5 下测试，其他组合需要验证；源码语法要求 Python 3.10 或更新版本。

在项目文件夹内运行：

```powershell
python -m pip install -r requirements.txt
Copy-Item config.example.json config.local.json
```

只在首次设置时复制示例；不要覆盖已经填写好的本地配置。

## 本地私有配置

在自己电脑上编辑 `config.local.json`。它已被 Git 忽略，不应上传。

| 配置项 | 含义 |
| --- | --- |
| `database` | Zotero 数据库。示例为 `~/Zotero/zotero.sqlite`；数据目录不同时请修改。 |
| `note_title` | 生词 Note 的完整标题，必须精确一致。`Vocabulary` 只是示例。 |
| `anki_profile` | Anki 配置文件夹名称。程序不会自动选择某个账户。 |
| `collection` | 可选：直接填写 `collection.anki2` 路径，代替配置名称。 |
| `anki_packages`、`anki_exe` | 标准 Windows 用户安装可留空；自定义安装时填写。 |
| `output_dir` | 建议保留 `dist`，以使用现有隐私排除规则。 |
| `no_online` | 默认 `true`，不联网查询例句。只有愿意把生词搜索词发送给外部服务时才改为 `false`。 |
| `review_annotation_keys` | 可选：需要人工复核的批注标识列表，只保存在本地。 |

Anki 配置根目录从当前 Windows 用户的应用数据目录推导；非标准位置可以设置 `anki_root`。JSON 路径支持正斜杠、`~` 和环境变量，相对路径以配置文件所在目录为起点。`collection` 与 `anki_profile` 同时填写时，以 `collection` 为准。命令行参数优先于本地配置。

PowerShell 与 Python 共用同一套配置解析逻辑。真实路径、账户名称、笔记标题和批注标识应留在本地配置，不写进源码或说明文档。

## 日常同步

保存 Zotero 中的修改，然后**手动完全退出 Zotero 和 Anki**。双击 `Syne_Zot2Anki.cmd`，或运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/sync_vocabulary.ps1
```

启动器检查环境、备份数据库、同步生词、导出文件并写入报告。只有成功后才重新打开 Anki；失败时窗口保留错误摘要。程序不会强制关闭 Zotero 或 Anki。

可选：安装桌面快捷方式。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install_desktop_shortcut.ps1
```

快捷方式名称是 **Syne_Zot2Anki**。目标位置根据本机项目目录自动设置，快捷方式本身不进入版本管理；项目可以放在任意文件夹。

进阶入口：

```powershell
python scripts/sync_vocabulary.py --help
python scripts/export_vocabulary_note.py --help
python scripts/export_vocabulary_note.py --no-examples --no-online
```

仅导出命令只生成 TSV，不打开或修改 Anki。Python 同步入口不会重新打开 Anki。完整同步即使关闭联网查询，仍需要 PDF 提取依赖。

## 卡片和输出

牌组和笔记类型名称：`Zotero2Anki Vocabulary`。

项目现已更名为 **Zot2Anki**。为继续识别原有卡片，Anki 牌组、笔记类型及同步标签保留原有名称；此次项目改名不会迁移 Anki 数据或另建一套卡片。

字段为 `Word`、`Symbol`、`Chn`、`Example`、`Source`、`ZoteroKeys`、`Notes`；只有 `Notes` 专供个人编辑。模板保存在 `anki-template/`。

本地 `dist/` 中会生成生词 TSV、复核 TSV、同步报告、数据库备份、日志、例句缓存及两种 APKG。报告和日志可能包含本机路径、来源信息。

- `personal.apkg` 包含学习进度和个人笔记，应当视为私有文件。
- `clean.apkg` 的目标是去掉进度和个人笔记，但过滤仍有已知遗漏，未经单独隐私检查不要公开分享。
- 即使没有个人笔记，导出文件仍可能包含生词、文献题名、DOI 链接和 Zotero 标识，不等于匿名数据。

`.gitignore` 排除了生成文件、数据库、备份、PDF、快捷方式和本地配置。忽略文件不会删除它，也不会清除旧提交中的内容；不要强制添加私有文件。若修改输出目录，请放在仓库外，或在运行前添加相应忽略规则。

## 测试与说明

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
python tests/integration_anki.py
node --test tests/core.test.js
```

Anki 集成测试在临时数据库中使用虚构数据，不同步真实生词或修改现有数据库。现有测试尚未覆盖所有同步边界；仓库隐私测试只是基本检查，不能替代全面的秘密信息扫描。

- [实施与操作说明（英文）](IMPLEMENTATION_GUIDE.md)
- [已知问题](KNOWN_ISSUES.md)
- [旧插件手动测试](tests/MANUAL-INTEGRATION.md)

目前尚未选择开源许可证。卡片模板为自行制作；其中使用的第三方组件需在公开发行前单独核对授权。
