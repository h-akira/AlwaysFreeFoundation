#!/usr/bin/env bash
# afp-bootstrap: bring the VM up to the platform's code and hand over to afp.
#
# Installed by cloud-init. Run by afp-bootstrap.service at every boot until it
# succeeds, and through Run Command (sudo) by make platform and make apply.
# Every step is idempotent, so running it again only does what is missing.
#
#   0. no kdump: free the crash kernel reservation (reboots once if needed)
#   1. swap; stop dnf's background metadata refresh
#   2. wait until the VM can reach the internet (the reserved IP comes later)
#   3. Docker, the compose plugin and the OCI CLI
#   4. block containers from the metadata service (except the VCN's DNS)
#   5. let ocarun (Run Command) sudo only this script and afp
#   6. fetch the platform code named in platform.json, then afp install / sync
set -euo pipefail

BUCKET="afp" # must match the bucket name in terraform/main
AFP_DIR="/opt/afp"
SWAP_FILE="/swapfile"
SWAP_MB=2048
METADATA="http://169.254.169.254/opc/v2"

log() { echo "afp-bootstrap: $*" >&2; }
die() { log "$*"; exit 1; }

# Only one run at a time (the unit and Run Command may overlap).
exec 9> /run/afp-bootstrap.lock
flock -w 600 9 || die "another run holds the lock"

# Write stdin to a file only if it differs; print "changed" when it does.
put_file() {
  local path="$1" mode="$2" tmp
  tmp="$(mktemp)"
  cat > "$tmp"
  if [[ -f "$path" ]] && cmp -s "$tmp" "$path"; then
    rm -f "$tmp"
    return
  fi
  install -m "$mode" "$tmp" "$path"
  rm -f "$tmp"
  echo changed
}

json_get() { python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$1" "$2"; }

# 0. Oracle Linux 9 reserves 448 MB for kdump (crashkernel=1G-64G:448M)
# whenever the VM sees at least 1 GB, which an E2.1.Micro sometimes does.
# The VM is replaced rather than debugged, so kdump is turned off.
if [[ -f /etc/kdump.conf ]]; then
  sed -i -E 's/^([[:space:]]*auto_reset_crashkernel[[:space:]]+)yes/\1no/' /etc/kdump.conf
fi
systemctl disable --now kdump.service > /dev/null 2>&1 || true
if grubby --info=ALL | grep -q 'crashkernel='; then
  grubby --update-kernel=ALL --remove-args=crashkernel
fi
# Arguments for kernels installed later.
for f in /etc/default/grub /etc/kernel/cmdline; do
  if [[ -f "$f" ]]; then
    sed -i -E 's/ ?crashkernel=[^ "]*//g' "$f"
  fi
done
if [[ "$(cat /sys/kernel/kexec_crash_size)" != "0" ]]; then
  # Never loop: reboot only if the next boot will really be without it.
  grubby --info=DEFAULT | grep -q 'crashkernel=' && die "cannot remove crashkernel"
  log "rebooting to release the kdump memory reservation"
  systemctl reboot
  exit 0
fi

# 1. Swap first: dnf alone can exhaust 1 GB of memory.
if ! swapon --show=NAME --noheadings | grep -qx "$SWAP_FILE"; then
  if [[ ! -f "$SWAP_FILE" ]]; then
    log "creating ${SWAP_MB} MB swap"
    dd if=/dev/zero of="$SWAP_FILE" bs=1M count="$SWAP_MB" status=none
    chmod 600 "$SWAP_FILE"
    mkswap "$SWAP_FILE" > /dev/null
  fi
  swapon "$SWAP_FILE"
fi
grep -q "^$SWAP_FILE " /etc/fstab || echo "$SWAP_FILE none swap defaults 0 0" >> /etc/fstab
systemctl disable --now dnf-makecache.timer > /dev/null 2>&1 || true

# 2. Outbound access starts only after the reserved public IP is attached.
for i in $(seq 90); do
  curl -sS -m 10 -o /dev/null https://github.com && break
  (( i < 90 )) || die "no internet access yet"
  log "waiting for internet access ..."
  sleep 10
done

# 3. Packages. On 1 GB of memory, loading every enabled repository's metadata
# takes most of the time (ol9_oci_included alone took about 9 minutes), so
# each install enables only the repositories it needs. No man pages either.
dnf_() {
  local repos="$1"; shift
  dnf install -y --setopt=tsflags=nodocs --disablerepo='*' --enablerepo="$repos" "$@"
}
if ! rpm -q docker-ce docker-compose-plugin > /dev/null 2>&1; then
  log "installing Docker"
  [[ -f /etc/yum.repos.d/docker-ce.repo ]] \
    || dnf config-manager --add-repo https://download.docker.com/linux/rhel/docker-ce.repo
  dnf_ docker-ce-stable,ol9_baseos_latest,ol9_appstream \
    docker-ce docker-ce-cli containerd.io docker-compose-plugin
fi
if ! rpm -q python39-oci-cli > /dev/null 2>&1; then
  log "installing the OCI CLI"
  dnf_ ol9_oci_included,ol9_baseos_latest,ol9_appstream python39-oci-cli
fi

mkdir -p /etc/docker
daemon_changed="$(put_file /etc/docker/daemon.json 0644 <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": {"max-size": "10m", "max-file": "3"}
}
EOF
)"

