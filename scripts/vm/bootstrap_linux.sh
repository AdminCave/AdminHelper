#!/usr/bin/env bash
#
# bootstrap_linux.sh — hydrate a fresh Linux box (Ubuntu 24.04) with every
# toolchain the heavy AdminHelper suites need, then it can run
# `bash scripts/tests/run.sh all`. Idempotent-ish: safe to re-run.
#
# Runs ON THE BOX, e.g.:
#   python3 scripts/vm/vm.py run <vmid> --sync -- 'bash scripts/vm/bootstrap_linux.sh'
# Run as the (non-root) guest user: apt/docker steps use `sudo` internally,
# while rustup/cargo install run as the user so cargo lands in ~/.cargo (not
# root's). The guest user needs passwordless sudo (our templates provide it).
#
# Mirrors the dependency setup in .github/workflows/ci.yml so the box matches CI.

set -euo pipefail

FRP_VERSION="${AH_FRP_VERSION:-0.69.1}"
FRP_SHA256_LINUX_AMD64="7be257b72dbbc60bcb3e0e25a5afd1dfac7b63f897084864d3c956dd3d5674e1"
GO_VERSION="${AH_GO_VERSION:-1.25.0}"
# Pin the Go tarball checksum like the frpc one (consistency) — the official sha256
# from go.dev's release JSON; override alongside a non-default GO_VERSION (4.123).
GO_SHA256_LINUX_AMD64="${AH_GO_SHA256:-2852af0cb20a13139b3448992e69b868e50ed0f8a1e5940ee1de9e19a123b613}"
NODE_MAJOR="${AH_NODE_MAJOR:-22}"
TAURI_CLI_VERSION="${AH_TAURI_CLI_VERSION:-2.11.2}"
# Pinned, and to the same version ci.yml installs: a bake picks up whatever pip
# offers that day, and a newer ruff enables rules this repo never opted into.
# The 2026-09-17 bake proved it — a fresh template's `run.sh lint` went red with
# UP017/B008/RUF100 while the dev box and CI were green, which reads as "the
# tree is broken" and is really "the box is newer". Keep in sync with
# .github/workflows/ci.yml and the floor in apps/server/requirements-dev.txt.
RUFF_VERSION="${AH_RUFF_VERSION:-0.15.20}"
# pytest for scripts/vm/tests: run.sh's `vm-pytest` step dep-gates on importing
# it, and only the python components' own steps build the shared venv. Without
# it here, `run.sh --only scripts` on a box SKIPs the step and --strict calls
# that a failure — on a box where nothing is wrong. Pinned like ci.yml's.
PYTEST_VERSION="${AH_PYTEST_VERSION:-9.1.1}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
# Profile: full (default — everything, for the single-box run.sh incl. desktop GUI
# E2E) | server (docker stack only) | agent (Go agent + packaging). server/agent
# never run Tauri, so they skip the ~18min tauri-cli/rustc compile.
PROFILE="${AH_BOOTSTRAP_PROFILE:-full}"

SUDO=""; [ "$(id -u)" -eq 0 ] || SUDO="sudo"
log() { printf '\n\033[1m[bootstrap] %s\033[0m\n' "$*"; }

# A freshly booted VM still runs cloud-init/unattended-upgrades, which hold the
# dpkg lock for the first minute or two. Without waiting, bootstrap dies with
# "Could not get lock /var/lib/dpkg/lock-frontend" — the single most common
# transient failure of a fresh multibox lease (it took out the rpm and tunnel
# boxes of a whole capstone run).
# ALL four locks, not just lock-frontend: `apt-get update` takes
# /var/lib/apt/lists/lock while `apt-get install` takes the dpkg ones — waiting
# for a single file let the update step race straight into "Could not get lock
# /var/lib/apt/lists/lock" and killed a fresh rpm box mid-capstone.
wait_apt_lock() {
    local locks="/var/lib/dpkg/lock-frontend /var/lib/dpkg/lock /var/lib/apt/lists/lock /var/cache/apt/archives/lock"
    local l held
    for _ in $(seq 1 90); do
        held=0
        for l in $locks; do
            [ -e "$l" ] || continue
            $SUDO fuser "$l" >/dev/null 2>&1 && { held=1; break; }
        done
        [ "$held" = 0 ] && return 0
        sleep 5
    done
    echo "[bootstrap] WARNUNG: apt/dpkg-Lock nach 7.5 min noch belegt — versuche es trotzdem." >&2
}

