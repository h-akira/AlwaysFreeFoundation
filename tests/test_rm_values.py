import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import rm_values  # noqa: E402

SCRIPT = Path(rm_values.__file__)


def test_strings_stay_and_others_become_json() -> None:
    tfvars = {
        "home_cidrs": ["192.0.2.10/32", "198.51.100.0/24"],
        "db_admin_username": "afpadmin",
        "availability_domain_index": 1,
        "flag": True,
    }
    assert rm_values.to_rm_variables(tfvars) == {
        "home_cidrs": '["192.0.2.10/32","198.51.100.0/24"]',
        "db_admin_username": "afpadmin",
        "availability_domain_index": "1",
        "flag": "true",
    }


def test_tenancy_and_region_are_passed() -> None:
    # Stacks created from the CLI do not get these from Resource Manager.
    tfvars = {"tenancy_ocid": "ocid1.tenancy.oc1..xxxx", "region": "us-ashburn-1"}
    assert rm_values.to_rm_variables(tfvars) == tfvars


def test_null_is_rejected() -> None:
    with pytest.raises(ValueError):
        rm_values.to_rm_variables({"x": None})


def test_select_keys_keeps_only_given_keys() -> None:
    tfvars = {"tenancy_ocid": "ocid1.tenancy.oc1..xxxx", "region": "us-ashburn-1", "home_cidrs": ["192.0.2.10/32"]}
    assert rm_values.select_keys(tfvars, ["tenancy_ocid", "region"]) == {
        "tenancy_ocid": "ocid1.tenancy.oc1..xxxx",
        "region": "us-ashburn-1",
    }


def test_select_keys_rejects_missing() -> None:
    with pytest.raises(ValueError, match="region"):
        rm_values.select_keys({"tenancy_ocid": "ocid1.tenancy.oc1..xxxx"}, ["tenancy_ocid", "region"])


def test_state_outputs_skips_sensitive() -> None:
    state = {
        "outputs": {
            "db_ip": {"value": "10.0.1.5", "type": "string"},
            "db_port": {"value": 3306, "type": "number"},
            "secret": {"value": "s3cr3t", "type": "string", "sensitive": True},
        }
    }
    assert rm_values.state_outputs(state) == {"db_ip": "10.0.1.5", "db_port": "3306"}


def test_cli_get_and_variables(tmp_path: Path) -> None:
    path = tmp_path / "terraform.tfvars.json"
    path.write_text(json.dumps({"region": "us-ashburn-1", "home_cidrs": ["192.0.2.10/32"]}))

    got = subprocess.run([sys.executable, SCRIPT, "get", path, "region"], capture_output=True, text=True, check=True)
    assert got.stdout.strip() == "us-ashburn-1"

    missing = subprocess.run([sys.executable, SCRIPT, "get", path, "nope"], capture_output=True, text=True)
    assert missing.returncode == 1

    variables = subprocess.run([sys.executable, SCRIPT, "variables", path], capture_output=True, text=True, check=True)
    assert json.loads(variables.stdout) == {"region": "us-ashburn-1", "home_cidrs": '["192.0.2.10/32"]'}


def test_cli_variables_with_keys(tmp_path: Path) -> None:
    path = tmp_path / "terraform.tfvars.json"
    path.write_text(json.dumps({"region": "us-ashburn-1", "home_cidrs": ["192.0.2.10/32"]}))

    only = subprocess.run(
        [sys.executable, SCRIPT, "variables", path, "region"], capture_output=True, text=True, check=True
    )
    assert json.loads(only.stdout) == {"region": "us-ashburn-1"}

    missing = subprocess.run([sys.executable, SCRIPT, "variables", path, "region,tenancy_ocid"], capture_output=True, text=True)
    assert missing.returncode == 1
    assert "not set: tenancy_ocid" in missing.stderr
    assert "Traceback" not in missing.stderr

    # An empty key list selects nothing.
    empty = subprocess.run([sys.executable, SCRIPT, "variables", path, ","], capture_output=True, text=True, check=True)
    assert json.loads(empty.stdout) == {}


def test_execution_result() -> None:
    done = {"data": {"lifecycle-state": "FAILED", "content": {"exit-code": 3, "text": "boom"}}}
    assert rm_values.execution_result(done) == ("FAILED", "3", "boom")
    waiting = {"data": {"lifecycle-state": "ACCEPTED", "content": None}}
    assert rm_values.execution_result(waiting) == ("ACCEPTED", "-", "")


def test_command_content_keeps_the_end_and_the_exit_code() -> None:
    script = "seq 1 2000; echo \"done $((1+1))\" 'x'; exit 3"
    out = subprocess.run([sys.executable, str(SCRIPT), "command-content", script],
                         capture_output=True, text=True, check=True).stdout
    text = json.loads(out)["source"]["text"]
    result = subprocess.run(["sh", "-c", text], capture_output=True, text=True)
    assert result.returncode == 3
    assert result.stdout.endswith("2000\ndone 2 x\n")
    assert len(result.stdout.encode()) <= rm_values.OUTPUT_TAIL_BYTES


def test_wrapped_script_passes_success() -> None:
    result = subprocess.run(["sh", "-c", rm_values.wrap_script("echo ok >&2")], capture_output=True, text=True)
    assert (result.returncode, result.stdout) == (0, "ok\n")
