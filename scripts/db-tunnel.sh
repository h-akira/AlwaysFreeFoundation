#!/usr/bin/env bash
# Open a tunnel to the MySQL HeatWave DB system through OCI Bastion.
#
# Usage: db-tunnel.sh
#   Creates a port-forwarding session and keeps `ssh -N -L` running in the
#   foreground. Stop with Ctrl-C. The session also expires by itself.
#
# Environment:
#   AFP_CONFIG_DIR       Directory holding terraform.tfvars.json (required).
#   AFP_SSH_PUBLIC_KEY   Public key for the session. The private key is the same
#                        path without ".pub". Default: a throwaway key pair made
#                        for this session and deleted on exit.
#   AFP_DB_LOCAL_PORT    Local port (default 13306, to avoid a local MySQL).
#   AFP_SESSION_TTL      Session lifetime in seconds (default 10800, the maximum).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY=(python3 "$ROOT/scripts/rm_values.py")

die() { echo "db-tunnel.sh: $*" >&2; exit 1; }

: "${AFP_CONFIG_DIR:?AFP_CONFIG_DIR is not set}"
TFVARS="$AFP_CONFIG_DIR/terraform.tfvars.json"
[[ -f "$TFVARS" ]] || die "$TFVARS not found"
REGION="$("${PY[@]}" get "$TFVARS" region)"

LOCAL_PORT="${AFP_DB_LOCAL_PORT:-13306}"
SESSION_TTL="${AFP_SESSION_TTL:-10800}"
oci_() { oci --region "$REGION" "$@"; }

session_id=""
tmp="$(mktemp -d)"
cleanup() {
  if [[ -n "$session_id" ]]; then
    oci_ bastion session delete --session-id "$session_id" --force > /dev/null 2>&1 || true
  fi
  rm -rf "$tmp"
}
trap cleanup EXIT

if [[ -n "${AFP_SSH_PUBLIC_KEY:-}" ]]; then
  PUBLIC_KEY="$AFP_SSH_PUBLIC_KEY"
  PRIVATE_KEY="${PUBLIC_KEY%.pub}"
  [[ -f "$PUBLIC_KEY" && -f "$PRIVATE_KEY" ]] || die "ssh key pair not found: $PRIVATE_KEY(.pub)"
else
  PRIVATE_KEY="$tmp/id_ed25519"
  PUBLIC_KEY="$PRIVATE_KEY.pub"
  ssh-keygen -q -t ed25519 -N "" -C "afp-db-tunnel" -f "$PRIVATE_KEY"
fi

# Stack outputs as KEY=VALUE lines (bash 3.2 compatible: no associative arrays).
outputs="$("$ROOT/scripts/stack.sh" main outputs)"
out() {
  local value
  value="$(printf '%s\n' "$outputs" | sed -n "s/^$1=//p")"
  [[ -n "$value" ]] || die "stack output $1 is missing; run 'make apply' first"
  printf '%s' "$value"
}
BASTION_ID="$(out bastion_id)"
DB_IP="$(out db_ip)"
DB_PORT="$(out db_port)"
DB_USER="$(out db_admin_username)"
SECRET_ID="$(out db_admin_secret_id)"

echo "Creating a Bastion session (TTL ${SESSION_TTL}s) ..."
session_id="$(oci_ bastion session create-port-forwarding \
  --bastion-id "$BASTION_ID" --display-name "afp-db-tunnel" \
  --target-private-ip "${DB_IP}" --target-port "${DB_PORT}" \
  --ssh-public-key-file "$PUBLIC_KEY" --key-type PUB --session-ttl "$SESSION_TTL" \
  --query 'data.id' --raw-output)"

for _ in $(seq 60); do
  state="$(oci_ bastion session get --session-id "$session_id" \
    --query 'data."lifecycle-state"' --raw-output)"
  [[ "$state" == "ACTIVE" ]] && break
  [[ "$state" == "CREATING" ]] || die "session $session_id is $state"
  sleep 5
done
[[ "$state" == "ACTIVE" ]] || die "session $session_id did not become ACTIVE"

cat <<EOF

Tunnel: 127.0.0.1:${LOCAL_PORT} -> ${DB_IP}:${DB_PORT}
Connect from another terminal:

  MYSQL_PWD="\$(oci secrets secret-bundle get --region ${REGION} \\
    --secret-id ${SECRET_ID} \\
    --query 'data."secret-bundle-content".content' --raw-output | base64 -d)" \\
  mysql -h 127.0.0.1 -P ${LOCAL_PORT} -u ${DB_USER}

Press Ctrl-C to close the tunnel.
EOF

ssh -i "$PRIVATE_KEY" -N \
  -o ServerAliveInterval=60 -o StrictHostKeyChecking=accept-new \
  -o UserKnownHostsFile="$tmp/known_hosts" \
  -L "127.0.0.1:${LOCAL_PORT}:${DB_IP}:${DB_PORT}" \
  "${session_id}@host.bastion.${REGION}.oci.oraclecloud.com"