# Waiting is treatment, not cure: unattended-upgrades can start at ANY point
# during the bootstrap, so a single wait at the top only moves the race later
# (it took out the docker and node steps). Shut the racer down for the box's
# lifetime — these are throwaway test VMs, they need no background updates.
disable_apt_timers() {
    local u
    for u in unattended-upgrades.service apt-daily.timer apt-daily-upgrade.timer \
             apt-daily.service apt-daily-upgrade.service; do
        $SUDO systemctl stop "$u" 2>/dev/null || true
        $SUDO systemctl mask "$u" 2>/dev/null || true
    done
}

# A drop-in, not a shell variable: this way EVERY apt process inherits it,
# including the ones the nodesource setup script spawns internally, which no
# wrapper could bracket. Covers the dpkg locks only — `apt-get update` takes
# /var/lib/apt/lists/lock, for which apt has no timeout knob (verified in
# apt-pkg/update.cc), so wait_apt_lock stays responsible for that one.
write_apt_lock_dropin() {
    printf 'DPkg::Lock::Timeout "300";\n' \
        | $SUDO tee /etc/apt/apt.conf.d/99lock-timeout >/dev/null 2>&1 || true
}

log "apt base + tauri libs + display + repo-build + keyring tooling"
export DEBIAN_FRONTEND=noninteractive
disable_apt_timers
write_apt_lock_dropin
wait_apt_lock
# If the stopped unattended-upgrades run was killed mid-transaction, the next
# apt call dies with "dpkg was interrupted". Cheap insurance, no-op otherwise.
$SUDO dpkg --configure -a >/dev/null 2>&1 || true
$SUDO apt-get update -qq
# --no-upgrade: on a box cloned from the fat template every package below is
# already installed (bar what was added to the list after the bake), and a plain
# `install -y` would UPGRADE all of them to the
# newest mirror versions (25 MB of webkit2gtk alone). In the 2026-09-11 weekly
# that upgrade, stacked on the apt-lock wait, pushed two role setups past their
# role timeout; every capstone failure that day was a consequence. Install
# what is missing, leave what is there.
$SUDO apt-get install -y --no-install-recommends --no-upgrade \
  ca-certificates curl git rsync openssl gnupg jq unzip build-essential pkg-config \
  python3 python3-pip python3-venv shellcheck \
  libgtk-3-dev libwebkit2gtk-4.1-dev librsvg2-dev libxdo-dev \
  libayatana-appindicator3-dev libssl-dev patchelf file \
  xvfb webkit2gtk-driver at-spi2-core dbus-x11 gnome-keyring \
  minisign dpkg-dev apt-utils createrepo-c rpm locales \
  xterm freerdp2-x11 qemu-guest-agent

# qemu-guest-agent: vm.py asks the hypervisor for the guest's address instead of
# parsing it out of a provider's output, so a template without it is a template
# whose clones never become reachable. Both cloud images already carry it —
# this line is what keeps a bake from losing it (scripts/vm/vm.py, `wait`).
# Hard, not a warning: without the agent, vm.py never learns a clone's address,
# so a template baked without it produces boxes nobody can reach — and the next
# thing anyone sees is `vm.py wait` timing out 900 s later, once per lease.
$SUDO systemctl enable --now qemu-guest-agent

# xterm + freerdp2-x11: the desktop client SPAWNS these to open an SSH terminal
# (terminal.rs profile list) resp. an RDP session. Without them desktop_e2e_connect
# fails with "sshd/xrdp saw no connection" — the launch silently has nothing to
# exec, while web-connect still passes (xdg-open/webview). Cost: ~30 MB.

# Hard, not best-effort: without en_US.UTF-8 the headless webview dies in
# Intl.NumberFormat and every desktop journey sees a blank #app — a box that
# looks bootstrapped and fails seven GUI suites for a reason nobody reads out of
# a screenshot (.claude/rules/testing.md).
log "generate a valid UTF-8 locale (headless boxes default to C — breaks Intl.NumberFormat in the desktop webview -> blank app)"
$SUDO locale-gen en_US.UTF-8 >/dev/null
$SUDO update-locale LANG=en_US.UTF-8 >/dev/null

# The pipx fallback stays, the `|| true` behind it does not: run.sh dep-gates
# both of these, so a failed install does not go red — it SKIPs, and under
# --strict the box is then reported as unverified for a reason that has nothing
# to do with the tree. A bootstrap that could not install them must say so here.
log "ruff $RUFF_VERSION (Python lint, used by run.sh lint)"
$SUDO pip3 install --break-system-packages -q "ruff==$RUFF_VERSION" \
  || pipx install "ruff==$RUFF_VERSION"
log "pytest $PYTEST_VERSION (used by run.sh unit's vm-pytest step)"
$SUDO pip3 install --break-system-packages -q "pytest==$PYTEST_VERSION" \
  || pipx install "pytest==$PYTEST_VERSION"

