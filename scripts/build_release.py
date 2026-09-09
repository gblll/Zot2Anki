"""Build a reproducible source-only Windows ZIP from a committed allowlist."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {'.git', '.venv', '.codex', '.agents', 'dist', 'node_modules', '__pycache__'}
SUFFIXES = {'.py', '.ps1', '.cmd', '.js', '.json', '.md', '.txt', '.html', '.css', '.xhtml', '.ftl', '.yml', '.gitignore'}


def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, check=True).stdout


def release_files(commit='HEAD'):
    sha = git('rev-parse', '--verify', commit + '^{commit}').decode().strip()
    entries = git('show', sha + ':release-files.txt').decode('utf-8').splitlines()
    files = [line for line in entries if line and not line.startswith('#')]
    if len(files) != len(set(files)):
        raise RuntimeError('Duplicate release allowlist entries')
    tracked = set(git('ls-tree', '-r', '--name-only', sha).decode().splitlines())
    for name in files:
        path = PurePosixPath(name)
        if (path.is_absolute() or '..' in path.parts or set(path.parts) & FORBIDDEN or '\\' in name or
                name not in tracked or (path.suffix not in SUFFIXES and name not in ('VERSION', '.gitignore', 'LICENSE')) or
                'local.' in path.name or path.name == 'config.local.json'):
            raise RuntimeError('Disallowed release entry: ' + name)
    return sha, files


def inspect_zip(path):
    with zipfile.ZipFile(path) as archive:
        if len(archive.namelist()) != len(set(archive.namelist())):
            raise RuntimeError('Duplicate archive entries')
        manifest_name = next(n for n in archive.namelist() if n.endswith('/RELEASE-MANIFEST.json'))
        manifest = json.loads(archive.read(manifest_name))
        prefix = manifest_name.removesuffix('RELEASE-MANIFEST.json')
        for name in archive.namelist():
            if '..' in PurePosixPath(name).parts or PurePosixPath(name).is_absolute() or '\\' in name or ':' in name:
                raise RuntimeError('Unsafe archive path')
        if set(archive.namelist()) != {prefix + name for name in manifest['files']} | {manifest_name}:
            raise RuntimeError('Unexpected release payload')
        for name, digest in manifest['files'].items():
            if hashlib.sha256(archive.read(prefix + name)).hexdigest() != digest:
                raise RuntimeError('Release payload hash mismatch')
            if set(PurePosixPath(name).parts) & FORBIDDEN:
                raise RuntimeError('Private release payload')
        return manifest


def build(output: Path, commit='HEAD'):
    sha, names = release_files(commit)
    version = git('show', sha + ':VERSION').decode().strip()
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+-rc\.[0-9]+', version):
        raise RuntimeError('Unexpected RC version')
    output.mkdir(parents=True, exist_ok=True)
    archive_path = output / f'Zot2Anki-v{version}-windows.zip'
    if archive_path.exists():
        raise RuntimeError('Release output exists; use an empty output directory')
    files = {name: git('show', sha + ':' + name) for name in names}
    for name, data in files.items():
        text = data.decode('utf-8-sig')
        if re.search(r'\b[A-Za-z]:[\\/]|/(?:Users|home)/[^/\s]+/', text):
            raise RuntimeError('Machine path in release: ' + name)
        if re.search(r'gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY', text):
            raise RuntimeError('Possible credential in release: ' + name)
    manifest = {'version': version, 'commit': sha, 'private_prerelease': False,
                'files': {name: hashlib.sha256(value).hexdigest() for name, value in files.items()}}
    files['RELEASE-MANIFEST.json'] = (json.dumps(manifest, indent=2) + '\n').encode()
    epoch = int(git('show', '-s', '--format=%ct', sha).decode())
    stamp = datetime.fromtimestamp(epoch, timezone.utc).timetuple()[:6]
    with zipfile.ZipFile(archive_path, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(f'Zot2Anki-v{version}/' + name, date_time=stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    inspect_zip(archive_path)
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    with (output / 'SHA256SUMS.txt').open('x', encoding='utf-8') as stream:
        stream.write(digest + '  ' + archive_path.name + '\n')
    return archive_path, manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--commit', default='HEAD')
    args = parser.parse_args()
    path, manifest = build(args.output, args.commit)
    print(json.dumps({'zip': str(path), 'commit': manifest['commit'], 'files': len(manifest['files'])}))
