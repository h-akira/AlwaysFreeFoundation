"""Unit tests for afp/ (no OCI, no docker: commands go to a fake runner)."""

from __future__ import annotations

import argparse
import json
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from afp import caddy, cli, config, db  # noqa: E402
from afp.errors import AfpError  # noqa: E402
from afp.lock import Lock  # noqa: E402
from afp.log import truncate  # noqa: E402
from afp.oci import Oci  # noqa: E402

from afp_world import ADMIN_PASSWORD, DB_PASSWORD, afp_json  # noqa: E402


# --- config ---------------------------------------------------------------


def test_parse_afp_json() -> None:
    cfg = config.parse(json.dumps(afp_json()))
    assert cfg.namespace == "ns"
    assert cfg.db.port == 3306
    assert [p.name for p in cfg.projects] == ["hello", "app-a"]
    assert cfg.projects[1].db_name == "app_a"
    assert cfg.projects[1].manual_secret_ids == {"API_KEY": "ocid1.vaultsecret.oc1..apikey"}


def test_parse_without_projects() -> None:
    data = afp_json()
    del data["projects"]
    assert config.parse(json.dumps(data)).projects == []


@pytest.mark.parametrize(
    "project",
    [
        {"name": "afp-x", "domain": "x.example.com", "secret_id": "s"},
        {"name": "caddy", "domain": "x.example.com", "secret_id": "s"},
        {"name": "Hello", "domain": "x.example.com", "secret_id": "s"},
        {"name": "x`;drop", "domain": "x.example.com", "secret_id": "s"},
        {"name": "x", "domain": "x.example.com {\n}", "secret_id": "s"},
        {"name": "x", "domain": "x.example.com", "secret_id": ""},
        {"name": "x", "domain": "x.example.com", "secret_id": "s", "manual_secret_ids": {"AFP_X": "s"}},
    ],
)
def test_parse_rejects_bad_projects(project: dict[str, Any]) -> None:
    with pytest.raises(AfpError):
        config.parse(json.dumps(afp_json([project])))


def test_parse_rejects_duplicates() -> None:
    a = {"name": "a-b", "domain": "a.example.com", "secret_id": "s"}
    b = {"name": "a-b", "domain": "b.example.com", "secret_id": "s"}
    with pytest.raises(AfpError):
        config.parse(json.dumps(afp_json([a, b])))


def test_parse_rejects_non_json() -> None:
    with pytest.raises(AfpError):
        config.parse("{")


# --- db -------------------------------------------------------------------


def test_project_sql() -> None:
    project = config.Project(name="app-a", domain="a.example.com", secret_id="s")
    sql = db.project_sql(project, DB_PASSWORD)
    assert "CREATE DATABASE IF NOT EXISTS `app_a` CHARACTER SET utf8mb4 COLLATE utf8mb4_ja_0900_as_cs_ks;" in sql
    assert f"CREATE USER IF NOT EXISTS 'app_a'@'%' IDENTIFIED BY '{DB_PASSWORD}';" in sql
    assert f"ALTER USER 'app_a'@'%' IDENTIFIED BY '{DB_PASSWORD}';" in sql
    assert "GRANT ALL ON `app_a`.* TO 'app_a'@'%';" in sql


@pytest.mark.parametrize("password", ["short", "has'quote-12345", "back\\slash12345", ""])
def test_project_sql_rejects_unsafe_passwords(password: str) -> None:
    with pytest.raises(AfpError):
        db.project_sql(config.Project(name="a", domain="a.example.com", secret_id="s"), password)


def test_project_password() -> None:
    assert db.project_password(json.dumps({"AFP_DB_PASSWORD": DB_PASSWORD, "X": "y"}), "a") == DB_PASSWORD
    for bad in ["{}", "[]", "nope", json.dumps({"AFP_DB_PASSWORD": "x'y"})]:
        with pytest.raises(AfpError):
            db.project_password(bad, "a")


def test_mysql_image_follows_version_file() -> None:
    version = (ROOT / "mysql" / "VERSION").read_text().strip()
    assert db.mysql_image(ROOT) == f"mysql:{version}"


# --- caddy ----------------------------------------------------------------


def test_render_caddyfile() -> None:
    cfg = config.parse(json.dumps(afp_json()))
    text = caddy.render(cfg.projects)
    assert "app-a.example.net {\n\treverse_proxy app-a:8080\n}" in text
    assert "hello.example.com {\n\treverse_proxy hello:8080\n}" in text
    # Sorted by domain, so the file does not change with the list order.
    assert text == caddy.render(list(reversed(cfg.projects)))


def test_write_if_changed(tmp_path: Path) -> None:
    path = tmp_path / "Caddyfile"
    assert caddy.write_if_changed(path, "a")
    assert not caddy.write_if_changed(path, "a")
    assert caddy.write_if_changed(path, "b")
    assert path.read_text() == "b"
    assert not (tmp_path / "Caddyfile.tmp").exists()


