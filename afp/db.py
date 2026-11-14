"""Project databases and users on the shared MySQL HeatWave DB system.

The mysql client runs in the official mysql container of mysql/VERSION, so
the VM needs no client package. Passwords go through the environment
(MYSQL_PWD) and stdin, never through arguments.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from afp.config import Db, Project
from afp.errors import AfpError
from afp.runner import Runner

CHARSET = "utf8mb4"
COLLATION = "utf8mb4_ja_0900_as_cs_ks"
# What Terraform generates (ADR 011); also safe inside a quoted SQL string.
PASSWORD = re.compile(r"^[A-Za-z0-9._~-]{8,128}$")


def mysql_image(code_dir: Path) -> str:
    version = (code_dir / "mysql" / "VERSION").read_text().strip()
    return f"mysql:{version}"


def project_password(secret_json: str, project: str) -> str:
    try:
        value = json.loads(secret_json).get("AFP_DB_PASSWORD")
    except (ValueError, AttributeError):
        value = None
    if not isinstance(value, str) or not PASSWORD.match(value):
        raise AfpError(f"the secret of project {project} has no valid AFP_DB_PASSWORD")
    return value


def project_sql(project: Project, password: str) -> str:
    """Create the project's database and user, or bring them in line.

    With partial_revokes on, "_" in the database name is taken literally.
    """
    if not PASSWORD.match(password):
        raise AfpError(f"invalid DB password for project {project.name}")
    db = project.db_name
    user = f"'{db}'@'%'"
    return "\n".join(
        [
            f"CREATE DATABASE IF NOT EXISTS `{db}` CHARACTER SET {CHARSET} COLLATE {COLLATION};",
            f"CREATE USER IF NOT EXISTS {user} IDENTIFIED BY '{password}';",
            f"ALTER USER {user} IDENTIFIED BY '{password}';",
            f"GRANT ALL ON `{db}`.* TO {user};",
            "",
        ]
    )


def run_sql(runner: Runner, image: str, db: Db, admin_password: str, sql: str) -> None:
    runner.run(
        [
            "docker", "run", "--rm", "-i", "-e", "MYSQL_PWD", image,
            "mysql", "-h", db.host, "-P", str(db.port), "-u", db.admin_user, "--batch",
        ],
        stdin=sql,
        env={"MYSQL_PWD": admin_password},
    )
