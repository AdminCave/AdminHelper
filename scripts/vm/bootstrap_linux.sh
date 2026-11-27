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

FRP_VERSION="${AH_FRP_VERSION:-0.72.0}"
FRP_SHA256_LINUX_AMD64="daf719b32ca2778770bb92955e231a07414d754378b9af328aa2642862479804"
GO_VERSION="${AH_GO_VERSION:-1.27.4}"
# Pin the Go tarball checksum like the frpc one (consistency) — the official sha256
# from go.dev's release JSON; override alongside a non-default GO_VERSION (4.123).
GO_SHA256_LINUX_AMD64="${AH_GO_SHA256:-7226736c2339719cda28fbf3a54d71aa63bcefe376e98cef00034268dab24840}"
NODE_MAJOR="${AH_NODE_MAJOR:-26}"
TAURI_CLI_VERSION="${AH_TAURI_CLI_VERSION:-2.12.4}"
# Pinned, and to the same version ci.yml installs: a bake picks up whatever pip
# offers that day, and a newer ruff enables rules this repo never opted into.
# The 2026-09-17 bake proved it — a fresh template's `run.sh lint` went red with
# UP017/B008/RUF100 while the dev box and CI were green, which reads as "the
# tree is broken" and is really "the box is newer". Keep in sync with
# .github/workflows/ci.yml and the pin in apps/server/requirements-dev.txt.
RUFF_VERSION="${AH_RUFF_VERSION:-0.17.4}"
# pytest for scripts/vm/tests: run.sh's `vm-pytest` step dep-gates on importing
# it, and only the python components' own steps build the shared venv. Without
# it here, `run.sh --only scripts` on a box SKIPs the step and --strict calls
# that a failure — on a box where nothing is wrong. Pinned like ci.yml's.
PYTEST_VERSION="${AH_PYTEST_VERSION:-9.1.1}"
# oasdiff for run.sh's scripts block: openapi_breaking_test checks the ERR
# exception file against the real matcher and exits 75 without the binary, which
# --strict calls a failure. The release tarball and SHA-256 ci.yml pins (step
# "Install oasdiff"); scripts/dev/toolchain-lockstep.sh holds the two together.
OASDIFF_VERSION="${AH_OASDIFF_VERSION:-1.32.0}"
OASDIFF_SHA256_LINUX_AMD64="${AH_OASDIFF_SHA256:-5b2050787cfee2a9a3ba7b25cb50fe2c5cc45cdf5b96fbc51a4a60107f8b4aad}"
# python3.14 for run.sh's venv: the install_only build of
# astral-sh/python-build-standalone, pinned by release and SHA-256 and at the
# patch version of the Dockerfiles' python:3.14-slim. Not the deadsnakes PPA:
# Launchpad answered 503 on 2026-11-25 and every fresh box failed its lease
# (R-1789); GitHub is a hard dependency of the boxes anyway.
PY_VERSION="${AH_PY_VERSION:-3.14.10}"
PY_PBS_RELEASE="${AH_PY_PBS_RELEASE:-20261124}"
PY_SHA256_LINUX_AMD64="${AH_PY_SHA256:-bfa2f9fe1691f14a98c37e206641058ad7116db117ac924fdcab744987107ad8}"
# TLS alone vouched for the Docker key, the nodesource setup script and sh.rustup.rs
# (R-1800). The two apt keys are checked by fingerprint (both repos sign their
# packages, so apt does the rest), rustup-init by version and sha256 from its archive.
DOCKER_KEY_FPR="9DC858229FC7DD38854AE2D88D81803C0EBFCD88"
NODESOURCE_KEY_FPR="6F71F525282841EEDAF851B42F59B5F99B1BE0B4"
RUSTUP_VERSION="${AH_RUSTUP_VERSION:-1.29.3}"
RUSTUP_SHA256_LINUX_AMD64="${AH_RUSTUP_SHA256:-b1c8cb14e30889e7e2999e6b69e62d9e9b9ffc0f4df8180564d306d9680e6c55}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
# Profile: full (default — everything, for the single-box run.sh incl. desktop GUI
# E2E) | server (docker stack only) | agent (Go agent + packaging). server/agent
# never run Tauri, so they skip the ~18min tauri-cli/rustc compile.
PROFILE="${AH_BOOTSTRAP_PROFILE:-full}"

