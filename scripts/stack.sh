#!/usr/bin/env bash
# Send plan/apply jobs for terraform/ to OCI Resource Manager.
#
# Usage: stack.sh base|main plan|apply|destroy|outputs
#   base     Stack "afp-base" (terraform/base): what destroy cannot remove.
#   main     Stack "afp" (terraform/main): everything else.
#
#   plan     Upload terraform/ at HEAD and the variables, then run a plan job.
#   apply    Apply exactly the latest plan job, if it was made from HEAD.
#            For the main stack, then sends afp-bootstrap to the VM through
#            Run Command (without waiting), so that the VM picks up afp.json.
#   destroy  Destroy every resource of the main stack (the stack itself is kept).
#            Empties the bucket first, dumps included. Asks to type the stack
#            name, or needs AFP_CONFIRM_DESTROY=<name>. Refused for the base stack.
#   outputs  Print the stack's outputs as KEY=VALUE lines.
#
# Environment:
#   AFP_CONFIG_DIR  Directory holding terraform.tfvars.json (required).
#   OCI_CLI_PROFILE, OCI_CLI_AUTH, ...  Passed through to the OCI CLI.
#
# Nothing is kept locally: the stack is found by its name in the tenancy root,
# and its state is held by Resource Manager.
set -euo pipefail

TERRAFORM_VERSION="1.5.x"
JOB_MAX_WAIT_SECONDS=3600
POLL_SECONDS=15
REFRESH_SECONDS=600

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY=(python3 "$ROOT/scripts/rm_values.py")

die() { echo "stack.sh: $*" >&2; exit 1; }
# Print the header comment (up to the first non-comment line).
usage() { sed -n '2,/^[^#]/p' "$0" | sed '$d' >&2; exit 2; }

# Each stack runs one root module of terraform/; both share terraform/modules/.
case "${1:-}" in
  base)
    STACK_NAME="afp-base"; WORKDIR="base"; MAKE_PREFIX="base-"
    VARIABLE_KEYS="tenancy_ocid,region"
    ;;
  main)
    STACK_NAME="afp"; WORKDIR="main"; MAKE_PREFIX=""
    VARIABLE_KEYS=""
    ;;
  *) usage ;;
esac
shift

# A deleted vault stays in its compartment for days; the base stack is kept.
if [[ "${1:-}" == "destroy" && "$WORKDIR" != "main" ]]; then
  die "the base stack is never destroyed by this script"
fi

: "${AFP_CONFIG_DIR:?AFP_CONFIG_DIR is not set}"
TFVARS="$AFP_CONFIG_DIR/terraform.tfvars.json"
[[ -f "$TFVARS" ]] || die "$TFVARS not found"

TENANCY="$("${PY[@]}" get "$TFVARS" tenancy_ocid)"
REGION="$("${PY[@]}" get "$TFVARS" region)"
oci_() { oci --region "$REGION" "$@"; }

require_clean_tree() {
  # The applied code must match a commit so the submodule pointer records it.
  if [[ -n "$(git -C "$ROOT" status --porcelain)" ]]; then
    die "working tree has uncommitted changes; commit them first"
  fi
}

head_sha() { git -C "$ROOT" rev-parse --short=12 HEAD; }

# Print the stack's OCID, or nothing if it does not exist. Fails on CLI errors
# (e.g. an expired session) instead of treating them as "not found".
find_stack() {
  local id
  id="$(oci_ resource-manager stack list --compartment-id "$TENANCY" \
    --display-name "$STACK_NAME" --lifecycle-state ACTIVE \
    --query 'data[0].id' --raw-output)" || die "cannot list stacks (is the OCI CLI session valid?)"
  [[ "$id" == "null" ]] || printf '%s\n' "$id"
}

# Wait for a job and print its log; fail unless it succeeded.
finish_job() {
  local job_id="$1" state
  state="$(oci_ resource-manager job get --job-id "$job_id" \
    --query 'data."lifecycle-state"' --raw-output)"
  oci_ resource-manager job get-job-logs-content --job-id "$job_id" \
    --query 'data' --raw-output || true
  [[ "$state" == "SUCCEEDED" ]] || die "job $job_id ended in $state"
}

# Session tokens expire after about an hour; keep them alive during long jobs.
refresh_session() {
  if [[ "${OCI_CLI_AUTH:-}" == "security_token" ]]; then
    oci session refresh > /dev/null 2>&1 || echo "stack.sh: warning: session refresh failed" >&2
  fi
}

run_job() {
  # $1: create-plan-job | create-apply-job | create-destroy-job; the rest is passed through.
  local kind="$1"; shift
  local job_id state waited=0 since_refresh=0
  refresh_session
  job_id="$(oci_ resource-manager job "$kind" "$@" --query 'data.id' --raw-output)"
  echo "Job $job_id started; waiting ..."
  while :; do
    state="$(oci_ resource-manager job get --job-id "$job_id" \
      --query 'data."lifecycle-state"' --raw-output)"
    case "$state" in
      SUCCEEDED|FAILED|CANCELED) break ;;
    esac
    (( waited < JOB_MAX_WAIT_SECONDS )) || die "job $job_id still $state after ${waited}s"
    sleep "$POLL_SECONDS"
    waited=$(( waited + POLL_SECONDS ))
    since_refresh=$(( since_refresh + POLL_SECONDS ))
    if (( since_refresh >= REFRESH_SECONDS )); then
      refresh_session
      since_refresh=0
    fi
  done
  finish_job "$job_id"
}

