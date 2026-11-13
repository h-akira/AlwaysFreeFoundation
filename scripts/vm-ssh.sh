#!/usr/bin/env bash
# ssh into the VM (user opc) through OCI Bastion, for maintenance only.
#
# Usage: vm-ssh.sh [COMMAND ...]
#   Creates a port-forwarding session to the VM's port 22, connects through it
#   (ProxyCommand) and deletes the session on exit. Without COMMAND, opens an
#   interactive shell.
#
# Environment:
#   AFP_CONFIG_DIR   Directory holding terraform.tfvars.json (required).
#   AFP_SSH_KEY      Private key whose public half is ssh_public_key in
#                    terraform.tfvars.json (default ~/.ssh/afp_ed25519).
#                    The Bastion session uses the same key.
#   AFP_SESSION_TTL  Session lifetime in seconds (default 3600).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY=(python3 "$ROOT/scripts/rm_values.py")
# shellcheck source=SCRIPTDIR/lib.sh
source "$ROOT/scripts/lib.sh"

die() { echo "vm-ssh.sh: $*" >&2; exit 1; }

: "${AFP_CONFIG_DIR:?AFP_CONFIG_DIR is not set}"
TFVARS="$AFP_CONFIG_DIR/terraform.tfvars.json"
[[ -f "$TFVARS" ]] || die "$TFVARS not found"
REGION="$("${PY[@]}" get "$TFVARS" region)"

PRIVATE_KEY="${AFP_SSH_KEY:-$HOME/.ssh/afp_ed25519}"
PUBLIC_KEY="$PRIVATE_KEY.pub"
SESSION_TTL="${AFP_SESSION_TTL:-3600}"
[[ -f "$PRIVATE_KEY" && -f "$PUBLIC_KEY" ]] || die "ssh key pair not found: $PRIVATE_KEY(.pub)"
oci_() { oci --region "$REGION" "$@"; }

tmp="$(mktemp -d)"
cleanup() {
  [[ -z "$BASTION_SESSION_ID" ]] || bastion_delete_session
  rm -rf "$tmp"
}
trap cleanup EXIT

load_outputs
BASTION_ID="$(out bastion_id)"
VM_IP="$(out vm_private_ip)"

bastion_create_session "$BASTION_ID" afp-vm-ssh "$VM_IP" 22 "$PUBLIC_KEY" "$SESSION_TTL"

# The VM's host key changes whenever it is recreated; the path to it is
# already authenticated by the Bastion, so a throwaway known_hosts is used.
ssh_opts=(-i "$PRIVATE_KEY" -o IdentitiesOnly=yes -o ServerAliveInterval=60
  -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$tmp/known_hosts")
ssh "${ssh_opts[@]}" \
  -o ProxyCommand="ssh ${ssh_opts[*]} -W %h:%p $(bastion_host)" \
  "opc@$VM_IP" "$@"