def test_caddy_compose_mounts_the_directory() -> None:
    compose = (ROOT / "caddy" / "compose.yaml").read_text()
    assert "- /opt/afp/caddy:/etc/caddy:ro" in compose
    assert str(cli.Paths(code=ROOT).caddy_dir) == "/opt/afp/caddy"
    assert "external: true" in compose
    assert "mem_limit:" in compose


# --- log and lock ---------------------------------------------------------


def test_truncate() -> None:
    assert truncate("abc", 10) == "abc"
    assert truncate("x" * 20, 10) == "xxxxxxx..."


def test_lock_times_out_while_held(tmp_path: Path) -> None:
    path = tmp_path / "run" / "lock"
    with Lock(path, timeout=1):
        result: list[str] = []

        def other() -> None:
            # flock is per open file, so a second open in this process conflicts too.
            try:
                with Lock(path, timeout=0.3, poll=0.1):
                    result.append("got")
            except AfpError:
                result.append("timeout")

        t = threading.Thread(target=other)
        t.start()
        t.join()
        assert result == ["timeout"]
    with Lock(path, timeout=0.3):
        pass


# --- commands on a fake VM (tests/afp_world.py) --------------------------

from afp_world import World, b64, make_ctx  # noqa: E402

NO_ARGS = argparse.Namespace()


def test_sync(tmp_path: Path) -> None:
    world = World()
    ctx = make_ctx(tmp_path, world)
    summary = cli.cmd_sync(ctx, NO_ARGS)
    assert summary == "projects: hello, app-a; Caddyfile updated"
    assert ctx.oci is not None and ctx.oci.namespace == "ns"

    secret_calls = [c for c in world.calls if "secret-bundle" in c["args"]]
    assert secret_calls and all(c["secret_output"] for c in secret_calls)

    [mysql] = [c for c in world.calls if c["args"][:2] == ["docker", "run"]]
    assert "mysql:" + (ROOT / "mysql" / "VERSION").read_text().strip() in mysql["args"]
    assert ["-h", "10.0.1.10", "-P", "3306", "-u", "afpadmin"] == mysql["args"][-7:-1]
    # Passwords only in the environment and stdin, never in the arguments.
    assert mysql["env"] == {"MYSQL_PWD": ADMIN_PASSWORD}
    assert ADMIN_PASSWORD not in " ".join(mysql["args"]) and DB_PASSWORD not in " ".join(mysql["args"])
    assert "`hello`" in mysql["stdin"] and "`app_a`" in mysql["stdin"]

    assert (tmp_path / "caddy" / "Caddyfile").read_text() == caddy.render(config.parse(json.dumps(afp_json())).projects)
    docker = [c["args"] for c in world.calls if c["args"][:4] == ["docker", "compose", "-p", "afp-caddy"]]
    assert docker[0][-3:] == ["up", "-d", "--remove-orphans"]
    assert docker[1][6:11] == ["exec", "-T", "caddy", "caddy", "reload"]

    # Second run: same file, still reloaded (a failed reload is retried).
    world.calls.clear()
    assert cli.cmd_sync(ctx, NO_ARGS).endswith("Caddyfile unchanged")
    assert any("reload" in c["args"] for c in world.calls)


def test_sync_without_projects_skips_the_db(tmp_path: Path) -> None:
    world = World(afp_json([]))
    cli.cmd_sync(make_ctx(tmp_path, world), NO_ARGS)
    assert not any("secret-bundle" in c["args"] for c in world.calls)
    assert not any(c["args"][:2] == ["docker", "run"] for c in world.calls)


def test_sync_secrets_never_reach_the_log(tmp_path: Path) -> None:
    from afp.runner import Runner

    # The real Runner, with a fake oci/docker on PATH.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    answers = {
        "afp.json": json.dumps(afp_json()),
        "..admin": b64(ADMIN_PASSWORD),
        "..hello": b64(json.dumps({"AFP_DB_PASSWORD": DB_PASSWORD})),
        "..appa": b64(json.dumps({"AFP_DB_PASSWORD": DB_PASSWORD})),
    }
    (tmp_path / "answers.json").write_text(json.dumps(answers))
    (bin_dir / "oci").write_text(
        f"#!{sys.executable}\nimport json, sys\n"
        f"answers = json.load(open({str(tmp_path / 'answers.json')!r}))\n"
        "args = ' '.join(sys.argv)\n"
        "if 'state/' in args:\n"
        "    sys.exit('ServiceError: ObjectNotFound')\n"
        "print(next(v for k, v in answers.items() if k in args))\n"
    )
    (bin_dir / "docker").write_text(
        '#!/bin/sh\ncat > /dev/null\ncase "$*" in *" ls "*) echo "[]" ;; *) echo docker ok ;; esac\n'
    )
    for f in bin_dir.iterdir():
        f.chmod(0o755)
    monkey = pytest.MonkeyPatch()
    monkey.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    try:
        ctx = make_ctx(tmp_path, None)
        ctx.runner = Runner(ctx.log)
        ctx.oci = Oci(ctx.runner, "us-ashburn-1")
        cli.cmd_sync(ctx, NO_ARGS)
    finally:
        monkey.undo()
    ctx.log.close()
    text = ctx.log.path.read_text()
    assert "docker ok" in text
    for value in [ADMIN_PASSWORD, DB_PASSWORD, b64(ADMIN_PASSWORD)]:
        assert value not in text