cmd_plan() {
  require_clean_tree
  local sha stack_id
  sha="$(head_sha)"
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT

  # Archive the committed tree, not the working files. The whole of terraform/
  # is sent so that the root module can reach ../modules.
  git -C "$ROOT" archive --format=zip -o "$tmp/stack.zip" HEAD:terraform
  "${PY[@]}" variables "$TFVARS" ${VARIABLE_KEYS:+"$VARIABLE_KEYS"} > "$tmp/variables.json"

  stack_id="$(find_stack)"
  if [[ -z "$stack_id" || "$stack_id" == "null" ]]; then
    echo "Creating stack $STACK_NAME ..."
    stack_id="$(oci_ resource-manager stack create --compartment-id "$TENANCY" \
      --display-name "$STACK_NAME" --description "AlwaysFreePlatform" \
      --terraform-version "$TERRAFORM_VERSION" \
      --freeform-tags '{"afp":"stack"}' \
      --config-source "$tmp/stack.zip" --working-directory "$WORKDIR" \
      --variables "file://$tmp/variables.json" \
      --wait-for-state ACTIVE --query 'data.id' --raw-output)"
  else
    echo "Updating stack $STACK_NAME ..."
    oci_ resource-manager stack update --stack-id "$stack_id" \
      --config-source "$tmp/stack.zip" --working-directory "$WORKDIR" \
      --variables "file://$tmp/variables.json" \
      --force --wait-for-state ACTIVE > /dev/null
  fi

  echo "Planning $sha ..."
  run_job create-plan-job --stack-id "$stack_id" --display-name "plan-$sha"
  echo "Plan of $sha succeeded. Run 'make ${MAKE_PREFIX}apply' to apply it."
}

cmd_apply() {
  require_clean_tree
  local sha stack_id plan
  sha="$(head_sha)"
  stack_id="$(find_stack)"
  [[ -n "$stack_id" && "$stack_id" != "null" ]] || die "stack not found; run 'make ${MAKE_PREFIX}plan' first"

  # Latest job of the stack must be a successful plan of HEAD.
  plan="$(oci_ resource-manager job list --stack-id "$stack_id" \
    --sort-by TIMECREATED --sort-order DESC --limit 1 \
    --query 'data[0].[id, operation, "lifecycle-state", "display-name"] | join(`" "`, @)' \
    --raw-output)"
  read -r plan_id operation state name <<< "$plan"
  [[ "$operation" == "PLAN" && "$state" == "SUCCEEDED" ]] \
    || die "latest job is not a successful plan ($operation $state); run 'make ${MAKE_PREFIX}plan'"
  [[ "$name" == "plan-$sha" ]] \
    || die "latest plan ($name) is not of HEAD ($sha); run 'make ${MAKE_PREFIX}plan'"

  echo "Applying $name ..."
  run_job create-apply-job --stack-id "$stack_id" --display-name "apply-$sha" \
    --execution-plan-strategy FROM_PLAN_JOB_ID --execution-plan-job-id "$plan_id"
  echo "Applied $sha. Commit the platform/ pointer in the config repository."
  if [[ "$WORKDIR" == "main" ]]; then
    # A new VM runs it by itself at boot; then this one only waits its turn.
    "$ROOT/scripts/run-command.sh" send "sudo -n /usr/local/sbin/afp-bootstrap" \
      || echo "stack.sh: warning: could not send afp-bootstrap to the VM" >&2
  fi
}

# A bucket with objects cannot be deleted. afp.json is left to Terraform.
empty_bucket() {
  local bucket
  bucket="$(stack_outputs "$1" | sed -n 's/^bucket=//p')"
  if [[ -z "$bucket" ]]; then
    echo "No bucket in the stack's outputs; nothing to empty."
    return
  fi
  if ! oci_ os bucket get --bucket-name "$bucket" > /dev/null 2>&1; then
    echo "Bucket $bucket not found; nothing to empty."
    return
  fi
  echo "Emptying bucket $bucket ..."
  oci_ os object bulk-delete --bucket-name "$bucket" --exclude afp.json --force > /dev/null \
    || die "cannot empty bucket $bucket"
}

cmd_destroy() {
  local stack_id answer
  stack_id="$(find_stack)"
  [[ -n "$stack_id" && "$stack_id" != "null" ]] || die "stack not found"

  if [[ "${AFP_CONFIRM_DESTROY:-}" != "$STACK_NAME" ]]; then
    [[ -t 0 ]] || die "not a terminal; set AFP_CONFIRM_DESTROY=$STACK_NAME to confirm"
    echo "This deletes everything in the bucket too, DB dumps included."
    read -r -p "Destroy all resources of stack '$STACK_NAME'? Type the stack name: " answer
    [[ "$answer" == "$STACK_NAME" ]] || die "aborted"
  fi

  empty_bucket "$stack_id"
  echo "Destroying ..."
  run_job create-destroy-job --stack-id "$stack_id" --display-name "destroy-$(head_sha)" \
    --execution-plan-strategy AUTO_APPROVED
  echo "Destroyed. The stack itself is kept; 'make plan' and 'make apply' recreate everything."
}

stack_outputs() {
  oci_ resource-manager stack get-stack-tf-state --stack-id "$1" --file - \
    | "${PY[@]}" outputs
}

cmd_outputs() {
  local stack_id
  stack_id="$(find_stack)"
  [[ -n "$stack_id" && "$stack_id" != "null" ]] || die "stack not found"
  stack_outputs "$stack_id"
}

case "${1:-}" in
  plan) cmd_plan ;;
  apply) cmd_apply ;;
  destroy) cmd_destroy ;;
  outputs) cmd_outputs ;;
  *) usage ;;
esac
