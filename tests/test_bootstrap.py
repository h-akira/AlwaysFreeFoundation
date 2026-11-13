"""Static checks of the VM bootstrap that runs from cloud-init."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOOTSTRAP = ROOT / "terraform" / "modules" / "compute" / "afp-bootstrap.sh"


def test_bootstrap_parses() -> None:
    subprocess.run(["bash", "-n", str(BOOTSTRAP)], check=True)


def test_bucket_name_matches_terraform() -> None:
    main_tf = (ROOT / "terraform" / "main" / "main.tf").read_text()
    assert 'bucket_name = "afp"' in main_tf
    assert 'BUCKET="afp"' in BOOTSTRAP.read_text()
