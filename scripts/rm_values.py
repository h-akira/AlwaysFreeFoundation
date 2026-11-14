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
  execution                  Read a Run Command execution (oci instance-agent
                             command-execution get) from stdin; print
                             "STATE EXIT_CODE" and then the output text.
  command-content SCRIPT     Print the --content of a Run Command for SCRIPT
                             (wrapped to return only the end of its output).
  build-services PREFIX      Read `docker compose config --format json` from
                             stdin; print "SERVICE REPOSITORY" for each service
                             with build:, whose image must be PREFIX/<name>:<tag>.
  json-get KEY               Print one top-level value of the JSON on stdin.
  has-project NAME           Read afp.json on stdin; fail unless NAME is listed.
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


def execution_result(execution: dict[str, Any]) -> tuple[str, str, str]:
    """State, exit code ("-" if none yet) and output text of an execution."""
    data = execution.get("data", execution)
    content = data.get("content") or {}
    code = content.get("exit-code")
    return str(data.get("lifecycle-state")), "-" if code is None else str(code), content.get("text") or ""


# Run Command returns about 1 KB of the output, cut at its start (measured
# 2026-11-14, although the documentation says the last 1 KB). The script is
# wrapped so that only its end, where afp prints its summary, comes back.
OUTPUT_TAIL_BYTES = 900


def wrap_script(script: str) -> str:
    """POSIX sh: run SCRIPT, print the end of its output, keep its exit code."""
    return (
        f"out=$( {{ {script}\n}} 2>&1 ); rc=$?\n"
        f"printf '%s\\n' \"$out\" | tail -c {OUTPUT_TAIL_BYTES}\n"
        "exit $rc\n"
    )


def command_content(script: str) -> dict[str, Any]:
    return {"source": {"sourceType": "TEXT", "text": wrap_script(script)}, "output": {"outputType": "TEXT"}}


def build_services(config: dict[str, Any], prefix: str) -> list[tuple[str, str]]:
    """Services that make deploy builds, with their OCIR repository names.

    prefix is AFP_IMAGE_PREFIX, e.g. nrt.ocir.io/<namespace>/afp/<project>;
    the repository is the image path after the namespace, without the tag
    (afp/<project>/<name>).
    """
    result: list[tuple[str, str]] = []
    for name, service in sorted((config.get("services") or {}).items()):
        if "build" not in service:
            continue
        image = service.get("image") or ""
        path, _, tag = image.rpartition(":")
        if not image.startswith(prefix + "/") or not tag or "/" in tag:
            raise ValueError(f"service {name}: image must be ${{AFP_IMAGE_PREFIX}}/<name>:${{AFP_TAG}}, not {image!r}")
        repository = path.split("/", 2)[2]  # drop the registry host and the namespace
        result.append((name, repository))
    if not result:
        raise ValueError("no service has build:; nothing to build")
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
    elif len(argv) == 1 and argv[0] == "execution":
        state, code, text = execution_result(json.load(sys.stdin))
        print(f"{state} {code}")
        print(text, end="" if text.endswith("\n") or not text else "\n")
    elif len(argv) == 2 and argv[0] == "command-content":
        print(json.dumps(command_content(argv[1])))
    elif len(argv) == 2 and argv[0] == "build-services":
        for name, repository in build_services(json.load(sys.stdin), argv[1]):
            print(f"{name} {repository}")
    elif len(argv) == 2 and argv[0] == "json-get":
        value = json.load(sys.stdin).get(argv[1])
        if value is None:
            print(f"{argv[1]} is not set", file=sys.stderr)
            return 1
        print(value if isinstance(value, str) else json.dumps(value))
    elif len(argv) == 2 and argv[0] == "has-project":
        names = [p.get("name") for p in json.load(sys.stdin).get("projects") or []]
        if argv[1] not in names:
            print(f"project {argv[1]} is not in afp.json (listed: {', '.join(names) or 'none'})", file=sys.stderr)
            return 1
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
