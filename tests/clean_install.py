"""Install and exercise an audited ZIP in a fresh Chinese/space path."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.build_release import inspect_zip
from scripts import sync_vocabulary as sync
from tests.fixtures import create_config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('zip', type=Path)
    parser.add_argument('--wheelhouse', type=Path)
    parser.add_argument('--anki-packages', type=Path, default=sync.DEFAULT_ANKI_PACKAGES)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    manifest = inspect_zip(args.zip)
    sync.DEFAULT_ANKI_PACKAGES = args.anki_packages
    with tempfile.TemporaryDirectory(prefix='Zot2Anki 安装测试 ') as temporary:
        temporary = Path(temporary)
        with zipfile.ZipFile(args.zip) as z:
            z.extractall(temporary)
        root = temporary / ('Zot2Anki-v' + manifest['version'])
        setup = ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(root / 'scripts/setup.ps1'),
                 '-Python', sys.executable, '-AnkiPackages', str(args.anki_packages)]
        if args.wheelhouse:
            setup += ['-Wheelhouse', str(args.wheelhouse.resolve())]
        subprocess.run(setup, check=True, cwd=temporary)
        data = temporary / 'Synthetic data'
        data.mkdir()
        config, collection = create_config(data)
        # The subprocess uses the extracted launcher and its own .venv. App
        # detection remains real; CI must not have Anki/Zotero running.
        command = ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(root / 'scripts/sync_vocabulary.ps1'),
                   '-Config', str(config), '-NoOpenAnki']
        subprocess.run(command + ['-DryRun', '-NoOnline', '-RefreshExamples', '-AllowLargeRemoval'], check=True, cwd=temporary)
        subprocess.run(command + ['-NoOnline'], check=True, cwd=temporary)
        subprocess.run(command + ['-NoOnline'], check=True, cwd=temporary)
        reports = [json.loads(p.read_text(encoding='utf-8')) for p in (data / 'output').glob('zot2anki-sync-*.json')]
        assert len(reports) == 3 and sum(r['committed'] is True for r in reports) == 2
        assert sorted(r['sync']['added'] for r in reports if r['committed']) == [0, 1]
        # Exercise the CMD argument-forwarding route using the already-tested
        # environment-only flag; it cannot open personal databases.
        subprocess.run([str(root / 'Syne_Zot2Anki.cmd'), '-Check', '-AnkiPackages', str(args.anki_packages)], check=True, cwd=temporary, stdin=subprocess.DEVNULL)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps({'commit': manifest['commit'], 'clean_install': 'passed',
        'unicode_space_path': 'passed', 'launcher_arguments': 'passed', 'offline_cli': 'passed', 'repeat_sync': 'passed'}, indent=2), encoding='utf-8')
    print('Clean installation acceptance passed.')


if __name__ == '__main__':
    main()