SUDO=""; [ "$(id -u)" -eq 0 ] || SUDO="sudo"
log() { printf '\n\033[1m[bootstrap] %s\033[0m\n' "$*"; }
# Every download goes through here. The boxes' network is sound (net probe
# 2026-11-26); what broke bakes were single upstream blips, so a failed or
# stalled transfer is retried instead of failing the bootstrap (R-1795, R-1797),
# and a transfer that stops moving ends after a minute instead of hanging the
# run (R-1798). A speed floor, not --max-time: a slow but moving download stays.
# Always to a file (-o): a retry after a partial body would append the whole
# body again behind it on a pipe, and `| bash` would run that.
# Downloads land in a directory of our own: a fixed name under /tmp is one
# another user of the box could plant first.
DL="$(mktemp -d)"
trap 'rm -rf "$DL"' EXIT
# Exactly one key, with the pinned primary fingerprint; a temporary GNUPGHOME
# keeps the box user's keyring out of it.
key_has_fpr() {
  local fprs
  fprs="$(GNUPGHOME="$(mktemp -d -p "$DL")" gpg --batch --show-keys --with-colons "$1" | awk -F: '$1 == "pub" { want = 1; next } want && $1 == "fpr" { print $10; want = 0 }')"
  [ "$fprs" = "$2" ] || { echo "key $1: fingerprint ${fprs:-none}, want $2" >&2; return 1; }
}

dl() {
  curl -fsSL --retry 5 --retry-connrefused --retry-all-errors \
    --connect-timeout 30 --speed-limit 1024 --speed-time 60 "$@"
}
# pip's --retries covers opening a connection, not a read that times out in the
# middle of a wheel (the 2026-11-25 bake) — hence the outer loop.
pip_install() {
  local i
  for i in 1 2 3; do
    $SUDO pip3 install --break-system-packages -q --retries 10 --timeout 60 "$@" && return 0
    log "pip3 install $* failed (attempt $i/3)"
    if [ "$i" -lt 3 ]; then sleep $((i * 10)); fi
  done
  return 1
}

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
    # Same reason for the network: one mirror blip must not fail a lease.
    printf 'Acquire::Retries "5";\nAcquire::http::Timeout "60";\nAcquire::https::Timeout "60";\n' \
        | $SUDO tee /etc/apt/apt.conf.d/99net-retries >/dev/null 2>&1 || true
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
  libayatana-appindicator3-dev libssl-dev libasound2-dev cmake patchelf file \
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

# The services run on the Python of their Dockerfiles (python:3.14-slim) and CI
# tests that; Ubuntu 24.04 ships 3.12. A venv built on 3.12 fails code that uses
# 3.13+ API (SSLSocket.get_unverified_chain: the 2026-11-13 weekly, R-1418).
# run.sh's ensure_venv builds the venv with python3.14 when it is installed.
# Every profile: the bake warms each template with `run.sh unit`.
log "python ${PY_VERSION} from python-build-standalone ${PY_PBS_RELEASE} (the Dockerfiles' Python, for run.sh's venv)"
if [ "$(python3.14 -c 'import ensurepip, platform; print(platform.python_version())' 2>/dev/null || true)" != "$PY_VERSION" ]; then
  py_dir="/opt/ah-python/${PY_VERSION}"
  dl -o "$DL/python.tgz" \
    "https://github.com/astral-sh/python-build-standalone/releases/download/${PY_PBS_RELEASE}/cpython-${PY_VERSION}%2B${PY_PBS_RELEASE}-x86_64-unknown-linux-gnu-install_only.tar.gz"
  echo "${PY_SHA256_LINUX_AMD64}  $DL/python.tgz" | sha256sum -c --quiet -
  $SUDO rm -rf "$py_dir"
  $SUDO mkdir -p "$py_dir"
  $SUDO tar -xzf "$DL/python.tgz" -C "$py_dir" --strip-components=1
  rm -f "$DL/python.tgz"
  $SUDO ln -sfn "$py_dir/bin/python3.14" /usr/local/bin/python3.14
  python3.14 -c 'import ensurepip, ssl, sqlite3, venv' \
    || { echo "python ${PY_VERSION} from ${PY_PBS_RELEASE} does not import ensurepip/ssl/sqlite3/venv" >&2; exit 1; }
