"""Cross-process file locks with fcntl.flock — Mac/Unix only (the demo is Mac-only;
there is no Windows port).

A writer holds an EXCLUSIVE lock on <file>.lock for its whole read-modify-write. A
reader takes a SHARED lock, but only on a lock file a writer already created:
readers never create one, so verifying a chain in a read-only place (or the shipped
example) leaves nothing behind. If no lock file exists, no locking writer has
touched that file; in the narrow race where one starts mid-read, a torn line makes
the hash check FAIL, never pass.

The lock file is never deleted: deleting a lock file another process holds is a
classic race. The kernel releases a flock when the descriptor closes or the process
exits, including a crash or kill -9, so a dead writer never leaves a stale lock.

Fail closed: if the lock can't be had within LOCK_TIMEOUT seconds, LockTimeout is
raised before anything is read, written, or signed. 15 seconds sits above the
10-second ssh-keygen signing timeout (signing.py), so a slow but healthy signer
holding the lock never trips a waiting writer.
"""

from __future__ import annotations

import contextlib
import errno
import fcntl
import os
import time
from pathlib import Path

LOCK_TIMEOUT = 15.0
_POLL = 0.01


class LockTimeout(RuntimeError):
    """The lock wasn't acquired in time; nothing was read, written, or signed."""


def lock_path(path) -> Path:
    path = Path(path)
    return path.with_name(path.name + ".lock")


def _acquire(fd: int, op: int, timeout: float, name: str) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(fd, op | fcntl.LOCK_NB)
            return
        except OSError as e:
            if e.errno not in (errno.EWOULDBLOCK, errno.EAGAIN):
                raise
        if time.monotonic() >= deadline:
            raise LockTimeout(f"could not lock {name} within {timeout:g}s; nothing was written")
        time.sleep(_POLL)


@contextlib.contextmanager
def exclusive(path, timeout: float | None = None):
    """Hold <path>.lock exclusively, creating it if needed."""
    lp = lock_path(path)
    lp.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lp, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        _acquire(fd, fcntl.LOCK_EX, LOCK_TIMEOUT if timeout is None else timeout, lp.name)
        yield
    finally:
        os.close(fd)   # releases the lock; the lock file stays


@contextlib.contextmanager
def shared_if_present(path, timeout: float | None = None):
    """Hold <path>.lock shared, if a writer has created it; otherwise lock nothing."""
    try:
        fd = os.open(lock_path(path), os.O_RDONLY)
    except OSError:
        yield
        return
    try:
        _acquire(fd, fcntl.LOCK_SH, LOCK_TIMEOUT if timeout is None else timeout, lock_path(path).name)
        yield
    finally:
        os.close(fd)
