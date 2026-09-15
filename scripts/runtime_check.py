"""RC runtime gate; must run before any source or personal database is opened."""
import importlib.metadata
import platform
from pathlib import Path
import sys
import tempfile


SUPPORTED_ANKI_VERSIONS = {(26, 5), (26, 9)}


def check_runtime(root: Path, packages: Path, configure_anki):
    if sys.platform != 'win32' or platform.machine().lower() not in ('amd64', 'x86_64'):
        raise RuntimeError('RC 仅支持 Windows x64')
    if sys.version_info[:2] != (3, 13):
        raise RuntimeError('RC 需要 Python 3.13；请运行 scripts/setup.ps1')
    if Path(sys.prefix).resolve() != (root / '.venv').resolve():
        raise RuntimeError('请使用项目 .venv；先运行 scripts/setup.ps1')
    if importlib.metadata.version('PyMuPDF') != '1.28.2':
        raise RuntimeError('PyMuPDF 版本不匹配；请重新运行 scripts/setup.ps1')
    import pymupdf
    Collection, Exporter = configure_anki(packages)
    from anki.buildinfo import version
    try:
        version_tuple = tuple(map(int, version.split('.')))
    except ValueError as exc:
        raise RuntimeError(f'无法识别 Anki 后端版本：{version}') from exc
    if version_tuple not in SUPPORTED_ANKI_VERSIONS:
        raise RuntimeError(f'RC 需要 Anki 26 后端；当前为 {version}')
    with tempfile.TemporaryDirectory(prefix='zot2anki-check-') as temporary:
        collection = Collection(str(Path(temporary) / 'collection.anki2'))
        collection.close()
    return Collection, Exporter, {'platform': 'Windows x64', 'python': platform.python_version(),
                                  'anki': version, 'pymupdf': pymupdf.VersionBind}
