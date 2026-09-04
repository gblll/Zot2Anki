# Third-party notices / 第三方声明

Zot2Anki's original code and documentation are licensed under the [MIT License](LICENSE), copyright 2026 gblll. Third-party components retain their own copyright notices and licenses. The MIT grant applies to original project material, not to third-party software, documents or learning materials.

## Scope of the MIT grant / MIT 适用范围

The current scripts import the Anki Python backend and PyMuPDF directly. When conveying a combined program with AGPL components, comply with the applicable AGPL conditions for that program, including preserving notices and providing its Corresponding Source as required. The MIT grant for original project material remains available when that material is reused separately. It does not grant permission to redistribute the combined program under MIT alone or to ignore dependency licenses.

Installing a dependency separately, omitting its wheel from this ZIP, or adding this notice does not by itself waive its license obligations. Anyone distributing binaries or a bundled application must provide the required notices, license texts and access to Corresponding Source; anyone offering a modified AGPL program over a network must also meet the applicable network-source requirements. This source ZIP is not a bundled runtime or a complete binary-distribution source offer.

The [AGPL version 3 text](LICENSES/AGPL-3.0.txt) is included unchanged from the [SPDX license text](https://github.com/spdx/license-list-data/blob/main/text/AGPL-3.0-only.txt) for reference. Each component's own notice determines whether version 3 only or version 3 or later is available. This copy does not change the MIT license of original project material. See also the [GNU license compatibility explanation](https://www.gnu.org/licenses/license-compatibility.en.html).

## AnkiPersistence — embedded code

The card templates `anki-template/front.html` and `anki-template/back.html` contain code derived from [AnkiPersistence](https://github.com/SimonLammer/anki-persistence) by Simon Lammer, copyright 2018, under the MIT License. The namespace in the templates refers to that upstream project. The complete upstream notice is included in [LICENSES/AnkiPersistence-MIT.txt](LICENSES/AnkiPersistence-MIT.txt). The third-party notice applies to that embedded component.

## PyMuPDF / MuPDF — separately installed dependency

[PyMuPDF 1.28.2](https://pypi.org/project/pymupdf/1.28.2/) is installed into the local `.venv` from its Windows x64 wheel, with a pinned SHA256 in `requirements.txt`. PyMuPDF/MuPDF are offered under GNU AGPL v3 or commercial terms by Artifex; consult the [official licensing documentation](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright). The installed wheel's COPYING notice states: "Dual Licensed - GNU AFFERO GPL 3.0 or Artifex Commercial License". No Artifex commercial license is supplied by Zot2Anki.

Neither the wheel nor an installed runtime is redistributed in the source ZIP. Setup downloads it directly. Upstream source is available from [PyMuPDF](https://github.com/pymupdf/PyMuPDF), the versioned source distribution on [PyPI](https://pypi.org/project/pymupdf/1.28.2/#files), and [MuPDF](https://mupdf.com/). Distributors must ensure the Corresponding Source for their actual dependency builds is available as required; these links are not a substitute for those obligations.

## Anki, Python and other runtimes

[Anki](https://github.com/ankitects/anki) and its Python packages are external software, not bundled with this RC. The baseline uses Anki 26.5's backend. The [Anki 26.05 license notice](https://github.com/ankitects/anki/blob/26.05/LICENSE), copied without changes to [LICENSES/Anki-LICENSE.txt](LICENSES/Anki-LICENSE.txt), identifies AGPL version 3 or later and components with other terms. The corresponding upstream source tree is [Anki 26.05](https://github.com/ankitects/anki/tree/26.05). Anki's license notices and its own third-party notices apply to that installation. CI separately installs a synthetic-test backend from PyPI.

[Python](https://www.python.org/psf/license/) is installed separately. No interpreter or Anki installation folder is included in the release ZIP. Standard-library use does not replace the respective runtime's notices.

## Public metadata providers

Optional online examples query [Crossref](https://www.crossref.org/documentation/retrieve-metadata/rest-api/) and [Europe PMC](https://europepmc.org/RestfulWebService). Public metadata verification establishes provenance, not publication rights to article text. No article/PDF dataset or personal vocabulary materials are bundled. Online lookup is disabled by default.

## 中文说明

本项目原创代码和文档采用 MIT。模板内的 AnkiPersistence 代码继续保留 Simon Lammer 的 MIT 版权与许可声明。PyMuPDF / MuPDF、Anki 和 Python 保留各自许可，均为独立安装的外部运行依赖，不随 ZIP 捆绑。

当前脚本直接导入 Anki 后端和 PyMuPDF。分发含 AGPL 组件的组合程序时，须遵守相应 AGPL 条件，保留声明并按要求提供对应源码；单独安装依赖、未捆绑运行时或列出本声明，都不等于免除义务。原创部分独立复用时仍可使用 MIT，但不能据此把整个组合程序声明为仅受 MIT 约束。公开出处核验也不等同于取得文章或学习资料的分享授权。
