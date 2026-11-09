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


def test_rm_provided_keys_are_dropped() -> None:
    tfvars = {"tenancy_ocid": "ocid1.tenancy.oc1..xxxx", "region": "us-ashburn-1", "x": "y"}
    assert rm_values.to_rm_variables(tfvars) == {"x": "y"}


def test_null_is_rejected() -> None:
    with pytest.raises(ValueError):
        rm_values.to_rm_variables({"x": None})


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
    assert json.loads(variables.stdout) == {"home_cidrs": '["192.0.2.10/32"]'}
