"""Tests for scripts/stack.sh that do not touch OCI (a fake `oci` is put on PATH)."""

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "stack.sh"


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    config = tmp_path / "config"
    config.mkdir()
    (config / "terraform.tfvars.json").write_text(
        json.dumps({"tenancy_ocid": "ocid1.tenancy.oc1..xxxx", "region": "us-ashburn-1"})
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "oci"
    # Fails like an expired session; records its arguments.
    fake.write_text(f'#!/bin/sh\necho "$@" >> "{tmp_path}/oci.log"\necho "NotAuthenticated" >&2\nexit 1\n')
    fake.chmod(0o755)
    result = dict(os.environ)
    result["AFP_CONFIG_DIR"] = str(config)
    result["PATH"] = f"{bin_dir}{os.pathsep}{result['PATH']}"
    return result


def run(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True)


def test_usage_on_bad_arguments(env: dict[str, str]) -> None:
    for args in ([], ["nope"], ["main"], ["main", "nope"]):
        result = run(args, env)
        assert result.returncode == 2, args
        assert "Usage: stack.sh base|main" in result.stderr
        assert "set -euo" not in result.stderr


def test_base_destroy_is_refused_before_anything(env: dict[str, str]) -> None:
    env.pop("AFP_CONFIG_DIR")
    result = run(["base", "destroy"], env)
    assert result.returncode == 1
    assert "never destroyed" in result.stderr


def test_cli_failure_is_not_taken_as_missing_stack(env: dict[str, str], tmp_path: Path) -> None:
    result = run(["main", "outputs"], env)
    assert result.returncode != 0
    assert "cannot list stacks" in result.stderr
    assert "stack not found" not in result.stderr
    log = (tmp_path / "oci.log").read_text()
    assert "--display-name afp " in log
