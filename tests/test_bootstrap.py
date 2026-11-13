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


def _image_regex() -> str:
    import re

    main_tf = (ROOT / "terraform" / "modules" / "compute" / "main.tf").read_text()
    match = re.search(r'values = \["(\^Oracle-Linux-9[^"]+)"\]', main_tf)
    assert match, "image name filter not found"
    return match.group(1).replace("\\\\", "\\")


def test_image_filter_takes_both_cpu_types_only() -> None:
    import re

    regex = re.compile(_image_regex())
    assert regex.match("Oracle-Linux-9.8-2026.10.30-0")
    assert regex.match("Oracle-Linux-9.8-aarch64-2026.10.30-0")
    assert not regex.match("Oracle-Linux-9.8-Gen2-GPU-2026.10.30-0")
    assert not regex.match("Oracle-Linux-9.8-Minimal-2026.10.30-0")
