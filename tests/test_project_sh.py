"""Tests for scripts/project.sh with a fake `oci` and `docker` on PATH
(no OCI and no Docker are touched)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "project.sh"
PREFIX_BASE = "nrt.ocir.io/ns/afp"

FAKE_OCI = r'''
import json, os, sys
from pathlib import Path
d = Path(os.environ["FAKE_DIR"])
args = sys.argv[1:]
with open(d / "oci.log", "a") as f:
    f.write(json.dumps(args) + "\n")
line = " ".join(args)
def arg(name):
    return args[args.index(name) + 1]
if "stack list" in line:
    print("ocid1.ormstack.oc1..stack")
elif "get-stack-tf-state" in line:
    print(json.dumps({"outputs": {k: {"value": v} for k, v in {
        "vm_id": "ocid1.instance.oc1..vm", "compartment_id": "ocid1.compartment.oc1..c",
        "bucket": "afp", "vm_arch": "arm64",
    }.items()}}))
elif "os object get" in line:
    name = arg("--name")
    if name == "afp.json":
        print(json.dumps({"image_prefix_base": "PREFIX_BASE", "projects": [{"name": "hello"}]}))
    elif name.startswith("logs/"):
        print("full log line 1\nfull log line 2")
    else:
        sys.exit("ObjectNotFound")
elif "repository list" in line:
    print("1" if arg("--display-name") in os.environ.get("FAKE_REPOS", "").split(",") else "0")
elif "repository create" in line:
    pass
elif "raw-request" in line:
    print(json.dumps({"data": {"token": "tok"}, "status": "200 OK"}))
elif "os object put" in line:
    (d / "release.yaml").write_text(Path(arg("--file")).read_text())
    (d / "put-name").write_text(arg("--name"))
elif "command create" in line:
    (d / "content.json").write_text(arg("--content"))
    print("ocid1.instanceagentcommand.oc1..cmd")
elif "command-execution get" in line:
    state = os.environ.get("FAKE_STATE", "SUCCEEDED")
    code = 0 if state == "SUCCEEDED" else 1
    text = "afp deploy: OK\nlog: bucket afp: logs/x-deploy-hello.log\n"
    print(json.dumps({"data": {"lifecycle-state": state, "content": {"exit-code": code, "text": text}}}))
else:
    sys.exit("fake oci: unexpected " + line)
'''.replace("PREFIX_BASE", PREFIX_BASE)

FAKE_DOCKER = r'''
import json, os, sys
from pathlib import Path
d = Path(os.environ["FAKE_DIR"])
args = sys.argv[1:]
with open(d / "docker.log", "a") as f:
    f.write(json.dumps({"args": args, "platform": os.environ.get("DOCKER_DEFAULT_PLATFORM"),
                        "tag": os.environ.get("AFP_TAG"), "prefix": os.environ.get("AFP_IMAGE_PREFIX")}) + "\n")
if args[:1] == ["login"]:
    sys.stdin.read()
elif "config" in args:
    prefix, tag = os.environ["AFP_IMAGE_PREFIX"], os.environ["AFP_TAG"]
    print(json.dumps({"services": {
        "web": {"build": {"context": "."}, "image": f"{prefix}/web:{tag}"},
        "redis": {"image": "redis:7"},
    }}))
'''


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    config = tmp_path / "config"
    config.mkdir()
    (config / "terraform.tfvars.json").write_text(json.dumps({"tenancy_ocid": "ocid1.tenancy.oc1..xxxx", "region": "us-ashburn-1"}))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in [("oci", FAKE_OCI), ("docker", FAKE_DOCKER)]:
        (bin_dir / name).write_text(f"#!{sys.executable}\n{body}")
        (bin_dir / name).chmod(0o755)
    result = dict(os.environ)
    result.update({"AFP_CONFIG_DIR": str(config), "FAKE_DIR": str(tmp_path), "AFP_POLL_SECONDS": "0",
                   "PATH": f"{bin_dir}{os.pathsep}{result['PATH']}"})
    return result


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "hello"
    path.mkdir()
    (path / "compose.afp.yaml").write_text("services: {}\n")
    git(path, "init", "-q")
    git(path, "add", "compose.afp.yaml")
    git(path, "commit", "-q", "-m", "a")
    git(path, "tag", "v1")
    return path


def git(path: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(path), "-c", "user.name=t", "-c", "user.email=t@example.com", *args], check=True)


def run(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL)


def calls(tmp_path: Path, name: str) -> list:
    path = tmp_path / f"{name}.log"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_deploy(env: dict[str, str], repo: Path, tmp_path: Path) -> None:
    result = run(["deploy", "hello", str(repo)], env)
    assert result.returncode == 0, result.stderr
    assert "afp deploy: OK" in result.stdout

    oci = calls(tmp_path, "oci")
    [create] = [c for c in oci if "repository" in c and "create" in c]
    assert create[create.index("--display-name") + 1] == "afp/hello/web"
    assert create[create.index("--compartment-id") + 1] == "ocid1.compartment.oc1..c"

    docker = calls(tmp_path, "docker")
    [build] = [c for c in docker if "build" in c["args"]]
    assert build["args"][-1:] == ["web"]  # only the services with build:
    assert build["platform"] == "linux/arm64"  # the VM's CPU type
    assert (build["tag"], build["prefix"]) == ("v1", f"{PREFIX_BASE}/hello")
    [push] = [c for c in docker if "push" in c["args"]]
    assert push["args"][-1:] == ["web"]
    [login] = [c for c in docker if c["args"][:1] == ["login"]]
    assert login["args"] == ["login", "nrt.ocir.io", "-u", "BEARER_TOKEN", "--password-stdin"]

    assert (tmp_path / "put-name").read_text() == "releases/hello/v1/compose.afp.yaml"
    assert (tmp_path / "release.yaml").read_text() == "services: {}\n"
    text = json.loads((tmp_path / "content.json").read_text())["source"]["text"]
    assert "{ sudo -n /opt/afp/current/bin/afp deploy hello v1\n}" in text


def test_deploy_keeps_an_existing_repository(env: dict[str, str], repo: Path, tmp_path: Path) -> None:
    env["FAKE_REPOS"] = "afp/hello/web"
    assert run(["deploy", "hello", str(repo)], env).returncode == 0
    assert not any("create" in c and "repository" in c for c in calls(tmp_path, "oci"))


def test_deploy_failure_shows_the_end_of_the_log(env: dict[str, str], repo: Path) -> None:
    env["FAKE_STATE"] = "FAILED"
    result = run(["deploy", "hello", str(repo)], env)
    assert result.returncode == 1
    assert "--- end of logs/x-deploy-hello.log ---" in result.stdout
    assert "full log line 2" in result.stdout


def test_deploy_refuses_a_dirty_tree(env: dict[str, str], repo: Path, tmp_path: Path) -> None:
    (repo / "new.txt").write_text("x")
    result = run(["deploy", "hello", str(repo)], env)
    assert result.returncode == 1 and "uncommitted changes" in result.stderr
    assert not calls(tmp_path, "docker")


def test_deploy_refuses_untagged_and_doubly_tagged_heads(env: dict[str, str], repo: Path) -> None:
    git(repo, "commit", "-q", "--allow-empty", "-m", "b")
    assert "has no tag" in run(["deploy", "hello", str(repo)], env).stderr
    git(repo, "tag", "v2")
    git(repo, "tag", "v2b")
    assert "several tags" in run(["deploy", "hello", str(repo)], env).stderr


def test_deploy_refuses_unknown_projects(env: dict[str, str], repo: Path, tmp_path: Path) -> None:
    result = run(["deploy", "other", str(repo)], env)
    assert result.returncode == 1 and "not in afp.json" in result.stderr
    assert not calls(tmp_path, "docker")


@pytest.mark.parametrize("args", [["rollback", "x;reboot"], ["backup", "Hello"], ["deploy", "a b", "."]])
def test_bad_project_names_never_reach_the_vm(env: dict[str, str], tmp_path: Path, args: list[str]) -> None:
    result = run(args, env)
    assert result.returncode == 1 and "invalid project name" in result.stderr
    assert not (tmp_path / "content.json").exists()


def test_rollback_and_backup(env: dict[str, str], tmp_path: Path) -> None:
    assert run(["rollback", "hello"], env).returncode == 0
    assert "afp rollback hello\n}" in json.loads((tmp_path / "content.json").read_text())["source"]["text"]
    assert run(["backup"], env).returncode == 0
    assert "afp backup\n}" in json.loads((tmp_path / "content.json").read_text())["source"]["text"]
