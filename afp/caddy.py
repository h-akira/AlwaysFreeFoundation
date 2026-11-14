"""Caddy, the entrance: one site per project domain, proxied to <project>:8080.

The Caddyfile directory (not the file) is mounted into the container, so that
replacing the file by rename is seen by the container.
"""

from __future__ import annotations

import os
from pathlib import Path

from afp.config import Project
from afp.runner import Runner

COMPOSE_PROJECT = "afp-caddy"


def render(projects: list[Project]) -> str:
    lines = ["# Written by afp sync from afp.json. Do not edit.", ""]
    for p in sorted(projects, key=lambda p: p.domain):
        lines += [f"{p.domain} {{", f"\treverse_proxy {p.name}:8080", "}", ""]
    return "\n".join(lines)


def write_if_changed(path: Path, content: str) -> bool:
    if path.exists() and path.read_text() == content:
        return False
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)
    return True


def _compose(code_dir: Path) -> list[str]:
    return ["docker", "compose", "-p", COMPOSE_PROJECT, "-f", str(code_dir / "caddy" / "compose.yaml")]


def up(runner: Runner, code_dir: Path) -> None:
    runner.run([*_compose(code_dir), "up", "-d", "--remove-orphans"])


def reload(runner: Runner, code_dir: Path) -> None:
    runner.run(
        [*_compose(code_dir), "exec", "-T", "caddy", "caddy", "reload",
         "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
    )