class NetworkMissing(World):
    def _answer(self, args, env, stdout_path):  # type: ignore[no-untyped-def]
        if args[:3] == ["docker", "network", "inspect"]:
            return 1, "", "no such network"
        return super()._answer(args, env, stdout_path)


def test_install_creates_the_network_once(tmp_path: Path) -> None:
    world = NetworkMissing()
    cli.cmd_install(make_ctx(tmp_path, world), NO_ARGS)
    assert ["docker", "network", "create", "afp"] in [c["args"] for c in world.calls]
    world = World()
    cli.cmd_install(make_ctx(tmp_path, world), NO_ARGS)
    assert not any(c["args"][:3] == ["docker", "network", "create"] for c in world.calls)
    assert (tmp_path / "caddy").is_dir()


def paths_in(tmp_path: Path) -> cli.Paths:
    return cli.Paths(code=ROOT, caddy_dir=tmp_path / "caddy", run_dir=tmp_path / "run", log_dir=tmp_path / "log",
                     projects_dir=tmp_path / "projects", work_dir=tmp_path / "work")


def test_main_prints_a_short_summary_last(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(ctx: cli.Context, args: argparse.Namespace) -> str:
        raise AfpError("x" * 5000)

    monkeypatch.setitem(cli.COMMANDS, "sync", cli.Command(boom, "h", upload_log=True))
    assert cli.main(["sync"], paths=paths_in(tmp_path)) == 1
    out = capsys.readouterr().out
    assert out.startswith("afp sync: FAILED: xxx")
    assert len(out.encode()) <= 1024
    assert out.splitlines()[-1].startswith("log: ")
    # No OCI client was made, so the log stays on the VM.
    assert list((tmp_path / "log").iterdir())


def test_main_names_the_log_after_the_project(tmp_path: Path, capsys: pytest.CaptureFixture[str],
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(cli.COMMANDS, "backup", cli.Command(lambda ctx, args: "ok", "h", upload_log=False,
                                                            arguments=(("project", "?"),)))
    assert cli.main(["backup", "hello"], paths=paths_in(tmp_path)) == 0
    assert capsys.readouterr().out.splitlines()[-1].endswith("-backup-hello.log")


def test_bucket_name_matches_terraform() -> None:
    assert 'bucket_name = "afp"' in (ROOT / "terraform" / "main" / "main.tf").read_text()
    assert config.BUCKET == "afp"


def test_main_uploads_the_log_with_the_real_runner(tmp_path: Path, capsys: pytest.CaptureFixture[str],
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    """The upload runs after the log is closed; it must not write into it."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "oci").write_text(f'#!/bin/sh\necho "$@" >> "{tmp_path}/oci.log"\n')
    (bin_dir / "oci").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")

    def work(ctx: cli.Context, args: argparse.Namespace) -> str:
        ctx.oci = Oci(ctx.runner, "us-ashburn-1", namespace="ns")
        ctx.runner.run(["oci", "something"])
        return "done"

    monkeypatch.setitem(cli.COMMANDS, "sync", cli.Command(work, "h", upload_log=True))
    assert cli.main(["sync"], paths=paths_in(tmp_path)) == 0
    out = capsys.readouterr().out
    assert out.startswith("afp sync: OK: done\nlog: bucket afp: logs/")
    assert "os object put -ns ns -bn afp --name logs/" in (tmp_path / "oci.log").read_text()
    assert not list((tmp_path / "log").iterdir())  # removed once uploaded


def test_main_reports_a_failed_upload(tmp_path: Path, capsys: pytest.CaptureFixture[str],
                                      monkeypatch: pytest.MonkeyPatch) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "oci").write_text("#!/bin/sh\nexit 1\n")
    (bin_dir / "oci").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")

    def work(ctx: cli.Context, args: argparse.Namespace) -> str:
        ctx.oci = Oci(ctx.runner, "us-ashburn-1", namespace="ns")
        return "done"

    monkeypatch.setitem(cli.COMMANDS, "sync", cli.Command(work, "h", upload_log=True))
    assert cli.main(["sync"], paths=paths_in(tmp_path)) == 0
    assert "(upload failed: AfpError)" in capsys.readouterr().out
    assert list((tmp_path / "log").iterdir())
