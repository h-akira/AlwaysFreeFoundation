"""Tests for scripts/vm-ssh.sh that do not touch OCI (a fake `oci` is put on PATH)."""

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "vm-ssh.sh"


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    config = tmp_path / "config"
    config.mkdir()
    (config / "terraform.tfvars.json").write_text(
        json.dumps({"tenancy_ocid": "ocid1.tenancy.oc1..xxxx", "region": "us-ashburn-1"})
    )
    key = tmp_path / "key"
    key.write_text("private")
    (tmp_path / "key.pub").write_text("ssh-ed25519 AAAA test")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "oci"
    # Fails like an expired session; records its arguments.
    fake.write_text(f'#!/bin/sh\necho "$@" >> "{tmp_path}/oci.log"\necho "NotAuthenticated" >&2\nexit 1\n')
    fake.chmod(0o755)
    result = dict(os.environ)
    result["AFP_CONFIG_DIR"] = str(config)
    result["AFP_SSH_KEY"] = str(key)
    result["PATH"] = f"{bin_dir}{os.pathsep}{result['PATH']}"
    return result


def run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)


def test_missing_key_pair_stops_before_oci(env: dict[str, str], tmp_path: Path) -> None:
    env["AFP_SSH_KEY"] = str(tmp_path / "nope")
    result = run(env)
    assert result.returncode == 1
    assert "ssh key pair not found" in result.stderr
    assert not (tmp_path / "oci.log").exists()


def test_cli_failure_stops_without_a_session(env: dict[str, str], tmp_path: Path) -> None:
    result = run(env)
    assert result.returncode == 1
    assert "cannot read the stack outputs" in result.stderr
    assert "session" not in (tmp_path / "oci.log").read_text()
