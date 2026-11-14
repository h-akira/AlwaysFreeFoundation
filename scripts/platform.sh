#!/usr/bin/env bash
# Point the VM at a tag of the platform code and bring it up to it.
#
# Usage: platform.sh TAG
#   1. Looks the tag up on the public repository (platform_repository in
#      terraform.tfvars.json); it must have been pushed.
#   2. Writes {"tag", "commit"} to platform.json in the bucket.
#   3. Runs afp-bootstrap on the VM through Run Command and waits for it: the
#      VM fetches that commit, then runs afp install and afp sync.
#
# Environment:
#   AFP_CONFIG_DIR  Directory holding terraform.tfvars.json (required).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY=(python3 "$ROOT/scripts/rm_values.py")
# shellcheck source=SCRIPTDIR/lib.sh
source "$ROOT/scripts/lib.sh"

die() { echo "platform.sh: $*" >&2; exit 1; }
usage() { sed -n '2,/^[^#]/p' "$0" | sed '$d' >&2; exit 2; }

[[ $# -eq 1 && -n "$1" ]] || usage
TAG="$1"
[[ "$TAG" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || die "invalid tag: $TAG"

: "${AFP_CONFIG_DIR:?AFP_CONFIG_DIR is not set}"
TFVARS="$AFP_CONFIG_DIR/terraform.tfvars.json"
[[ -f "$TFVARS" ]] || die "$TFVARS not found"
REGION="$("${PY[@]}" get "$TFVARS" region)"
REPOSITORY="$("${PY[@]}" get "$TFVARS" platform_repository)"
oci_() { oci --region "$REGION" "$@"; }

# The commit the tag names on GitHub; for an annotated tag, the peeled line
# (^{}) is the commit, the other one is the tag object.
refs="$(git ls-remote --tags "$REPOSITORY" "refs/tags/$TAG" "refs/tags/$TAG^{}")" \
  || die "cannot read tags from $REPOSITORY"
commit="$(printf '%s\n' "$refs" | awk -v t="refs/tags/$TAG^{}" '$2 == t {print $1}')"
[[ -n "$commit" ]] || commit="$(printf '%s\n' "$refs" | awk -v t="refs/tags/$TAG" '$2 == t {print $1}')"
[[ "$commit" =~ ^[0-9a-f]{40}$ ]] || die "tag $TAG not found on $REPOSITORY; push it first"

local_commit="$(git -C "$ROOT" rev-parse -q --verify "refs/tags/$TAG^{commit}" || true)"
if [[ -n "$local_commit" && "$local_commit" != "$commit" ]]; then
  die "tag $TAG is $local_commit here but $commit on $REPOSITORY"
fi

load_outputs
BUCKET="$(out bucket)"
printf '{"tag":"%s","commit":"%s"}\n' "$TAG" "$commit" \
  | oci_ os object put -bn "$BUCKET" --name platform.json --file - \
      --content-type application/json --force > /dev/null \
  || die "cannot write platform.json"
echo "platform.json: $TAG ($commit)"

exec "$ROOT/scripts/run-command.sh" send --wait "sudo -n /usr/local/sbin/afp-bootstrap"
