"""afp.json, written to the bucket by Terraform (terraform/main/main.tf).

Names are checked again here because they end up in SQL, the Caddyfile and
docker compose project names.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from afp.errors import AfpError

# Must match the bucket name in terraform/main/main.tf.
BUCKET = "afp"

PROJECT_NAME = re.compile(r"^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$")
DOMAIN = re.compile(r"^([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$")
SECRET_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
HOST = re.compile(r"^[A-Za-z0-9.-]+$")


@dataclass(frozen=True)
class Project:
    name: str
    domain: str
    secret_id: str
    manual_secret_ids: dict[str, str] = field(default_factory=dict)

    @property
    def db_name(self) -> str:
        """Also the DB user name."""
        return self.name.replace("-", "_")


@dataclass(frozen=True)
class Db:
    host: str
    port: int
    admin_user: str
    admin_secret_id: str


@dataclass(frozen=True)
class Config:
    region: str
    namespace: str
    bucket: str
    platform_repository: str
    db: Db
    image_prefix_base: str
    projects: list[Project]


def _str(data: dict[str, Any], key: str, where: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise AfpError(f"afp.json: {where}{key} must be a non-empty string")
    return value


def _project(data: Any, index: int) -> Project:
    where = f"projects[{index}]."
    if not isinstance(data, dict):
        raise AfpError(f"afp.json: projects[{index}] must be an object")
    name = _str(data, "name", where)
    if not PROJECT_NAME.match(name) or name.startswith("afp") or name == "caddy":
        raise AfpError(f"afp.json: invalid project name {name!r}")
    domain = _str(data, "domain", where)
    if not DOMAIN.match(domain):
        raise AfpError(f"afp.json: invalid domain {domain!r} of project {name}")
    manual = data.get("manual_secret_ids") or {}
    if not isinstance(manual, dict) or not all(
        isinstance(k, str) and SECRET_NAME.match(k) and not k.startswith("AFP_") and isinstance(v, str)
        for k, v in manual.items()
    ):
        raise AfpError(f"afp.json: invalid manual_secret_ids of project {name}")
    return Project(name=name, domain=domain, secret_id=_str(data, "secret_id", where), manual_secret_ids=dict(manual))


def parse(text: str) -> Config:
    try:
        data = json.loads(text)
    except ValueError as e:
        raise AfpError(f"afp.json is not JSON: {e}") from e
    if not isinstance(data, dict):
        raise AfpError("afp.json: top level must be an object")
    db = data.get("db")
    if not isinstance(db, dict):
        raise AfpError("afp.json: db must be an object")
    host = _str(db, "host", "db.")
    port = db.get("port")
    if not HOST.match(host) or not isinstance(port, int):
        raise AfpError("afp.json: invalid db.host or db.port")
    projects_data = data.get("projects") or []
    if not isinstance(projects_data, list):
        raise AfpError("afp.json: projects must be a list")
    projects = [_project(p, i) for i, p in enumerate(projects_data)]
    if len({p.db_name for p in projects}) != len(projects) or len({p.domain for p in projects}) != len(projects):
        raise AfpError("afp.json: project names and domains must be unique")
    return Config(
        region=_str(data, "region", ""),
        namespace=_str(data, "namespace", ""),
        bucket=_str(data, "bucket", ""),
        platform_repository=_str(data, "platform_repository", ""),
        db=Db(host=host, port=port, admin_user=_str(db, "admin_user", "db."), admin_secret_id=_str(db, "admin_secret_id", "db.")),
        image_prefix_base=_str(data, "image_prefix_base", ""),
        projects=projects,
    )
