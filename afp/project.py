"""Running projects: deploy, roll back, dump, and bring them back after a reboot.

In the bucket:
  releases/<project>/<tag>/compose.afp.yaml   put there by make deploy
  state/<project>.json                        {"current": tag, "previous": tag|null}
  dumps/<project>/<time>[-before-<tag>].sql.gz

Values for compose.afp.yaml (docs/04_using.md §3), secrets included, go to
docker compose through its environment; no env file is written.
"""

from __future__ import annotations

import gzip
import json
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from afp import db
from afp.config import BUCKET, Config, Project
from afp.errors import AfpError
from afp.log import utc_stamp

if TYPE_CHECKING:
    from afp.cli import Context

# Docker tag syntax.
TAG = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")
WAIT_TIMEOUT = 300  # seconds for every service to become healthy
CADDY_PROJECT = "afp-caddy"


def check_tag(tag: str) -> None:
    if not TAG.match(tag):
        raise AfpError(f"invalid tag {tag!r} (must be usable as a Docker tag)")


def find(cfg: Config, name: str) -> Project:
    for p in cfg.projects:
        if p.name == name:
            return p
    raise AfpError(f"project {name!r} is not in afp.json")


def release_object(project: str, tag: str) -> str:
    return f"releases/{project}/{tag}/compose.afp.yaml"


def state_object(project: str) -> str:
    return f"state/{project}.json"


def registry(cfg: Config) -> str:
    return cfg.image_prefix_base.split("/", 1)[0]


def compose_env(cfg: Config, p: Project, tag: str, secrets: dict[str, str]) -> dict[str, str]:
    env = {name: value for name, value in secrets.items() if name != "AFP_DB_PASSWORD"}
    env.update(
        {
            "AFP_IMAGE_PREFIX": f"{cfg.image_prefix_base}/{p.name}",
            "AFP_TAG": tag,
            "AFP_PROJECT": p.name,
            "AFP_DOMAIN": p.domain,
            "AFP_DB_HOST": cfg.db.host,
            "AFP_DB_PORT": str(cfg.db.port),
            "AFP_DB_NAME": p.db_name,
            "AFP_DB_USER": p.db_name,
            "AFP_DB_PASSWORD": secrets["AFP_DB_PASSWORD"],
        }
    )
    return env


def parse_state(text: str | None) -> dict[str, str | None]:
    if text is None:
        return {"current": None, "previous": None}
    try:
        data = json.loads(text)
    except ValueError as e:
        raise AfpError(f"the current-version state is not JSON: {e}") from e
    return {"current": data.get("current"), "previous": data.get("previous")}


def next_state(state: dict[str, str | None], tag: str) -> dict[str, str | None]:
    """After a successful deploy of tag. Deploying the current tag again keeps previous."""
    current = state["current"]
    return {"current": tag, "previous": state["previous"] if current == tag else current}


