#!/usr/bin/env bash
#
# crabbox_bootstrap.sh — hydrate a fresh crabbox box (Ubuntu 24.04) with every
# toolchain the heavy AdminHelper suites need, then it can run
# `bash scripts/tests/run.sh all`. Idempotent-ish: safe to re-run.
#
# Runs ON THE BOX, e.g.:
#   crabbox run --id <slug> -- 'bash scripts/tests/crabbox_bootstrap.sh'
# Run as the (non-root) crabbox user: apt/docker steps use `sudo` internally,
# while rustup/cargo install run as the user so cargo lands in ~/.cargo (not
# root's). The crabbox user needs passwordless sudo (crabbox templates provide it).
#
# Mirrors the dependency setup in .github/workflows/ci.yml so the box matches CI.

set -euo pipefail

FRP_VERSION="${AH_FRP_VERSION:-0.69.1}"
FRP_SHA256_LINUX_AMD64="7be257b72dbbc60bcb3e0e25a5afd1dfac7b63f897084864d3c956dd3d5674e1"
GO_VERSION="${AH_GO_VERSION:-1.25.0}"
NODE_MAJOR="${AH_NODE_MAJOR:-22}"
TAURI_CLI_VERSION="${AH_TAURI_CLI_VERSION:-2.11.2}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
# Profile: full (default — everything, for the single-box run.sh incl. desktop GUI
# E2E) | server (docker stack only) | agent (Go agent + packaging). server/agent
# never run Tauri, so they skip the ~18min tauri-cli/rustc compile.
PROFILE="${AH_BOOTSTRAP_PROFILE:-full}"

SUDO=""; [ "$(id -u)" -eq 0 ] || SUDO="sudo"
log() { printf '\n\033[1m[bootstrap] %s\033[0m\n' "$*"; }

log "apt base + tauri libs + display + repo-build + keyring tooling"
export DEBIAN_FRONTEND=noninteractive
$SUDO apt-get update -qq
$SUDO apt-get install -y --no-install-recommends \
  ca-certificates curl git rsync openssl gnupg jq unzip build-essential pkg-config \
  python3 python3-pip python3-venv shellcheck \
  libgtk-3-dev libwebkit2gtk-4.1-dev librsvg2-dev libxdo-dev \
  libayatana-appindicator3-dev libssl-dev patchelf file \
  xvfb webkit2gtk-driver at-spi2-core dbus-x11 gnome-keyring \
  minisign dpkg-dev apt-utils createrepo-c rpm locales

log "generate a valid UTF-8 locale (headless boxes default to C — breaks Intl.NumberFormat in the desktop webview -> blank app)"
$SUDO locale-gen en_US.UTF-8 >/dev/null 2>&1 || true
$SUDO update-locale LANG=en_US.UTF-8 >/dev/null 2>&1 || true

log "ruff (Python lint, used by run.sh lint)"
$SUDO pip3 install --break-system-packages -q ruff || pipx install ruff || true

log "docker engine + compose v2 plugin"
if ! command -v docker >/dev/null 2>&1; then
  $SUDO install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | $SUDO gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  $SUDO chmod a+r /etc/apt/keyrings/docker.gpg
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    | $SUDO tee /etc/apt/sources.list.d/docker.list >/dev/null
  $SUDO apt-get update -qq
  $SUDO apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
$SUDO systemctl enable --now docker 2>/dev/null || true
$SUDO usermod -aG docker "${SUDO_USER:-$USER}" || true   # effective on next login/session

log "Go ${GO_VERSION}"
if ! command -v go >/dev/null 2>&1 || ! go version | grep -q "$GO_VERSION"; then
  curl -fsSL -o /tmp/go.tgz "https://go.dev/dl/go${GO_VERSION}.linux-amd64.tar.gz"
  $SUDO rm -rf /usr/local/go && $SUDO tar -C /usr/local -xzf /tmp/go.tgz
  echo 'export PATH=$PATH:/usr/local/go/bin:$HOME/go/bin' | $SUDO tee /etc/profile.d/go.sh >/dev/null
fi
export PATH="$PATH:/usr/local/go/bin:$HOME/go/bin"

log "Node ${NODE_MAJOR}.x"
if ! command -v node >/dev/null 2>&1 || [ "$(node -v | grep -oE '[0-9]+' | head -1)" != "$NODE_MAJOR" ]; then
  curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | $SUDO -E bash -
  $SUDO apt-get install -y nodejs
fi

if [ "$PROFILE" = full ]; then
  log "Rust (rustup stable) + rustfmt + clippy  [full profile only]"
  if ! command -v cargo >/dev/null 2>&1; then
    curl -fsSL https://sh.rustup.rs | sh -s -- -y --profile minimal
  fi
  # shellcheck disable=SC1091
  [ -f "$HOME/.cargo/env" ] && . "$HOME/.cargo/env"
  rustup component add rustfmt clippy 2>/dev/null || true

  log "tauri-driver + tauri-cli ${TAURI_CLI_VERSION} (for desktop build + GUI E2E)  [full profile only]"
  command -v tauri-driver >/dev/null 2>&1 || cargo install tauri-driver --locked || true
  cargo tauri --version >/dev/null 2>&1 || cargo install tauri-cli --locked --version "$TAURI_CLI_VERSION" || true
else
  log "skipping Rust/Tauri toolchain (profile=$PROFILE — no Tauri on this box)"
fi

log "frpc sidecar v${FRP_VERSION} (externalBin must resolve for the Tauri build)"
curl -fsSL -o /tmp/frpc.tgz \
  "https://github.com/fatedier/frp/releases/download/v${FRP_VERSION}/frp_${FRP_VERSION}_linux_amd64.tar.gz"
echo "${FRP_SHA256_LINUX_AMD64}  /tmp/frpc.tgz" | sha256sum -c -
tar -C /tmp -xzf /tmp/frpc.tgz
mkdir -p "$ROOT/apps/desktop/src-tauri/binaries"
cp "/tmp/frp_${FRP_VERSION}_linux_amd64/frpc" "$ROOT/apps/desktop/src-tauri/binaries/frpc-x86_64-unknown-linux-gnu"
chmod +x "$ROOT/apps/desktop/src-tauri/binaries/frpc-x86_64-unknown-linux-gnu"

log "done — verify with: bash scripts/tests/run.sh lint"
echo "NOTE: 'docker' group membership takes effect on a new session — a subsequent"
echo "      'crabbox run' invocation will already have it (fresh SSH session)."
