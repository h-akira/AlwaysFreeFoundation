#!/usr/bin/env bash
# Run a script on the VM through Run Command (Oracle Cloud Agent).
#
# Usage: run-command.sh send [--wait] [--timeout SECONDS] SCRIPT
#        run-command.sh result COMMAND_ID [--wait]
#   send     Send SCRIPT (run as ocarun; root needs sudo -n, see afp-bootstrap).
#            Without --wait, print the command's OCID and how to check it.
#   result   Print the state, exit code and the last 1 KB of output of a
#            command; with --wait, wait until it has finished.
#   With --wait, the exit code is the script's (1 if it timed out or was
#   canceled). The agent polls for commands about every 4 minutes, so even a
#   short script takes 0 to 5 minutes.
#
# Environment:
#   AFP_CONFIG_DIR    Directory holding terraform.tfvars.json (required).
#   AFP_POLL_SECONDS  Interval between checks while waiting (default 15).
set -euo pipefail

POLL_SECONDS="${AFP_POLL_SECONDS:-15}"
DEFAULT_TIMEOUT=3600
# On top of the timeout: the agent picks the command up within ~4 minutes.
PICKUP_SECONDS=600
MAX_CLI_FAILURES=4

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY=(python3 "$ROOT/scripts/rm_values.py")
# shellcheck source=SCRIPTDIR/lib.sh
source "$ROOT/scripts/lib.sh"

die() { echo "run-command.sh: $*" >&2; exit 1; }
usage() { sed -n '2,/^[^#]/p' "$0" | sed '$d' >&2; exit 2; }

: "${AFP_CONFIG_DIR:?AFP_CONFIG_DIR is not set}"
TFVARS="$AFP_CONFIG_DIR/terraform.tfvars.json"
[[ -f "$TFVARS" ]] || die "$TFVARS not found"
REGION="$("${PY[@]}" get "$TFVARS" region)"
oci_() { oci --region "$REGION" "$@" < /dev/null; }

# Print the result; return the script's exit code (1 when there is none).
show_result() {
  local json="$1" state code
  read -r state code < <(printf '%s' "$json" | "${PY[@]}" execution | head -1)
  echo "Run Command: $state (exit code $code)"
  printf '%s' "$json" | "${PY[@]}" execution | tail -n +2
  [[ "$state" == "SUCCEEDED" ]] && return 0
  [[ "$code" =~ ^[0-9]+$ && "$code" != "0" ]] && return "$code"
  return 1
}

# Wait until the command has finished, then show it.
wait_result() {
  local command_id="$1" max_wait="$2" waited=0 failures=0 json state
  echo "Waiting for the VM to run it (the agent polls about every 4 minutes) ..."
  while :; do
    if json="$(oci_ instance-agent command-execution get \
        --command-id "$command_id" --instance-id "$VM_ID" 2> /dev/null)"; then
      failures=0
      state="$(printf '%s' "$json" | "${PY[@]}" execution | head -1 | cut -d' ' -f1)"
      case "$state" in
        SUCCEEDED|FAILED|TIMED_OUT|CANCELED) show_result "$json"; return ;;
      esac
    else
      # Right after create the execution may not be readable yet; an expired
      # session fails every time.
      failures=$(( failures + 1 ))
      (( failures < MAX_CLI_FAILURES )) || die "cannot read command $command_id (is the OCI CLI session valid?)"
    fi
    (( waited < max_wait )) || die "command $command_id has not finished after ${waited}s"
    sleep "$POLL_SECONDS"
    waited=$(( waited + POLL_SECONDS ))
  done
}

cmd_send() {
  local wait=false timeout="$DEFAULT_TIMEOUT" script command_id
  while [[ $# -gt 1 ]]; do
    case "$1" in
      --wait) wait=true; shift ;;
      --timeout) timeout="$2"; shift 2 ;;
      *) usage ;;
    esac
  done
  [[ $# -eq 1 && -n "$1" ]] || usage
  script="$1"
  load_outputs
  VM_ID="$(out vm_id)"
  command_id="$(oci_ instance-agent command create \
    --compartment-id "$(out compartment_id)" \
    --target "{\"instanceId\":\"$VM_ID\"}" \
    --display-name "afp $(date -u +%Y%m%dT%H%M%SZ)" \
    --timeout-in-seconds "$timeout" \
    --content "$("${PY[@]}" command-content "$script")" \
    --query 'data.id' --raw-output)" || die "cannot send the command"
  echo "Sent to the VM: $script"
  if [[ "$wait" == true ]]; then
    wait_result "$command_id" $(( timeout + PICKUP_SECONDS ))
  else
    echo "Command $command_id. Check it with: make command-result ID=$command_id"
  fi
}

cmd_result() {
  [[ $# -ge 1 ]] || usage
  local command_id="$1" json
  load_outputs
  VM_ID="$(out vm_id)"
  if [[ "${2:-}" == "--wait" ]]; then
    wait_result "$command_id" $(( DEFAULT_TIMEOUT + PICKUP_SECONDS ))
  else
    json="$(oci_ instance-agent command-execution get \
      --command-id "$command_id" --instance-id "$VM_ID")" || die "cannot read command $command_id"
    show_result "$json"
  fi
}

case "${1:-}" in
  send) shift; cmd_send "$@" ;;
  result) shift; cmd_result "$@" ;;
  *) usage ;;
esac
