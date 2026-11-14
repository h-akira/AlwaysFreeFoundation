"""OCI through the OCI CLI, authenticated as the VM (instance principal)."""

from __future__ import annotations

import base64
import json
import re
import urllib.request
from pathlib import Path

from afp.errors import AfpError
from afp.runner import Runner

METADATA = "http://169.254.169.254/opc/v2"
# The CLI's error for a missing object: it tries head_object first and prints
# "code": null with "status": 404 (measured 2026-11-14), not "ObjectNotFound".
NOT_FOUND = re.compile(r'"status":\s*404\b')


def metadata_region() -> str:
    request = urllib.request.Request(
        f"{METADATA}/instance/canonicalRegionName", headers={"Authorization": "Bearer Oracle"}
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.read().decode().strip()
    except OSError as e:
        raise AfpError(f"cannot read the region from the instance metadata: {e}") from e


class Oci:
    def __init__(self, runner: Runner, region: str, namespace: str | None = None) -> None:
        self.runner = runner
        self.region = region
        # Known once afp.json is read; saves the CLI a lookup per call.
        self.namespace = namespace

    def _cmd(self, *args: str) -> list[str]:
        return ["oci", "--auth", "instance_principal", "--region", self.region, *args]

    def _ns(self) -> list[str]:
        return ["-ns", self.namespace] if self.namespace else []

    def get_object(self, bucket: str, name: str) -> str:
        result = self.runner.run(
            self._cmd("os", "object", "get", *self._ns(), "-bn", bucket, "--name", name, "--file", "-"),
            check=False,
        )
        if result.returncode != 0:
            raise AfpError(f"cannot read {name} from bucket {bucket}: {result.stderr.strip()[-300:]}")
        return result.stdout

    def get_object_or_none(self, bucket: str, name: str) -> str | None:
        """Like get_object, but None when the object does not exist."""
        result = self.runner.run(
            self._cmd("os", "object", "get", *self._ns(), "-bn", bucket, "--name", name, "--file", "-"),
            check=False,
        )
        if result.returncode == 0:
            return result.stdout
        if NOT_FOUND.search(result.stderr):
            return None
        raise AfpError(f"cannot read {name} from bucket {bucket}: {result.stderr.strip()[-300:]}")

    def put_object(self, bucket: str, name: str, path: Path, content_type: str, quiet: bool = False) -> None:
        self.runner.run(
            self._cmd(
                "os", "object", "put", *self._ns(), "-bn", bucket, "--name", name,
                "--file", str(path), "--content-type", content_type, "--force",
            ),
            quiet=quiet,
        )

    def secret(self, secret_id: str) -> str:
        """Current value of a secret (stored as base64 text)."""
        result = self.runner.run(
            self._cmd(
                "secrets", "secret-bundle", "get", "--secret-id", secret_id,
                "--query", 'data."secret-bundle-content".content', "--raw-output",
            ),
            secret_output=True,
        )
        try:
            return base64.b64decode(result.stdout.strip(), validate=True).decode()
        except ValueError as e:
            raise AfpError(f"secret {secret_id} is not base64 text") from e

    def registry_token(self, registry: str) -> str:
        """Short-lived (1 hour) OCIR token for docker login -u BEARER_TOKEN."""
        result = self.runner.run(
            self._cmd("raw-request", "--http-method", "GET", "--target-uri", f"https://{registry}/20180419/docker/token"),
            secret_output=True,
        )
        try:
            token = json.loads(result.stdout)["data"]["token"]
        except (ValueError, KeyError, TypeError) as e:
            raise AfpError(f"no token in the answer of {registry}") from e
        if not isinstance(token, str) or not token:
            raise AfpError(f"no token in the answer of {registry}")
        return token
