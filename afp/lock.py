"""One afp operation at a time on the VM (sync, deploy, rollback, backup)."""

from __future__ import annotations

import fcntl
import os
import time
from pathlib import Path
from typing import IO

from afp.errors import AfpError


class Lock:
    """flock on a file; released when closed or when the process exits."""

    def __init__(self, path: Path, timeout: float, poll: float = 2.0) -> None:
        self.path = path
        self.timeout = timeout
        self.poll = poll
        self._file: IO[str] | None = None

    def __enter__(self) -> "Lock":
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        f = open(self.path, "a")
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    f.close()
                    raise AfpError(f"another afp operation holds {self.path} (waited {self.timeout:.0f}s)")
                time.sleep(self.poll)
        os.set_inheritable(f.fileno(), False)
        self._file = f
        return self

    def __exit__(self, *exc: object) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None