# 4. Containers must not reach 169.254.169.254 (instance principal tokens),
# except port 53 on the same address, which is the VCN's DNS resolver.
# Docker creates DOCKER-USER at start; the unit re-adds the rules each time.
put_file /usr/local/sbin/afp-metadata-block 0755 > /dev/null <<'EOF'
#!/bin/sh
# Rebuild the rules in a fixed order: DNS first, then the drop.
set -e
for rule in "-d 169.254.169.254/32 -p udp --dport 53 -j RETURN" \
            "-d 169.254.169.254/32 -p tcp --dport 53 -j RETURN" \
            "-d 169.254.0.0/16 -j DROP"; do
  # shellcheck disable=SC2086
  while iptables -D DOCKER-USER $rule 2> /dev/null; do :; done
done
iptables -I DOCKER-USER 1 -d 169.254.169.254/32 -p udp --dport 53 -j RETURN
iptables -I DOCKER-USER 2 -d 169.254.169.254/32 -p tcp --dport 53 -j RETURN
iptables -I DOCKER-USER 3 -d 169.254.0.0/16 -j DROP
EOF
unit_changed="$(put_file /etc/systemd/system/afp-metadata-block.service 0644 <<'EOF'
[Unit]
Description=Block containers from the instance metadata service
After=docker.service
PartOf=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/afp-metadata-block

[Install]
WantedBy=docker.service
EOF
)"
[[ -z "$unit_changed" ]] || systemctl daemon-reload
systemctl enable docker.service afp-metadata-block.service > /dev/null 2>&1
if [[ -n "$daemon_changed" ]] && systemctl is-active --quiet docker; then
  systemctl restart docker
fi
systemctl start docker.service afp-metadata-block.service

# 5. Run Command runs as ocarun; it may run exactly these as root.
sudoers="$(mktemp)"
echo "ocarun ALL=(root) NOPASSWD: /usr/local/sbin/afp-bootstrap, $AFP_DIR/current/bin/afp" > "$sudoers"
visudo -cqf "$sudoers" || die "invalid sudoers entry"
put_file /etc/sudoers.d/afp 0440 < "$sudoers" > /dev/null
rm -f "$sudoers"

# 6. Platform code. afp.json is written by Terraform, platform.json by
# make platform; wait (fail and retry) until both exist.
region="$(curl -sSf -m 10 -H 'Authorization: Bearer Oracle' "$METADATA/instance/canonicalRegionName")"
oci_() { oci --auth instance_principal --region "$region" "$@"; }
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
oci_ os object get -bn "$BUCKET" --name afp.json --file "$work/afp.json" > /dev/null \
  || die "cannot read afp.json from bucket $BUCKET"
oci_ os object get -bn "$BUCKET" --name platform.json --file "$work/platform.json" > /dev/null 2>&1 \
  || die "platform.json not found; run 'make platform TAG=<tag>'"

commit="$(json_get "$work/platform.json" commit)"
repo="$(json_get "$work/afp.json" platform_repository)"
[[ "$commit" =~ ^[0-9a-f]{40}$ ]] || die "invalid commit in platform.json: $commit"

mkdir -p "$AFP_DIR/releases"
release="$AFP_DIR/releases/$commit"
if [[ ! -d "$release" ]]; then
  log "fetching $repo at $commit"
  # Tags can move, so the code is fetched by commit.
  curl -fsSL -m 300 -o "$work/src.tar.gz" "$repo/archive/$commit.tar.gz"
  rm -rf "$release.tmp"
  mkdir "$release.tmp"
  tar -xzf "$work/src.tar.gz" --strip-components=1 -C "$release.tmp"
  mv "$release.tmp" "$release"
fi
if [[ "$(readlink "$AFP_DIR/current" || true)" != "releases/$commit" ]]; then
  ln -sfn "releases/$commit" "$AFP_DIR/current.new"
  mv -T "$AFP_DIR/current.new" "$AFP_DIR/current"
  log "platform code is now $commit"
fi

[[ -x "$AFP_DIR/current/bin/afp" ]] || die "$commit has no bin/afp"
"$AFP_DIR/current/bin/afp" install
"$AFP_DIR/current/bin/afp" sync
log "done"
