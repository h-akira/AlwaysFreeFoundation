"""afp: the platform's command on the VM. Runs as root.

Called by afp-bootstrap (install, then sync) and, through Run Command, by the
administrator's make targets. The platform code itself is switched only by
afp-bootstrap, never by afp.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from afp import caddy, config, db
from afp import project as projects_mod
from afp.errors import AfpError
from afp.lock import Lock
from afp.log import Log, log_name, truncate
from afp.oci import Oci, metadata_region
from afp.runner import Runner

LOCK_TIMEOUT = 900  # shorter than the Run Command timeouts used by make
NETWORK = "afp"


@dataclass(frozen=True)
class Paths:
    code: Path
    caddy_dir: Path = Path("/opt/afp/caddy")
    run_dir: Path = Path("/run/afp")
    log_dir: Path = Path("/var/log/afp")
    # Each project's compose.afp.yaml of the versions it ran (refetched every time).
    projects_dir: Path = Path("/opt/afp/projects")
    # DB dumps on their way to the bucket (on disk, not tmpfs).
    work_dir: Path = Path("/var/tmp/afp")


@dataclass
class Context:
    paths: Paths
    log: Log
    runner: Runner
    oci: Optional[Oci]

    def need_oci(self) -> Oci:
        if self.oci is None:
            self.oci = Oci(self.runner, metadata_region())
        return self.oci


def load_config(ctx: Context) -> config.Config:
    oci = ctx.need_oci()
    cfg = config.parse(oci.get_object(config.BUCKET, "afp.json"))
    oci.namespace = cfg.namespace
    return cfg


def cmd_install(ctx: Context, args: argparse.Namespace) -> str:
    """The VM-wide pieces the projects and Caddy rely on. Idempotent."""
    if ctx.runner.run(["docker", "network", "inspect", NETWORK], check=False, quiet=True).returncode != 0:
        ctx.runner.run(["docker", "network", "create", NETWORK])
    ctx.paths.caddy_dir.mkdir(mode=0o755, parents=True, exist_ok=True)
    ctx.paths.run_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    return "installed"


def sync_databases(ctx: Context, cfg: config.Config) -> None:
    if not cfg.projects:
        return
    oci = ctx.need_oci()
    admin_password = oci.secret(cfg.db.admin_secret_id)
    sql = "".join(
        db.project_sql(p, db.project_password(oci.secret(p.secret_id), p.name)) for p in cfg.projects
    )
    ctx.log.info(f"bringing {len(cfg.projects)} project database(s) and user(s) in line")
    db.run_sql(ctx.runner, db.mysql_image(ctx.paths.code), cfg.db, admin_password, sql)


def sync_caddy(ctx: Context, cfg: config.Config) -> bool:
    """Write the Caddyfile, keep Caddy up and reload it.

    Reloaded every time, not only when the file changed: a failed reload
    leaves the new file behind, and the next sync must try it again. Caddy
    does nothing when the configuration is the same.
    """
    ctx.paths.caddy_dir.mkdir(mode=0o755, parents=True, exist_ok=True)
    changed = caddy.write_if_changed(ctx.paths.caddy_dir / "Caddyfile", caddy.render(cfg.projects))
    caddy.up(ctx.runner, ctx.paths.code)
    # A container that has just started may not take the reload yet.
    for attempt in range(5):
        try:
            caddy.reload(ctx.runner, ctx.paths.code)
            break
        except AfpError:
            if attempt == 4:
                raise
            time.sleep(3)
    return changed


def cmd_sync(ctx: Context, args: argparse.Namespace) -> str:
    """Bring the VM in line with afp.json."""
    cfg = load_config(ctx)
    with Lock(ctx.paths.run_dir / "lock", LOCK_TIMEOUT):
        sync_databases(ctx, cfg)
        changed = sync_caddy(ctx, cfg)
        projects = projects_mod.Projects(ctx, cfg)
        stopped = projects.stop_removed()
        started = projects.start_stopped()
    names = ", ".join(p.name for p in cfg.projects) or "none"
    summary = f"projects: {names}; Caddyfile {'updated' if changed else 'unchanged'}"
    if started:
        summary += f"; started: {', '.join(started)}"
    if stopped:
        summary += f"; stopped: {', '.join(stopped)}"
    return summary


def cmd_deploy(ctx: Context, args: argparse.Namespace) -> str:
    """Deploy TAG of PROJECT; on failure, go back to the version before."""
    projects_mod.check_tag(args.tag)
    cfg = load_config(ctx)
    p = projects_mod.find(cfg, args.project)
    with Lock(ctx.paths.run_dir / "lock", LOCK_TIMEOUT):
        return projects_mod.Projects(ctx, cfg).deploy(p, args.tag)


def cmd_rollback(ctx: Context, args: argparse.Namespace) -> str:
    """Deploy PROJECT's previous version again (images and compose only, not the DB)."""
    cfg = load_config(ctx)
    p = projects_mod.find(cfg, args.project)
    with Lock(ctx.paths.run_dir / "lock", LOCK_TIMEOUT):
        return projects_mod.Projects(ctx, cfg).rollback(p)


