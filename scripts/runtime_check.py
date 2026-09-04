"""RC runtime gate; must run before any source or personal database is opened."""
import importlib.metadata
import platform
from pathlib import Path
import sys
import tempfile


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
    if tuple(map(int, version.split('.'))) != (26, 5):
        raise RuntimeError('RC 需要 Anki 26.5 后端')
    with tempfile.TemporaryDirectory(prefix='zot2anki-check-') as temporary:
        collection = Collection(str(Path(temporary) / 'collection.anki2'))
        collection.close()
    return Collection, Exporter, {'platform': 'Windows x64', 'python': platform.python_version(),
                                  'anki': version, 'pymupdf': pymupdf.VersionBind}
