"""An exclusive lock shared by all processes that write one file.

Why: on Windows, Python's append mode emulates O_APPEND with a seek followed by a write,
and the pair isn't atomic across processes. Two runs appending to the spend ledger at
the same moment can both seek to the same end, and the second write overwrites the
first. One entry is lost, and a fragment of it is left behind as a corrupt line (seen in
M6, when two evals ran in parallel). A lock on a sidecar file serialises the writers.
"""

import os
import sys
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def exclusive(path: Path) -> Generator[None]:
    """Hold an exclusive lock on `<path>.lock` for the duration of the block."""
    lock_path = path.with_name(path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT)
    try:
        if sys.platform == "win32":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)  # retries for ~10 s, then raises
            try:
                yield
            finally:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
