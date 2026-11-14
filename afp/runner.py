"""Running external commands (OCI CLI, docker) with logging.

Secrets never go into the arguments: they are passed through the environment
or stdin, and neither is logged.
"""

from __future__ import annotations

import os
import subprocess
from typing import Mapping, Sequence

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
    ) -> subprocess.CompletedProcess[str]:
        """Run a command and capture its output.

        env adds variables to the inherited environment. quiet keeps the
        command line and its output out of the log; secret_output keeps only
        stdout out of it (e.g. a secret's value).
        """
        if not quiet:
            self.log.info("$ " + " ".join(args))
        full_env = None
        if env:
            full_env = dict(os.environ)
            full_env.update(env)
        result = subprocess.run(
            list(args), input=stdin, env=full_env, capture_output=True, text=True, check=False
        )
        if not quiet:
            if not secret_output:
                self.log.detail(result.stdout)
            self.log.detail(result.stderr)
        if check and result.returncode != 0:
            tail = result.stderr.strip()[-STDERR_TAIL:]
            raise AfpError(f"{args[0]} {args[1] if len(args) > 1 else ''} failed ({result.returncode}): {tail}")
        return result
