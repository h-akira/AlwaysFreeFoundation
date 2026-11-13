# shellcheck shell=bash
# Shared by db-tunnel.sh and vm-ssh.sh (sourced, not run).
# The caller sets ROOT and REGION, defines die() and oci_(), and deletes any
# Bastion session on exit:
#   trap '[[ -z "$BASTION_SESSION_ID" ]] || bastion_delete_session' EXIT

# Main stack outputs as KEY=VALUE lines (bash 3.2: no associative arrays).
STACK_OUTPUTS=""
load_outputs() {
  STACK_OUTPUTS="$("$ROOT/scripts/stack.sh" main outputs)" || die "cannot read the stack outputs"
}

# Print one output loaded by load_outputs.
out() {
  local value
  value="$(printf '%s\n' "$STACK_OUTPUTS" | sed -n "s/^$1=//p")"
  [[ -n "$value" ]] || die "stack output $1 is missing; run 'make apply' first"
  printf '%s' "$value"
}

BASTION_SESSION_ID=""

# Create a port-forwarding session and wait until it is ACTIVE.
# Usage: bastion_create_session BASTION_ID NAME TARGET_IP TARGET_PORT PUBLIC_KEY_FILE TTL
bastion_create_session() {
  local bastion_id="$1" name="$2" ip="$3" port="$4" public_key="$5" ttl="$6" state=""
  echo "Creating a Bastion session to ${ip}:${port} (TTL ${ttl}s) ..." >&2
  BASTION_SESSION_ID="$(oci_ bastion session create-port-forwarding \
    --bastion-id "$bastion_id" --display-name "$name" \
    --target-private-ip "$ip" --target-port "$port" \
    --ssh-public-key-file "$public_key" --key-type PUB --session-ttl "$ttl" \
    --query 'data.id' --raw-output)" || die "cannot create a Bastion session"
  for _ in $(seq 60); do
    state="$(oci_ bastion session get --session-id "$BASTION_SESSION_ID" \
      --query 'data."lifecycle-state"' --raw-output)"
    [[ "$state" == "ACTIVE" ]] && return 0
    [[ "$state" == "CREATING" ]] || die "session $BASTION_SESSION_ID is $state"
    sleep 5
  done
  die "session $BASTION_SESSION_ID did not become ACTIVE"
}

bastion_delete_session() {
  oci_ bastion session delete --session-id "$BASTION_SESSION_ID" --force > /dev/null 2>&1 || true
}

# ssh destination of the session, e.g. for -L or ProxyCommand.
bastion_host() {
  printf '%s@host.bastion.%s.oci.oraclecloud.com' "$BASTION_SESSION_ID" "$REGION"
}
