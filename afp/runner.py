"""Running external commands (OCI CLI, docker) with logging.

Secrets never go into the arguments: they are passed through the environment
or stdin, and neither is logged.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import IO, Mapping, Optional, Sequence

from afp.errors import AfpError
from afp.log import Log

STDERR_TAIL = 400


class Runner:
    def __init__(self, log: Log) -> None:
        self.log = log

    def run(
        self,
        args: Sequence[str],
        *,
        stdin: str | None = None,
        env: Mapping[str, str] | None = None,
        check: bool = True,
        quiet: bool = False,
        secret_output: bool = False,
        stdout_path: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run a command and capture its output.

        env adds variables to the inherited environment. quiet keeps the
        command line and its output out of the log; secret_output keeps only
        stdout out of it (e.g. a secret's value). stdout_path writes stdout to
        that file instead of capturing it (e.g. a DB dump).
        """
        if not quiet:
            self.log.info("$ " + " ".join(args))
        full_env = None
        if env:
            full_env = dict(os.environ)
            full_env.update(env)
        out: Optional[IO[str]] = open(stdout_path, "w") if stdout_path is not None else None
        try:
            result = subprocess.run(
                list(args), input=stdin, env=full_env, text=True, check=False,
                stdout=out if out is not None else subprocess.PIPE, stderr=subprocess.PIPE,
            )
        finally:
            if out is not None:
                out.close()
        if result.stdout is None:
            result.stdout = ""
        if not quiet:
            if not secret_output:
                self.log.detail(result.stdout)
            self.log.detail(result.stderr)
        if check and result.returncode != 0:
            tail = result.stderr.strip()[-STDERR_TAIL:]
            raise AfpError(f"{args[0]} {args[1] if len(args) > 1 else ''} failed ({result.returncode}): {tail}")
        return result
