"""Log of one afp run: a local file (uploaded to the bucket at the end) and stderr.

Run Command returns only the last 1 KB of the output, so the full log goes to
the bucket and stdout gets a short summary as the last lines.
"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path
from typing import TextIO

SUMMARY_LIMIT = 700


def utc_stamp() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def log_name(command: str, project: str | None = None) -> str:
    """Object name of the log in the bucket, e.g. logs/20261114T010203Z-sync.log."""
    suffix = f"-{project}" if project else ""
    return f"logs/{utc_stamp()}-{command}{suffix}.log"


def truncate(text: str, limit: int = SUMMARY_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


class Log:
    def __init__(self, path: Path, echo: TextIO | None = None) -> None:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = path
        self._file = open(path, "a", encoding="utf-8")
        self._echo = echo if echo is not None else sys.stderr

    def info(self, message: str) -> None:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        self._file.write(f"{now} {message}\n")
        self._file.flush()
        print(message, file=self._echo, flush=True)

    def detail(self, text: str) -> None:
        """Long output (e.g. of a command): the file only."""
        if text:
            self._file.write(text if text.endswith("\n") else text + "\n")
            self._file.flush()

    def close(self) -> None:
        self._file.close()
