#!/usr/bin/env bash
# Deploy a project from this machine, roll it back, or dump its DB.
#
# Usage: project.sh deploy PROJECT DIR
#        project.sh rollback PROJECT
#        project.sh backup [PROJECT]
#   deploy    DIR is the project's repository with compose.afp.yaml. Its HEAD
#             must be clean and carry exactly one tag, which becomes the
#             version. Builds the services with build: for the VM's CPU type
#             (stack output vm_arch), pushes them to OCIR (creating the
#             repositories afp/<project>/<service> when missing), puts
#             compose.afp.yaml into the bucket, and runs afp deploy on the VM
#             through Run Command, waiting for it.
#   rollback  Runs afp rollback on the VM (previous version; the DB stays).
#   backup    Runs afp backup on the VM (dumps to the bucket).
#   On failure, the end of the full log is fetched from the bucket.
#
# Environment:
#   AFP_CONFIG_DIR  Directory holding terraform.tfvars.json (required).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY=(python3 "$ROOT/scripts/rm_values.py")
# shellcheck source=SCRIPTDIR/lib.sh
source "$ROOT/scripts/lib.sh"

die() { echo "project.sh: $*" >&2; exit 1; }
usage() { sed -n '2,/^[^#]/p' "$0" | sed '$d' >&2; exit 2; }

# Same rules as afp (afp/config.py, afp/project.py); checked here too because
# the names end up in the script that Run Command runs on the VM.
PROJECT_RE='^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$'
TAG_RE='^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$'
AFP="sudo -n /opt/afp/current/bin/afp"

: "${AFP_CONFIG_DIR:?AFP_CONFIG_DIR is not set}"
TFVARS="$AFP_CONFIG_DIR/terraform.tfvars.json"
[[ -f "$TFVARS" ]] || die "$TFVARS not found"
REGION="$("${PY[@]}" get "$TFVARS" region)"
oci_() { oci --region "$REGION" "$@" < /dev/null; }

check_project() {
  [[ "$1" =~ $PROJECT_RE ]] || die "invalid project name: $1"
}

afp_json() {
  oci_ os object get -bn "$BUCKET" --name afp.json --file - 2> /dev/null || die "cannot read afp.json from the bucket"
}

# Run afp on the VM; on failure show the end of the full log from the bucket.
run_afp() {
  local out rc=0 log
  out="$("$ROOT/scripts/run-command.sh" send --wait "$AFP $*")" || rc=$?
  printf '%s\n' "$out"
  if (( rc != 0 )); then
    log="$(printf '%s\n' "$out" | sed -n "s/^log: bucket $BUCKET: //p" | tail -1)"
    if [[ -n "$log" ]]; then
      echo "--- end of $log ---"
      oci_ os object get -bn "$BUCKET" --name "$log" --file - 2> /dev/null | tail -n 40 || true
    fi
  fi
  return "$rc"
}

ensure_repository() {
  local compartment="$1" name="$2" count
  count="$(oci_ artifacts container repository list --compartment-id "$compartment" \
    --display-name "$name" --query 'length(data.items)' --raw-output)" || die "cannot list OCIR repositories"
  if [[ "$count" == "0" ]]; then
    echo "Creating OCIR repository $name ..."
    oci_ artifacts container repository create --compartment-id "$compartment" \
      --display-name "$name" --is-public false > /dev/null || die "cannot create repository $name"
  fi
}

cmd_deploy() {
  [[ $# -eq 2 ]] || usage
  local project="$1" dir="$2" compose tag tags arch compartment prefix registry token services repo name
  check_project "$project"
  dir="$(cd "$dir" && pwd)" || die "no such directory: $2"
  compose="$dir/compose.afp.yaml"
  [[ -f "$compose" ]] || die "$compose not found"
  [[ -z "$(git -C "$dir" status --porcelain)" ]] || die "$dir has uncommitted changes"
  tags="$(git -C "$dir" tag --points-at HEAD)"
  [[ -n "$tags" ]] || die "HEAD of $dir has no tag; tag the version to deploy"
  [[ "$(printf '%s\n' "$tags" | wc -l | tr -d ' ')" == "1" ]] || die "HEAD of $dir has several tags: $(echo $tags)"
  tag="$tags"
  [[ "$tag" =~ $TAG_RE ]] || die "tag $tag cannot be a Docker tag"

  load_outputs
  BUCKET="$(out bucket)"
  arch="$(out vm_arch)"
  compartment="$(out compartment_id)"
  local afp
  afp="$(afp_json)"
  printf '%s' "$afp" | "${PY[@]}" has-project "$project" || exit 1
  prefix="$(printf '%s' "$afp" | "${PY[@]}" json-get image_prefix_base)/$project"
  registry="${prefix%%/*}"

  # Values that the build needs; the platform's other values (docs/04_using.md
  # §3) are set empty so that compose does not warn about them.
  export AFP_DOMAIN="" AFP_DB_HOST="" AFP_DB_PORT="" AFP_DB_NAME="" AFP_DB_USER="" AFP_DB_PASSWORD=""
  export AFP_IMAGE_PREFIX="$prefix" AFP_TAG="$tag" AFP_PROJECT="$project"
  services="$(docker compose -f "$compose" config --format json \
    | "${PY[@]}" build-services "$prefix")" || die "cannot read the services to build from $compose"

  while read -r _ repo; do ensure_repository "$compartment" "$repo"; done <<< "$services"

  echo "Logging in to $registry ..."
  token="$(oci_ raw-request --http-method GET --target-uri "https://$registry/20180419/docker/token" \
    | "${PY[@]}" json-get data | python3 -c 'import json, sys; print(json.load(sys.stdin)["token"])')" \
    || die "cannot get an OCIR token (is the OCI CLI session valid?)"
  printf '%s' "$token" | docker login "$registry" -u BEARER_TOKEN --password-stdin > /dev/null \
    || die "docker login to $registry failed"

  local names=()
  while read -r name _; do names+=("$name"); done <<< "$services"
  echo "Building ${names[*]} for linux/$arch at $tag ..."
  DOCKER_DEFAULT_PLATFORM="linux/$arch" docker compose -f "$compose" build "${names[@]}"
  docker compose -f "$compose" push "${names[@]}"

  oci_ os object put -bn "$BUCKET" --name "releases/$project/$tag/compose.afp.yaml" \
    --file "$compose" --content-type application/yaml --force > /dev/null \
    || die "cannot put the release into the bucket"
  echo "Released $project $tag; deploying on the VM ..."
  run_afp deploy "$project" "$tag"
}

cmd_rollback() {
  [[ $# -eq 1 ]] || usage
  check_project "$1"
  load_outputs
  BUCKET="$(out bucket)"
  run_afp rollback "$1"
}

cmd_backup() {
  [[ $# -le 1 ]] || usage
  [[ $# -eq 0 ]] || check_project "$1"
  load_outputs
  BUCKET="$(out bucket)"
  run_afp backup "$@"
}

case "${1:-}" in
  deploy) shift; cmd_deploy "$@" ;;
  rollback) shift; cmd_rollback "$@" ;;
  backup) shift; cmd_backup "$@" ;;
  *) usage ;;
esac
