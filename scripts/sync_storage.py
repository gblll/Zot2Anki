"""Consistent snapshots and recoverable, fail-closed file commits."""
from contextlib import AbstractContextManager, closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile


class StorageError(RuntimeError):
    pass


class CommittedError(StorageError):
    committed = True


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(path: Path) -> dict:
    wal = Path(str(path) + '-wal')
    return {'sha256': sha256(path), 'size': path.stat().st_size,
            'wal': sha256(wal) if wal.exists() and wal.stat().st_size else None}


def require_no_wal(path: Path) -> None:
    wal = Path(str(path) + '-wal')
    if wal.exists() and wal.stat().st_size > 32:
        raise StorageError('原库仍存在 WAL 数据；请正常关闭应用并等待数据合并后重试。')


def validate_database(path: Path) -> None:
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=1)) as db:
            # Current Anki schemas declare this collation. quick_check checks
            # pages/constraints without checking index ordering; Anki itself
            # opens the candidate afterward with its native collation.
            db.create_collation('unicase', lambda a, b: (a.casefold() > b.casefold()) - (a.casefold() < b.casefold()))
            result = db.execute('PRAGMA quick_check').fetchall()
            if result != [('ok',)]:
                raise StorageError('数据库完整性校验失败')
    except sqlite3.Error as exc:
        raise StorageError('数据库无法打开或完整性校验失败') from exc


def consistent_backup(source: Path, target: Path) -> None:
    if target.exists():
        raise StorageError('备份文件已存在；禁止覆盖')
    # SQLite backup, unlike copy2(), includes committed pages still in the WAL.
    src = sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True, timeout=1)
    dst = sqlite3.connect(target)
    import time
    deadline = time.monotonic() + 15
    def progress(status, remaining, total):
        if time.monotonic() > deadline:
            raise StorageError('备份等待超时；数据库可能正在使用')
    try:
        src.backup(dst, pages=256, progress=progress, sleep=0.05)
    finally:
        dst.close()
        src.close()
    validate_database(target)


class CollectionLock(AbstractContextManager):
    """OS lock survives no crashed process; the small lock file may remain."""
    def __init__(self, collection: Path):
        self.path = collection.with_name(collection.name + '.zot2anki.lock')
        self.stream = None

    def __enter__(self):
        self.stream = self.path.open('a+b')
        try:
            if self.path.stat().st_size == 0:
                self.stream.write(b'0')
                self.stream.flush()
            self.stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.stream.close()
            raise StorageError('另一个同步或恢复进程已锁定此 collection') from exc
        return self

    def __exit__(self, *args):
        self.stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.stream, fcntl.LOCK_UN)
        self.stream.close()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def commit_candidate(original: Path, candidate: Path, expected: dict, running_apps) -> dict:
    validate_database(candidate)
    require_no_wal(candidate)
    if running_apps():
        raise StorageError('应用已启动，停止提交。请手动关闭应用后重试。')
    require_no_wal(original)
    if fingerprint(original) != expected:
        raise StorageError('原数据库在运行期间发生变化，停止提交')
    # Candidate is prepared on the original filesystem. Windows also refuses
    # replacement when an application holds a non-sharing database handle.
    os.replace(candidate, original)
    try:
        return fingerprint(original)
    except OSError as exc:
        raise CommittedError('数据库已替换，但无法读取提交后指纹；请检查运行日志') from exc


def publish_file(staged: Path, final: Path) -> None:
    # Staging and final output directories share a filesystem. A hard link is an
    # atomic create-if-absent; neither partial copies nor overwritten runs occur.
    try:
        os.link(staged, final)
    except FileExistsError as exc:
        raise StorageError('产物路径冲突，禁止覆盖：' + final.name) from exc
    staged.unlink()


def recover_outputs(journal: Path) -> dict:
    state = json.loads(journal.read_text(encoding='utf-8'))
    collection = Path(state['collection'])
    with CollectionLock(collection):
        current = fingerprint(collection)
        expected = state.get('after') or state.get('candidate_fingerprint')
        if not expected or current != expected or state.get('stage') not in ('committing', 'committed', 'complete', 'finalizing'):
            raise StorageError('不能确认数据库已提交；禁止自动重跑。请检查运行日志与备份。')
        state.update(committed=True, after=current, stage='finalizing')
        atomic_json(journal, state)
        for artifact in state['artifacts']:
            target, source = Path(artifact['final']), Path(artifact['staged'])
            if target.exists():
                if sha256(target) != artifact['sha256']:
                    raise StorageError('恢复遇到不同内容的现有产物')
            else:
                if sha256(source) != artifact['sha256']:
                    raise StorageError('待恢复产物校验失败')
                publish_file(source, target)
        state['stage'] = 'complete'
        atomic_json(journal, state)
        return state