def cmd_backup(ctx: Context, args: argparse.Namespace) -> str:
    """Dump PROJECT's database (every project's without PROJECT) to the bucket."""
    cfg = load_config(ctx)
    targets = [projects_mod.find(cfg, args.project)] if args.project else cfg.projects
    with Lock(ctx.paths.run_dir / "lock", LOCK_TIMEOUT):
        projects = projects_mod.Projects(ctx, cfg)
        names = [projects.dump(p) for p in targets]
    return "dumped: " + (", ".join(names) or "no projects")


@dataclass(frozen=True)
class Command:
    run: Callable[[Context, argparse.Namespace], str]
    help: str
    upload_log: bool
    # (name, nargs) of positional arguments
    arguments: tuple[tuple[str, Optional[str]], ...] = ()


COMMANDS = {
    "install": Command(cmd_install, "set up the Docker network and directories (idempotent)", upload_log=False),
    "sync": Command(
        cmd_sync,
        "create project DBs and users, write the Caddyfile, reload Caddy, start projects that should run "
        "and stop those no longer listed",
        upload_log=True,
    ),
    "deploy": Command(
        cmd_deploy,
        "dump the DB, then run TAG of PROJECT (released by make deploy) and wait until healthy; "
        "on failure go back to the version before",
        upload_log=True,
        arguments=(("project", None), ("tag", None)),
    ),
    "rollback": Command(
        cmd_rollback,
        "deploy the previous version of PROJECT again (the DB is not rolled back)",
        upload_log=True,
        arguments=(("project", None),),
    ),
    "backup": Command(
        cmd_backup,
        "dump the DB of PROJECT, or of every project, to the bucket",
        upload_log=True,
        arguments=(("project", "?"),),
    ),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="afp", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True
    for name, command in COMMANDS.items():
        cmd = sub.add_parser(name, help=command.help, description=command.help)
        for arg, nargs in command.arguments:
            cmd.add_argument(arg, nargs=nargs)
    return parser


def finish(ctx: Context, object_name: str, upload: bool) -> str:
    """Upload the log to the bucket; tell where it is."""
    ctx.log.close()
    if not upload or ctx.oci is None or ctx.oci.namespace is None:
        return str(ctx.log.path)
    try:
        # quiet: the log is closed, and the upload must not write into it.
        ctx.oci.put_object(config.BUCKET, object_name, ctx.log.path, "text/plain", quiet=True)
    except Exception as e:  # the command itself is over; only report it
        return f"{ctx.log.path} (upload failed: {type(e).__name__})"
    ctx.log.path.unlink()
    return f"bucket {config.BUCKET}: {object_name}"


def main(argv: list[str] | None = None, paths: Paths | None = None) -> int:
    args = build_parser().parse_args(argv)
    if paths is None:
        if os.geteuid() != 0:
            print("afp: must run as root", file=sys.stderr)
            return 2
        paths = Paths(code=Path(__file__).resolve().parents[1])
    command = COMMANDS[args.command]
    object_name = log_name(args.command, getattr(args, "project", None))
    log = Log(paths.log_dir / Path(object_name).name)
    ctx = Context(paths=paths, log=log, runner=Runner(log), oci=None)
    code = 0
    try:
        result = f"OK: {command.run(ctx, args)}"
    except AfpError as e:
        log.info(f"error: {e}")
        result, code = f"FAILED: {e}", 1
    except Exception as e:  # keep the summary short; the traceback goes to the log
        log.detail(traceback.format_exc())
        result, code = f"FAILED: unexpected {type(e).__name__}: {e}", 1
    where = finish(ctx, object_name, command.upload_log)
    # The summary is printed last; make keeps only the end of the output.
    print(f"afp {args.command}: {truncate(result)}\nlog: {where}")
    return code
