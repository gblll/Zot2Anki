# Third-party notices / 第三方声明

No project open-source license is selected for Zot2Anki. This private RC includes the notices below for components it uses. These notices do not relicense the project or grant additional rights to learning materials.

## AnkiPersistence — embedded code

The card templates `anki-template/front.html` and `anki-template/back.html` contain code derived from [AnkiPersistence](https://github.com/SimonLammer/anki-persistence) by Simon Lammer, copyright 2018, under the MIT License. The namespace in the templates refers to that upstream project. The complete upstream notice is included in [LICENSES/AnkiPersistence-MIT.txt](LICENSES/AnkiPersistence-MIT.txt). The third-party notice applies to that embedded component.

## PyMuPDF / MuPDF — separately installed dependency

[PyMuPDF 1.28.2](https://pypi.org/project/pymupdf/1.28.2/) is installed into the local `.venv` from its Windows x64 wheel, with a pinned SHA256 in `requirements.txt`. PyMuPDF/MuPDF are offered under GNU AGPL or commercial terms by Artifex; consult the [official licensing documentation](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright). Neither the wheel nor an installed runtime is redistributed in the source ZIP. Setup downloads it directly. License obligations for any future public distribution must be reviewed before selecting a project license.

## Anki, Python and other runtimes

[Anki](https://github.com/ankitects/anki) and its Python packages are external software, not bundled with this RC. The baseline uses Anki 26.5's backend. Anki's license notices and its own third-party notices apply to that installation. CI separately installs a synthetic-test backend from PyPI.

[Python](https://www.python.org/psf/license/) is installed separately. No interpreter or Anki installation folder is included in the release ZIP. Standard-library use does not replace the respective runtime's notices.

## Public metadata providers

Optional online examples query [Crossref](https://www.crossref.org/documentation/retrieve-metadata/rest-api/) and [Europe PMC](https://europepmc.org/RestfulWebService). Public metadata verification establishes provenance, not publication rights to article text. No article/PDF dataset or personal vocabulary materials are bundled. Online lookup is disabled by default.

## 中文说明

本项目尚未选择开源许可证，只准备私有预发布。模板内的 AnkiPersistence 代码保留 Simon Lammer 的 MIT 版权与许可声明。PyMuPDF / MuPDF、Anki 和 Python 均为独立安装的外部运行依赖，不随 ZIP 捆绑；未来公开发行前仍须确认相应许可义务。公开出处核验不等同于获得文章或学习资料的分享授权。