fi

# The pipx fallback stays, the `|| true` behind it does not: run.sh dep-gates
# both of these, so a failed install does not go red — it SKIPs, and under
# --strict the box is then reported as unverified for a reason that has nothing
# to do with the tree. A bootstrap that could not install them must say so here.
log "ruff $RUFF_VERSION (Python lint, used by run.sh lint)"
pip_install "ruff==$RUFF_VERSION" \
  || pipx install "ruff==$RUFF_VERSION"
log "pytest $PYTEST_VERSION (used by run.sh unit's vm-pytest step)"
pip_install "pytest==$PYTEST_VERSION" \
  || pipx install "pytest==$PYTEST_VERSION"
# Every profile, like pytest: a lease runs the scripts block, `run.sh unit` or
# `--only scripts` (the bake's warm-up leaves it out, vm.py WARMUP_EXCLUDE). The version is read into a variable, not piped
# into grep -q: under pipefail an early grep exit can fail the pipe.
log "oasdiff ${OASDIFF_VERSION} (used by run.sh's scripts block)"
if [ "$(oasdiff --version 2>/dev/null || true)" != "oasdiff version ${OASDIFF_VERSION}" ]; then
  dl -o "$DL/oasdiff.tgz" \
    "https://github.com/oasdiff/oasdiff/releases/download/v${OASDIFF_VERSION}/oasdiff_${OASDIFF_VERSION}_linux_amd64.tar.gz"
  echo "${OASDIFF_SHA256_LINUX_AMD64}  $DL/oasdiff.tgz" | sha256sum -c -
  tar -C "$DL" -xzf "$DL/oasdiff.tgz" oasdiff
  $SUDO install -m 0755 "$DL/oasdiff" /usr/local/bin/oasdiff
fi

log "docker engine + compose v2 plugin"
if ! command -v docker >/dev/null 2>&1; then
  $SUDO install -m 0755 -d /etc/apt/keyrings
  dl -o "$DL/docker.asc" https://download.docker.com/linux/ubuntu/gpg
  key_has_fpr "$DL/docker.asc" "$DOCKER_KEY_FPR"
  $SUDO gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg "$DL/docker.asc"
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
  dl -o "$DL/go.tgz" "https://go.dev/dl/go${GO_VERSION}.linux-amd64.tar.gz"
  echo "${GO_SHA256_LINUX_AMD64}  $DL/go.tgz" | sha256sum -c -
  $SUDO rm -rf /usr/local/go && $SUDO tar -C /usr/local -xzf "$DL/go.tgz"
  echo 'export PATH=$PATH:/usr/local/go/bin:$HOME/go/bin' | $SUDO tee /etc/profile.d/go.sh >/dev/null
fi
export PATH="$PATH:/usr/local/go/bin:$HOME/go/bin"