log "docker engine + compose v2 plugin"
if ! command -v docker >/dev/null 2>&1; then
  $SUDO install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | $SUDO gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  $SUDO chmod a+r /etc/apt/keyrings/docker.gpg
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    | $SUDO tee /etc/apt/sources.list.d/docker.list >/dev/null
  wait_apt_lock
  $SUDO apt-get update -qq
  $SUDO apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
# Both hard: a box whose docker never came up, or whose user is not in the
# docker group, brings the whole integration tier down with permission errors
# forty minutes later instead of failing here in a second.
$SUDO systemctl enable --now docker
$SUDO usermod -aG docker "${SUDO_USER:-$USER}"   # effective on next login/session

log "Go ${GO_VERSION}"
if ! command -v go >/dev/null 2>&1 || ! go version | grep -q "$GO_VERSION"; then
  curl -fsSL --retry 3 --retry-connrefused -o /tmp/go.tgz "https://go.dev/dl/go${GO_VERSION}.linux-amd64.tar.gz"
  echo "${GO_SHA256_LINUX_AMD64}  /tmp/go.tgz" | sha256sum -c -
  $SUDO rm -rf /usr/local/go && $SUDO tar -C /usr/local -xzf /tmp/go.tgz
  echo 'export PATH=$PATH:/usr/local/go/bin:$HOME/go/bin' | $SUDO tee /etc/profile.d/go.sh >/dev/null
fi
export PATH="$PATH:/usr/local/go/bin:$HOME/go/bin"

log "Node ${NODE_MAJOR}.x"
if ! command -v node >/dev/null 2>&1 || [ "$(node -v | grep -oE '[0-9]+' | head -1)" != "$NODE_MAJOR" ]; then
  curl -fsSL --retry 3 --retry-connrefused "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | $SUDO -E bash -
  wait_apt_lock
  $SUDO apt-get install -y nodejs
fi

if [ "$PROFILE" = full ]; then
  log "Rust (rustup stable) + rustfmt + clippy  [full profile only]"
  if ! command -v cargo >/dev/null 2>&1; then
    curl -fsSL https://sh.rustup.rs | sh -s -- -y --profile minimal
  fi
  # shellcheck disable=SC1091
  [ -f "$HOME/.cargo/env" ] && . "$HOME/.cargo/env"
  # Hard: `cargo fmt`/`clippy -D warnings` are gates (CLAUDE.md §7), and without
  # the components run.sh's desktop-cargo step fails on the box, not here.
  rustup component add rustfmt clippy

  # No `|| true` here: a failed install used to leave the box looking bootstrapped
  # while all seven desktop_e2e_*.sh suites then skipped on the missing tauri-cli.
  # Failing the bootstrap is loud and fixable; a half-hydrated box is neither.
  log "tauri-driver + tauri-cli ${TAURI_CLI_VERSION} (for desktop build + GUI E2E)  [full profile only]"
  command -v tauri-driver >/dev/null 2>&1 || cargo install tauri-driver --locked \
    || { log "FATAL: tauri-driver install failed — the GUI E2E suites cannot run on this box"; exit 1; }
  cargo tauri --version >/dev/null 2>&1 || cargo install tauri-cli --locked --version "$TAURI_CLI_VERSION" \
    || { log "FATAL: tauri-cli install failed — the seven desktop_e2e_*.sh suites would all SKIP"; exit 1; }
else
  log "skipping Rust/Tauri toolchain (profile=$PROFILE — no Tauri on this box)"
fi

log "frpc sidecar v${FRP_VERSION} (externalBin must resolve for the Tauri build)"
curl -fsSL --retry 3 --retry-connrefused -o /tmp/frpc.tgz \
  "https://github.com/fatedier/frp/releases/download/v${FRP_VERSION}/frp_${FRP_VERSION}_linux_amd64.tar.gz"
echo "${FRP_SHA256_LINUX_AMD64}  /tmp/frpc.tgz" | sha256sum -c -
tar -C /tmp -xzf /tmp/frpc.tgz
mkdir -p "$ROOT/apps/desktop/src-tauri/binaries"
cp "/tmp/frp_${FRP_VERSION}_linux_amd64/frpc" "$ROOT/apps/desktop/src-tauri/binaries/frpc-x86_64-unknown-linux-gnu"
chmod +x "$ROOT/apps/desktop/src-tauri/binaries/frpc-x86_64-unknown-linux-gnu"

log "done — verify with: bash scripts/tests/run.sh lint"
echo "NOTE: 'docker' group membership takes effect on a new session — the next"
echo "      'vm.py run' will already have it (fresh SSH session)."