class Projects:
    """Operations on the projects of one afp run (one Context, one afp.json)."""

    def __init__(self, ctx: Context, cfg: Config) -> None:
        self.ctx = ctx
        self.cfg = cfg
        self.oci = ctx.need_oci()
        self._logged_in = False

    # --- bucket ------------------------------------------------------------

    def read_state(self, p: Project) -> dict[str, str | None]:
        return parse_state(self.oci.get_object_or_none(BUCKET, state_object(p.name)))

    def write_state(self, p: Project, state: dict[str, str | None]) -> None:
        path = self._work() / f"{p.name}.state.json"
        path.write_text(json.dumps(state) + "\n")
        self.oci.put_object(BUCKET, state_object(p.name), path, "application/json")
        path.unlink()

    def fetch_release(self, p: Project, tag: str) -> Path:
        text = self.oci.get_object_or_none(BUCKET, release_object(p.name, tag))
        if text is None:
            raise AfpError(f"no release {release_object(p.name, tag)} in the bucket; run make deploy")
        path = self.ctx.paths.projects_dir / p.name / tag / "compose.afp.yaml"
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def _work(self) -> Path:
        self.ctx.paths.work_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        return self.ctx.paths.work_dir

    # --- secrets and registry ------------------------------------------------

    def secrets(self, p: Project) -> dict[str, str]:
        text = self.oci.secret(p.secret_id)
        values: dict[str, str] = {}
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        if not isinstance(data, dict) or not all(isinstance(v, str) for v in data.values()):
            raise AfpError(f"the secret of project {p.name} is not a JSON object of strings")
        values.update(data)
        db.project_password(text, p.name)  # checks AFP_DB_PASSWORD
        for name, secret_id in p.manual_secret_ids.items():
            values[name] = self.oci.secret(secret_id)
        return values

    def login(self) -> None:
        """docker login to OCIR as the VM (the token lasts an hour)."""
        if self._logged_in:
            return
        host = registry(self.cfg)
        token = self.oci.registry_token(host)
        self.ctx.runner.run(["docker", "login", host, "-u", "BEARER_TOKEN", "--password-stdin"], stdin=token)
        self._logged_in = True

    # --- compose -------------------------------------------------------------

    def _compose(self, p: Project, path: Optional[Path] = None) -> list[str]:
        args = ["docker", "compose", "-p", p.name]
        return args + (["-f", str(path)] if path is not None else [])

    def up(self, p: Project, tag: str, secrets: dict[str, str]) -> None:
        """Pull and start tag; fail unless every service becomes healthy."""
        path = self.fetch_release(p, tag)
        env = compose_env(self.cfg, p, tag, secrets)
        self.login()
        self.ctx.runner.run([*self._compose(p, path), "pull", "-q"], env=env)
        self.ctx.runner.run(
            [*self._compose(p, path), "up", "-d", "--no-build", "--remove-orphans",
             "--wait", "--wait-timeout", str(WAIT_TIMEOUT)],
            env=env,
        )

    def down(self, name: str) -> None:
        self.ctx.runner.run(["docker", "compose", "-p", name, "down"])

    def running(self, p: Project) -> bool:
        result = self.ctx.runner.run(
            ["docker", "compose", "-p", p.name, "ps", "-q", "--status", "running"], quiet=True
        )
        return bool(result.stdout.strip())

    def compose_projects(self) -> list[str]:
        result = self.ctx.runner.run(["docker", "compose", "ls", "--all", "--format", "json"], quiet=True)
        try:
            return [item["Name"] for item in json.loads(result.stdout or "[]")]
        except (ValueError, KeyError, TypeError) as e:
            raise AfpError("cannot read docker compose ls") from e

    # --- DB dumps ------------------------------------------------------------

    def dump(self, p: Project, label: str = "") -> str:
        """Dump the project's database to the bucket; return the object name."""
        admin_password = self.oci.secret(self.cfg.db.admin_secret_id)
        work = self._work()
        raw = work / f"{p.name}.sql"
        packed = work / f"{p.name}.sql.gz"
        name = f"dumps/{p.name}/{utc_stamp()}{label}.sql.gz"
        try:
            self.ctx.runner.run(
                [
                    "docker", "run", "--rm", "-e", "MYSQL_PWD", db.mysql_image(self.ctx.paths.code),
                    "mysqldump", "-h", self.cfg.db.host, "-P", str(self.cfg.db.port), "-u", self.cfg.db.admin_user,
                    "--single-transaction", "--set-gtid-purged=OFF", "--no-tablespaces",
                    "--routines", "--triggers", "--databases", p.db_name,
                ],
                env={"MYSQL_PWD": admin_password},
                stdout_path=raw,
            )
            with open(raw, "rb") as src, gzip.open(packed, "wb") as dst:
                shutil.copyfileobj(src, dst)
            self.oci.put_object(BUCKET, name, packed, "application/gzip")
        finally:
            raw.unlink(missing_ok=True)
            packed.unlink(missing_ok=True)
        self.ctx.log.info(f"dumped {p.db_name} to {name}")
        return name

    # --- operations ----------------------------------------------------------

    def deploy(self, p: Project, tag: str) -> str:
        check_tag(tag)
        state = self.read_state(p)
        self.fetch_release(p, tag)  # fail before anything else if it is missing
        dump = self.dump(p, f"-before-{tag}")
        secrets = self.secrets(p)
        try:
            self.up(p, tag, secrets)
        except AfpError as e:
            current = state["current"]
            if current:
                self.ctx.log.info(f"{tag} failed; going back to {current}")
                try:
                    self.up(p, current, secrets)
                    after = f"back on {current}"
                except AfpError as e2:
                    after = f"going back to {current} failed too: {e2}"
            else:
                self.down(p.name)
                after = "stopped (no previous version)"
            raise AfpError(f"deploy of {p.name} {tag} failed: {e} -- {after}") from e
        new = next_state(state, tag)
        self.write_state(p, new)
        return f"{p.name} is now {tag} (previous: {new['previous'] or 'none'}); dump before it: {dump}"

    def rollback(self, p: Project) -> str:
        previous = self.read_state(p)["previous"]
        if not previous:
            raise AfpError(f"{p.name} has no previous version")
        result = self.deploy(p, previous)
        return f"{result}; the DB is not rolled back (dumps are in dumps/{p.name}/)"

    def start_stopped(self) -> list[str]:
        """Start each project's current version when none of it is running
        (a new or rebooted VM). Returns the names started."""
        started: list[str] = []
        failures: list[str] = []
        for p in self.cfg.projects:
            current = self.read_state(p)["current"]
            if not current or self.running(p):
                continue
            self.ctx.log.info(f"starting {p.name} {current}")
            try:
                self.up(p, current, self.secrets(p))
                started.append(p.name)
            except AfpError as e:
                failures.append(f"{p.name}: {e}")
        if failures:
            raise AfpError("could not start " + "; ".join(failures))
        return started

    def stop_removed(self) -> list[str]:
        """Stop the containers of projects no longer in afp.json (their DBs stay)."""
        names = {p.name for p in self.cfg.projects}
        stopped = [n for n in self.compose_projects() if n not in names and not n.startswith("afp")]
        for name in stopped:
            self.ctx.log.info(f"stopping {name}: no longer in afp.json")
            self.down(name)
        return stopped
