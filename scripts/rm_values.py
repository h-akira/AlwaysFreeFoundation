#!/usr/bin/env python3
"""Value conversion helpers for scripts/*.sh (Python standard library only).

Subcommands:
  variables TFVARS_JSON [KEYS]
                             Print Resource Manager stack variables as JSON.
                             KEYS (comma separated) limits them to those keys,
                             which must all be set.
  get TFVARS_JSON KEY        Print one top-level value from the tfvars file.
  outputs                    Read a Terraform state from stdin and print
                             outputs as KEY=VALUE lines.
"""

from __future__ import annotations

import json
import sys
from typing import Any


def to_rm_variables(tfvars: dict[str, Any]) -> dict[str, str]:
    """Convert tfvars values to Resource Manager variables (strings only).

    Strings stay as they are; everything else (lists, maps, numbers, booleans)
    becomes JSON text, which Terraform parses for complex-typed variables.
    """
    result: dict[str, str] = {}
    for key, value in tfvars.items():
        if value is None:
            raise ValueError(f"variable {key!r} is null; remove it to use the default")
        result[key] = value if isinstance(value, str) else json.dumps(value, separators=(",", ":"))
    return result


def select_keys(tfvars: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    """Keep only the given keys; each must be present."""
    missing = [key for key in keys if key not in tfvars]
    if missing:
        raise ValueError(f"not set: {', '.join(missing)}")
    return {key: tfvars[key] for key in keys}


def state_outputs(state: dict[str, Any]) -> dict[str, str]:
    """Extract outputs from a Terraform state as strings."""
    result: dict[str, str] = {}
    for key, output in state.get("outputs", {}).items():
        if output.get("sensitive"):
            continue
        value = output.get("value")
        result[key] = value if isinstance(value, str) else json.dumps(value)
    return result


def _load_json(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top level must be an object")
    return data


def main(argv: list[str]) -> int:
    if len(argv) in (2, 3) and argv[0] == "variables":
        tfvars = _load_json(argv[1])
        if len(argv) == 3:
            tfvars = select_keys(tfvars, [key for key in argv[2].split(",") if key])
        print(json.dumps(to_rm_variables(tfvars)))
    elif len(argv) == 3 and argv[0] == "get":
        value = _load_json(argv[1]).get(argv[2])
        if value is None:
            print(f"{argv[1]}: {argv[2]} is not set", file=sys.stderr)
            return 1
        print(value if isinstance(value, str) else json.dumps(value))
    elif len(argv) == 1 and argv[0] == "outputs":
        for key, value in state_outputs(json.load(sys.stdin)).items():
            print(f"{key}={value}")
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except ValueError as e:
        print(f"rm_values.py: {e}", file=sys.stderr)
        sys.exit(1)