log "Node ${NODE_MAJOR}.x"
if ! command -v node >/dev/null 2>&1 || [ "$(node -v | grep -oE '[0-9]+' | head -1)" != "$NODE_MAJOR" ]; then
  # What setup_${NODE_MAJOR}.x writes, without running it: key, deb822 source, and
  # the pin that keeps Ubuntu's own nodejs from winning.
  dl -o "$DL/nodesource.asc" https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key
  key_has_fpr "$DL/nodesource.asc" "$NODESOURCE_KEY_FPR"
  $SUDO gpg --dearmor --yes -o /usr/share/keyrings/nodesource.gpg "$DL/nodesource.asc"
  $SUDO chmod a+r /usr/share/keyrings/nodesource.gpg
  printf 'Types: deb\nURIs: https://deb.nodesource.com/node_%s.x\nSuites: nodistro\nComponents: main\nArchitectures: %s\nSigned-By: /usr/share/keyrings/nodesource.gpg\n' \
    "$NODE_MAJOR" "$(dpkg --print-architecture)" | $SUDO tee /etc/apt/sources.list.d/nodesource.sources >/dev/null
  printf 'Package: nodejs\nPin: origin deb.nodesource.com\nPin-Priority: 600\n' \
    | $SUDO tee /etc/apt/preferences.d/nodejs >/dev/null
  wait_apt_lock
  $SUDO apt-get update -qq
  wait_apt_lock
  $SUDO apt-get install -y nodejs
fi

if [ "$PROFILE" = full ]; then
  log "Rust (rustup stable) + rustfmt + clippy  [full profile only]"
  if ! command -v cargo >/dev/null 2>&1; then
    dl -o "$DL/rustup-init" "https://static.rust-lang.org/rustup/archive/${RUSTUP_VERSION}/x86_64-unknown-linux-gnu/rustup-init"
    echo "${RUSTUP_SHA256_LINUX_AMD64}  $DL/rustup-init" | sha256sum -c -
    chmod +x "$DL/rustup-init"
    "$DL/rustup-init" -y --profile minimal
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
  export CARGO_NET_RETRY=10   # cargo's default is 3 (crates.io blips, R-1797)
  command -v tauri-driver >/dev/null 2>&1 || cargo install tauri-driver --locked \
    || { log "FATAL: tauri-driver install failed — the GUI E2E suites cannot run on this box"; exit 1; }
  # The pinned one, not any: a box that kept an older tauri-cli built the desktop with another
  # CLI than CI and the release (R-1294).
  # clap prints "<name> <version>"; only the version is compared, the name is not pinned down.
  [[ "$(cargo tauri --version 2>/dev/null)" == *" $TAURI_CLI_VERSION" ]] \
    || cargo install tauri-cli --locked --force --version "$TAURI_CLI_VERSION" \
    || { log "FATAL: tauri-cli install failed — the seven desktop_e2e_*.sh suites would all SKIP"; exit 1; }
else
  log "skipping Rust/Tauri toolchain (profile=$PROFILE — no Tauri on this box)"
fi

log "frpc sidecar v${FRP_VERSION} (externalBin must resolve for the Tauri build)"
dl -o "$DL/frpc.tgz" \
  "https://github.com/fatedier/frp/releases/download/v${FRP_VERSION}/frp_${FRP_VERSION}_linux_amd64.tar.gz"
echo "${FRP_SHA256_LINUX_AMD64}  $DL/frpc.tgz" | sha256sum -c -
tar -C "$DL" -xzf "$DL/frpc.tgz"
mkdir -p "$ROOT/apps/desktop/src-tauri/binaries"
cp "$DL/frp_${FRP_VERSION}_linux_amd64/frpc" "$ROOT/apps/desktop/src-tauri/binaries/frpc-x86_64-unknown-linux-gnu"
chmod +x "$ROOT/apps/desktop/src-tauri/binaries/frpc-x86_64-unknown-linux-gnu"

log "done — verify with: bash scripts/tests/run.sh lint"
echo "NOTE: 'docker' group membership takes effect on a new session — the next"
echo "      'vm.py run' will already have it (fresh SSH session)."
