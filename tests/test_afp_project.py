"""Tests for afp deploy / rollback / backup and the project part of sync,
on the fake VM of tests/afp_world.py."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest
from afp_world import API_KEY, DB_PASSWORD, SIGNING_KEY, World, make_ctx

from afp import cli
from afp import project as pm
from afp.errors import AfpError


def deploy(world: World, tmp_path: Path, project: str, tag: str) -> str:
    world.release(project, tag)
    return cli.cmd_deploy(make_ctx(tmp_path, world), argparse.Namespace(project=project, tag=tag))


def test_first_deploy(tmp_path: Path) -> None:
    world = World()
    summary = deploy(world, tmp_path, "hello", "v1")
    assert summary.startswith("hello is now v1 (previous: none); dump before it: dumps/hello/")
    assert world.running == {"hello": "v1"}
    assert world.state("hello") == {"current": "v1", "previous": None}
    assert any(k.startswith("dumps/hello/") and k.endswith("-before-v1.sql.gz") for k in world.objects)


def test_values_go_through_the_environment(tmp_path: Path) -> None:
    world = World()
    deploy(world, tmp_path, "app-a", "v1")
    [up] = [c for c in world.calls if c["args"][:4] == ["docker", "compose", "-p", "app-a"] and "up" in c["args"]]
    assert up["env"] == {
        "AFP_IMAGE_PREFIX": "iad.ocir.io/ns/afp/app-a",
        "AFP_TAG": "v1",
        "AFP_PROJECT": "app-a",
        "AFP_DOMAIN": "app-a.example.net",
        "AFP_DB_HOST": "10.0.1.10",
        "AFP_DB_PORT": "3306",
        "AFP_DB_NAME": "app_a",
        "AFP_DB_USER": "app_a",
        "AFP_DB_PASSWORD": DB_PASSWORD,
        "SIGNING_KEY": SIGNING_KEY,
        "API_KEY": API_KEY,  # quotes and $ pass as they are; no env file to escape
    }
    assert "--no-build" in up["args"] and "--wait" in up["args"]
    for call in world.calls:
        joined = " ".join(call["args"])
        assert DB_PASSWORD not in joined and API_KEY not in joined and SIGNING_KEY not in joined
    # docker login reads the token from stdin.
    [login] = [c for c in world.calls if c["args"][:2] == ["docker", "login"]]
    assert login["args"][2:5] == ["iad.ocir.io", "-u", "BEARER_TOKEN"] and login["stdin"] == "tok"


def test_second_deploy_keeps_the_previous(tmp_path: Path) -> None:
    world = World()
    deploy(world, tmp_path, "hello", "v1")
    assert "(previous: v1)" in deploy(world, tmp_path, "hello", "v2")
    assert world.state("hello") == {"current": "v2", "previous": "v1"}
    # The same tag again does not lose the previous one.
    deploy(world, tmp_path, "hello", "v2")
    assert world.state("hello") == {"current": "v2", "previous": "v1"}


def test_broken_deploy_goes_back(tmp_path: Path) -> None:
    world = World()
    deploy(world, tmp_path, "hello", "v1")
    world.broken.add("v2")
    with pytest.raises(AfpError, match=r"deploy of hello v2 failed: .*unhealthy.* -- back on v1"):
        deploy(world, tmp_path, "hello", "v2")
    assert world.running == {"hello": "v1"}
    assert world.state("hello") == {"current": "v1", "previous": None}


def test_broken_first_deploy_stops(tmp_path: Path) -> None:
    world = World()
    world.broken.add("v1")
    with pytest.raises(AfpError, match="stopped \\(no previous version\\)"):
        deploy(world, tmp_path, "hello", "v1")
    assert world.running == {}
    assert world.state("hello") is None


def test_missing_release_changes_nothing(tmp_path: Path) -> None:
    world = World()
    with pytest.raises(AfpError, match="no release releases/hello/v9/compose.afp.yaml"):
        cli.cmd_deploy(make_ctx(tmp_path, world), argparse.Namespace(project="hello", tag="v9"))
    assert not any(k.startswith("dumps/") for k in world.objects)
    assert world.running == {}


@pytest.mark.parametrize("tag", ["", "-x", "a/b", "a b", "x" * 129])
def test_bad_tags_are_refused(tmp_path: Path, tag: str) -> None:
    with pytest.raises(AfpError, match="invalid tag"):
        cli.cmd_deploy(make_ctx(tmp_path, World()), argparse.Namespace(project="hello", tag=tag))


def test_unknown_project_is_refused(tmp_path: Path) -> None:
    with pytest.raises(AfpError, match="not in afp.json"):
        cli.cmd_deploy(make_ctx(tmp_path, World()), argparse.Namespace(project="nope", tag="v1"))


def test_rollback_swaps_current_and_previous(tmp_path: Path) -> None:
    world = World()
    deploy(world, tmp_path, "hello", "v1")
    deploy(world, tmp_path, "hello", "v2")
    summary = cli.cmd_rollback(make_ctx(tmp_path, world), argparse.Namespace(project="hello"))
    assert summary.startswith("hello is now v1 (previous: v2)")
    assert "the DB is not rolled back" in summary
    assert world.running == {"hello": "v1"}


def test_rollback_without_previous(tmp_path: Path) -> None:
    world = World()
    deploy(world, tmp_path, "hello", "v1")
    with pytest.raises(AfpError, match="no previous version"):
        cli.cmd_rollback(make_ctx(tmp_path, world), argparse.Namespace(project="hello"))


def test_backup_all_and_one(tmp_path: Path) -> None:
    world = World()
    summary = cli.cmd_backup(make_ctx(tmp_path, world), argparse.Namespace(project=None))
    assert summary.count("dumps/") == 2
    dumps = [c for c in world.calls if "mysqldump" in c["args"]]
    assert [d["args"][d["args"].index("--databases") + 1] for d in dumps] == ["hello", "app_a"]
    assert all(d["env"] == {"MYSQL_PWD": "Admin-Pass_1"} for d in dumps)
    assert not list((tmp_path / "work").iterdir())  # temporary files removed
    world.calls.clear()
    cli.cmd_backup(make_ctx(tmp_path, world), argparse.Namespace(project="hello"))
    assert len([c for c in world.calls if "mysqldump" in c["args"]]) == 1


def test_sync_starts_what_should_run_and_stops_what_is_gone(tmp_path: Path) -> None:
    world = World()
    deploy(world, tmp_path, "hello", "v1")
    world.running = {"old-app": "v3"}  # a reboot (nothing up), and a project removed from the list
    summary = cli.cmd_sync(make_ctx(tmp_path, world), argparse.Namespace())
    assert summary.endswith("; started: hello; stopped: old-app")
    assert world.running == {"hello": "v1"}
    # Nothing to do the second time.
    assert cli.cmd_sync(make_ctx(tmp_path, world), argparse.Namespace()).endswith("Caddyfile unchanged")


def test_sync_reports_a_project_that_cannot_start(tmp_path: Path) -> None:
    world = World()
    deploy(world, tmp_path, "hello", "v1")
    deploy(world, tmp_path, "app-a", "v1")
    world.running = {}
    world.broken.add("v1")
    with pytest.raises(AfpError, match="could not start hello: .*; app-a: "):
        cli.cmd_sync(make_ctx(tmp_path, world), argparse.Namespace())


def test_next_state() -> None:
    assert pm.next_state({"current": None, "previous": None}, "v1") == {"current": "v1", "previous": None}
    assert pm.next_state({"current": "v1", "previous": None}, "v2") == {"current": "v2", "previous": "v1"}
    assert pm.next_state({"current": "v2", "previous": "v1"}, "v2") == {"current": "v2", "previous": "v1"}


def test_example_follows_the_contract() -> None:
    """examples/hello/compose.afp.yaml keeps the four promises of docs/04_using.md §2."""
    root = Path(__file__).resolve().parent.parent
    text = (root / "examples" / "hello" / "compose.afp.yaml").read_text()
    assert "image: ${AFP_IMAGE_PREFIX}/web:${AFP_TAG}" in text
    assert 'aliases: ["${AFP_PROJECT}"]' in text and "external: true" in text
    assert "healthcheck:" in text and "mem_limit:" in text
    assert "8080" in (root / "examples" / "hello" / "app.py").read_text()
