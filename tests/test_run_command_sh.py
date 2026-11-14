"""Tests for scripts/run-command.sh, platform.sh and the bucket step of
stack.sh destroy, with a fake `oci` on PATH (no OCI is touched)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"

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
        "vm_id": "ocid1.instance.oc1..vm", "compartment_id": "ocid1.compartment.oc1..c", "bucket": "afp",
    }.items()}}))
elif "command create" in line:
    (d / "content.json").write_text(arg("--content"))
    print("ocid1.instanceagentcommand.oc1..cmd")
elif "command-execution get" in line:
    states = json.loads((d / "states.json").read_text())
    n = int((d / "n").read_text()) if (d / "n").exists() else 0
    (d / "n").write_text(str(n + 1))
    state, code, text = states[min(n, len(states) - 1)]
    content = {"text": text} if code is None else {"exit-code": code, "text": text}
    print(json.dumps({"data": {"lifecycle-state": state, "content": content}}))
elif "os object put" in line:
    (d / "put.json").write_text(sys.stdin.read())
elif "os bucket get" in line:
    sys.exit(int(os.environ.get("FAKE_BUCKET_MISSING", "0")))
elif "bulk-delete" in line:
    pass
elif "job create-destroy-job" in line:
    print("ocid1.ormjob.oc1..job")
elif "job get-job-logs-content" in line:
    print("log")
elif "job get" in line:
    print("SUCCEEDED")
else:
    print("fake oci: unexpected " + line, file=sys.stderr)
    sys.exit(9)
'''


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    config = tmp_path / "config"
    config.mkdir()
    repo = tmp_path / "repo"
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com"]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "a"], check=True)
    subprocess.run([*git, "tag", "-a", "v0.1.0", "-m", "v0.1.0"], check=True)
    subprocess.run([*git, "tag", "light"], check=True)
    (config / "terraform.tfvars.json").write_text(json.dumps({
        "tenancy_ocid": "ocid1.tenancy.oc1..xxxx", "region": "us-ashburn-1", "platform_repository": str(repo),
    }))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "oci").write_text(f"#!{sys.executable}\n{FAKE_OCI}")
    (bin_dir / "oci").chmod(0o755)
    (tmp_path / "states.json").write_text(json.dumps([["ACCEPTED", None, ""], ["SUCCEEDED", 0, "afp sync: OK\n"]]))
    result = dict(os.environ)
    result.update({
        "AFP_CONFIG_DIR": str(config), "FAKE_DIR": str(tmp_path), "AFP_POLL_SECONDS": "0",
        "PATH": f"{bin_dir}{os.pathsep}{result['PATH']}",
    })
    return result


def run(script: str, args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(SCRIPTS / script), *args], env=env, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL)


def commit_of(env: dict[str, str], ref: str) -> str:
    repo = json.loads(Path(env["AFP_CONFIG_DIR"], "terraform.tfvars.json").read_text())["platform_repository"]
    return subprocess.run(["git", "-C", repo, "rev-parse", ref], capture_output=True, text=True, check=True).stdout.strip()


def test_send_without_wait_prints_how_to_check(env: dict[str, str], tmp_path: Path) -> None:
    result = run("run-command.sh", ["send", "echo hi"], env)
    assert result.returncode == 0, result.stderr
    assert "make command-result ID=ocid1.instanceagentcommand.oc1..cmd" in result.stdout
    content = json.loads((tmp_path / "content.json").read_text())
    assert content["source"] == {"sourceType": "TEXT", "text": "echo hi"}
    calls = [json.loads(line) for line in (tmp_path / "oci.log").read_text().splitlines()]
    assert not any("command-execution" in c for c in calls)
    [create] = [c for c in calls if "create" in c and "instance-agent" in c]
    assert json.loads(create[create.index("--target") + 1]) == {"instanceId": "ocid1.instance.oc1..vm"}
    assert create[create.index("--compartment-id") + 1] == "ocid1.compartment.oc1..c"


def test_send_and_wait_returns_the_output(env: dict[str, str]) -> None:
    result = run("run-command.sh", ["send", "--wait", "echo hi"], env)
    assert result.returncode == 0, result.stderr
    assert "Run Command: SUCCEEDED (exit code 0)" in result.stdout
    assert result.stdout.rstrip().endswith("afp sync: OK")


def test_failed_command_passes_its_exit_code(env: dict[str, str], tmp_path: Path) -> None:
    (tmp_path / "states.json").write_text(json.dumps([["IN_PROGRESS", None, ""], ["FAILED", 3, "boom\n"]]))
    result = run("run-command.sh", ["result", "ocid1.instanceagentcommand.oc1..cmd", "--wait"], env)
    assert result.returncode == 3
    assert "FAILED (exit code 3)" in result.stdout


def test_timed_out_command_fails(env: dict[str, str], tmp_path: Path) -> None:
    (tmp_path / "states.json").write_text(json.dumps([["TIMED_OUT", None, ""]]))
    result = run("run-command.sh", ["result", "ocid1.instanceagentcommand.oc1..cmd", "--wait"], env)
    assert result.returncode == 1


def test_platform_writes_the_peeled_commit(env: dict[str, str], tmp_path: Path) -> None:
    result = run("platform.sh", ["v0.1.0"], env)
    assert result.returncode == 0, result.stderr
    put = json.loads((tmp_path / "put.json").read_text())
    # The annotated tag's commit, not the tag object.
    assert put == {"tag": "v0.1.0", "commit": commit_of(env, "v0.1.0^{commit}")}
    content = json.loads((tmp_path / "content.json").read_text())
    assert content["source"]["text"] == "sudo -n /usr/local/sbin/afp-bootstrap"
    assert "SUCCEEDED" in result.stdout


def test_platform_takes_a_lightweight_tag(env: dict[str, str], tmp_path: Path) -> None:
    assert run("platform.sh", ["light"], env).returncode == 0
    assert json.loads((tmp_path / "put.json").read_text())["commit"] == commit_of(env, "light")


def test_platform_refuses_unknown_and_bad_tags(env: dict[str, str], tmp_path: Path) -> None:
    result = run("platform.sh", ["v9.9.9"], env)
    assert result.returncode == 1 and "push it first" in result.stderr
    result = run("platform.sh", ["x;echo"], env)
    assert result.returncode == 1 and "invalid tag" in result.stderr
    assert not (tmp_path / "put.json").exists()


def test_destroy_empties_the_bucket_but_afp_json(env: dict[str, str], tmp_path: Path) -> None:
    env["AFP_CONFIRM_DESTROY"] = "afp"
    result = run("stack.sh", ["main", "destroy"], env)
    assert result.returncode == 0, result.stderr
    calls = [json.loads(line) for line in (tmp_path / "oci.log").read_text().splitlines()]
    [bulk] = [c for c in calls if "bulk-delete" in c]
    assert bulk[bulk.index("--bucket-name") + 1] == "afp"
    assert bulk[bulk.index("--exclude") + 1] == "afp.json"
    # Emptied before the destroy job is created.
    kinds = [i for i, c in enumerate(calls) if "bulk-delete" in c or "create-destroy-job" in c]
    assert "bulk-delete" in calls[kinds[0]]


def test_destroy_goes_on_without_the_bucket(env: dict[str, str], tmp_path: Path) -> None:
    env["AFP_CONFIRM_DESTROY"] = "afp"
    env["FAKE_BUCKET_MISSING"] = "1"
    result = run("stack.sh", ["main", "destroy"], env)
    assert result.returncode == 0, result.stderr
    assert "not found; nothing to empty" in result.stdout
    assert "bulk-delete" not in (tmp_path / "oci.log").read_text()
