"""A fake VM for afp tests: answers the oci and docker commands afp runs.

It keeps a bucket (objects), the secrets, and which tag of which compose
project is running. Tags in `broken` never become healthy.
"""

from __future__ import annotations

import base64
import io
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from afp import cli  # noqa: E402
from afp.errors import AfpError  # noqa: E402
from afp.log import Log  # noqa: E402
from afp.oci import Oci  # noqa: E402

REGION = "us-ashburn-1"
DB_PASSWORD = "Ab3-xyz_DEF.ghi~jkl"
ADMIN_PASSWORD = "Admin-Pass_1"
SIGNING_KEY = "sign-Key_123"
API_KEY = "api'key$with\"quotes"


def afp_json(projects: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "region": REGION,
        "namespace": "ns",
        "bucket": "afp",
        "platform_repository": "https://github.com/example/platform",
        "db": {"host": "10.0.1.10", "port": 3306, "admin_user": "afpadmin", "admin_secret_id": "ocid1.vaultsecret.oc1..admin"},
        "image_prefix_base": "iad.ocir.io/ns/afp",
        "projects": projects
        if projects is not None
        else [
            {"name": "hello", "domain": "hello.example.com", "secret_id": "ocid1.vaultsecret.oc1..hello", "manual_secret_ids": {}},
            {"name": "app-a", "domain": "app-a.example.net", "secret_id": "ocid1.vaultsecret.oc1..appa",
             "manual_secret_ids": {"API_KEY": "ocid1.vaultsecret.oc1..apikey"}},
        ],
    }


def b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


class World:
    def __init__(self, afp: dict[str, Any] | None = None) -> None:
        self.objects: dict[str, str] = {"afp.json": json.dumps(afp if afp is not None else afp_json())}
        self.secrets = {
            "ocid1.vaultsecret.oc1..admin": ADMIN_PASSWORD,
            "ocid1.vaultsecret.oc1..hello": json.dumps({"AFP_DB_PASSWORD": DB_PASSWORD}),
            "ocid1.vaultsecret.oc1..appa": json.dumps({"AFP_DB_PASSWORD": DB_PASSWORD, "SIGNING_KEY": SIGNING_KEY}),
            "ocid1.vaultsecret.oc1..apikey": API_KEY,
        }
        self.running: dict[str, str] = {}  # compose project -> tag
        self.broken: set[str] = set()
        self.calls: list[dict[str, Any]] = []

    def release(self, project: str, tag: str) -> None:
        self.objects[f"releases/{project}/{tag}/compose.afp.yaml"] = f"# {project} {tag}\n"

    def state(self, project: str) -> dict[str, Any] | None:
        text = self.objects.get(f"state/{project}.json")
        return json.loads(text) if text else None

    # Runner interface ------------------------------------------------------

    def run(self, args: list[str], *, stdin: str | None = None, env: dict[str, str] | None = None,
            check: bool = True, quiet: bool = False, secret_output: bool = False,
            stdout_path: Path | None = None) -> subprocess.CompletedProcess[str]:
        args = list(args)
        self.calls.append({"args": args, "stdin": stdin, "env": env, "secret_output": secret_output})
        code, out, err = self._answer(args, env or {}, stdout_path)
        if check and code != 0:
            raise AfpError(f"{args[0]} {args[1]} failed ({code}): {err}")
        return subprocess.CompletedProcess(args, code, out, err)

    def _answer(self, args: list[str], env: dict[str, str], stdout_path: Path | None) -> tuple[int, str, str]:
        line = " ".join(args)
        if args[0] == "oci":
            if "os object get" in line:
                name = args[args.index("--name") + 1]
                if name in self.objects:
                    return 0, self.objects[name], ""
                return 1, "", 'ServiceError: {"code": "ObjectNotFound", "status": 404}'
            if "os object put" in line:
                name = args[args.index("--name") + 1]
                data = Path(args[args.index("--file") + 1]).read_bytes()
                self.objects[name] = data.decode() if not name.endswith(".gz") else "<gzip>"
                return 0, "", ""
            if "secret-bundle get" in line:
                return 0, b64(self.secrets[args[args.index("--secret-id") + 1]]), ""
            if "raw-request" in line:
                return 0, json.dumps({"data": {"token": "tok", "expires_in": 3600}}), ""
        if args[:2] == ["docker", "compose"]:
            project = args[args.index("-p") + 1] if "-p" in args else None
            if "ls" in args:
                return 0, json.dumps([{"Name": n} for n in sorted(self.running)]), ""
            if "pull" in args:
                return 0, "", ""
            if "up" in args:
                if project == "afp-caddy":
                    return 0, "", ""
                tag = env["AFP_TAG"]
                self.running[project] = tag
                if tag in self.broken:
                    return 1, "", f"container {project}-web-1 is unhealthy"
                return 0, "", ""
            if "down" in args:
                self.running.pop(project, None)
                return 0, "", ""
            if "ps" in args:
                return 0, ("abc123\n" if project in self.running else ""), ""
            return 0, "", ""  # exec caddy reload
        if args[:2] == ["docker", "run"] and "mysqldump" in args:
            assert stdout_path is not None
            stdout_path.write_text("-- dump\n")
            return 0, "", ""
        if args[0] == "docker":
            return 0, "", ""  # run mysql, login, network
        return 9, "", f"unexpected command: {line}"


def make_ctx(tmp_path: Path, world: Any) -> cli.Context:
    paths = cli.Paths(code=ROOT, caddy_dir=tmp_path / "caddy", run_dir=tmp_path / "run", log_dir=tmp_path / "log",
                      projects_dir=tmp_path / "projects", work_dir=tmp_path / "work")
    log = Log(paths.log_dir / "test.log", echo=io.StringIO())
    return cli.Context(paths=paths, log=log, runner=world, oci=Oci(world, REGION))  # type: ignore[arg-type]
