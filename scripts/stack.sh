#!/usr/bin/env bash
# Send plan/apply jobs for terraform/ to OCI Resource Manager.
#
# Usage: stack.sh plan|apply|destroy|outputs
#   plan     Upload terraform/ at HEAD and the variables, then run a plan job.
#   apply    Apply exactly the latest plan job, if it was made from HEAD.
#   destroy  Destroy every resource of the stack (the stack itself is kept).
#            Asks to type the stack name, or needs AFP_CONFIRM_DESTROY=<name>.
#   outputs  Print the stack's outputs as KEY=VALUE lines.
#
# Environment:
#   AFP_CONFIG_DIR  Directory holding terraform.tfvars.json (required).
#   OCI_CLI_PROFILE, OCI_CLI_AUTH, ...  Passed through to the OCI CLI.
#
# Nothing is kept locally: the stack is found by its name in the tenancy root,
# and its state is held by Resource Manager.
set -euo pipefail

STACK_NAME="afp"
TERRAFORM_VERSION="1.5.x"
JOB_MAX_WAIT_SECONDS=3600

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY=(python3 "$ROOT/scripts/rm_values.py")

die() { echo "stack.sh: $*" >&2; exit 1; }

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

find_stack() {
  oci_ resource-manager stack list --compartment-id "$TENANCY" \
    --display-name "$STACK_NAME" --lifecycle-state ACTIVE \
    --query 'data[0].id' --raw-output 2>/dev/null || true
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

run_job() {
  # $1: create-plan-job | create-apply-job; remaining args are passed through.
  local kind="$1"; shift
  local job_id
  job_id="$(oci_ resource-manager job "$kind" "$@" \
    --wait-for-state SUCCEEDED --wait-for-state FAILED --wait-for-state CANCELED \
    --max-wait-seconds "$JOB_MAX_WAIT_SECONDS" \
    --query 'data.id' --raw-output)"
  finish_job "$job_id"
}

cmd_plan() {
  require_clean_tree
  local sha stack_id
  sha="$(head_sha)"
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT

  # Archive the committed tree, not the working files.
  git -C "$ROOT" archive --format=zip -o "$tmp/stack.zip" HEAD:terraform
  "${PY[@]}" variables "$TFVARS" > "$tmp/variables.json"

  stack_id="$(find_stack)"
  if [[ -z "$stack_id" || "$stack_id" == "null" ]]; then
    echo "Creating stack $STACK_NAME ..."
    stack_id="$(oci_ resource-manager stack create --compartment-id "$TENANCY" \
      --display-name "$STACK_NAME" --description "AlwaysFreePlatform" \
      --terraform-version "$TERRAFORM_VERSION" \
      --freeform-tags '{"afp":"stack"}' \
      --config-source "$tmp/stack.zip" --variables "file://$tmp/variables.json" \
      --wait-for-state ACTIVE --query 'data.id' --raw-output)"
  else
    echo "Updating stack $STACK_NAME ..."
    oci_ resource-manager stack update --stack-id "$stack_id" \
      --config-source "$tmp/stack.zip" --variables "file://$tmp/variables.json" \
      --force --wait-for-state ACTIVE > /dev/null
  fi

  echo "Planning $sha ..."
  run_job create-plan-job --stack-id "$stack_id" --display-name "plan-$sha"
  echo "Plan of $sha succeeded. Run 'make apply' to apply it."
}

cmd_apply() {
  require_clean_tree
  local sha stack_id plan
  sha="$(head_sha)"
  stack_id="$(find_stack)"
  [[ -n "$stack_id" && "$stack_id" != "null" ]] || die "stack not found; run 'make plan' first"

  # Latest job of the stack must be a successful plan of HEAD.
  plan="$(oci_ resource-manager job list --stack-id "$stack_id" \
    --sort-by TIMECREATED --sort-order DESC --limit 1 \
    --query 'data[0].[id, operation, "lifecycle-state", "display-name"] | join(`" "`, @)' \
    --raw-output)"
  read -r plan_id operation state name <<< "$plan"
  [[ "$operation" == "PLAN" && "$state" == "SUCCEEDED" ]] \
    || die "latest job is not a successful plan ($operation $state); run 'make plan'"
  [[ "$name" == "plan-$sha" ]] \
    || die "latest plan ($name) is not of HEAD ($sha); run 'make plan'"

  echo "Applying $name ..."
  run_job create-apply-job --stack-id "$stack_id" --display-name "apply-$sha" \
    --execution-plan-strategy FROM_PLAN_JOB_ID --execution-plan-job-id "$plan_id"
  echo "Applied $sha. Commit the platform/ pointer in the config repository."
}

cmd_destroy() {
  local stack_id answer
  stack_id="$(find_stack)"
  [[ -n "$stack_id" && "$stack_id" != "null" ]] || die "stack not found"

  if [[ "${AFP_CONFIRM_DESTROY:-}" != "$STACK_NAME" ]]; then
    [[ -t 0 ]] || die "not a terminal; set AFP_CONFIRM_DESTROY=$STACK_NAME to confirm"
    read -r -p "Destroy all resources of stack '$STACK_NAME'? Type the stack name: " answer
    [[ "$answer" == "$STACK_NAME" ]] || die "aborted"
  fi

  echo "Destroying ..."
  run_job create-destroy-job --stack-id "$stack_id" --display-name "destroy-$(head_sha)" \
    --execution-plan-strategy AUTO_APPROVED
  echo "Destroyed. The stack itself is kept; 'make plan' and 'make apply' recreate everything."
}

cmd_outputs() {
  local stack_id
  stack_id="$(find_stack)"
  [[ -n "$stack_id" && "$stack_id" != "null" ]] || die "stack not found"
  oci_ resource-manager stack get-stack-tf-state --stack-id "$stack_id" --file - \
    | "${PY[@]}" outputs
}

case "${1:-}" in
  plan) cmd_plan ;;
  apply) cmd_apply ;;
  destroy) cmd_destroy ;;
  outputs) cmd_outputs ;;
  *) sed -n '2,15p' "$0" >&2; exit 2 ;;
esac
