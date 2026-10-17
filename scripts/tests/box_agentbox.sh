#!/usr/bin/env bash
#
# box_agentbox.sh — runs ON an agent box. Installs + provisions the
# agent against the remote server box over a real network hop (cross-host mTLS)
# and prints AGENT_* markers.
#
# Primary path (REPO_FP given): the USER path — scripts/agent-install.sh sets up
# the apt source against the server's :8445 repo plane (GPG-fingerprint-checked),
# installs the .deb the server box built from the same checkout, and provisions
# with a verified first contact (--ca-fp, when CA_FP given). Fallback (no
# REPO_FP, e.g. the server-side repo build failed): build the .deb locally and
# provision with TOFU, as before.
#
# Called by scripts/tests/multibox.sh via `vm.py run`.
#   box_agentbox.sh <SRV_IP> <SID> <PTOK> [REPO_GPG_FP] [CA_FP]
# and, with --docker, one step per call on the provisioned box (R-0419). Each step changes
# Docker, then one agent run pushes the report; it prints AGENT_DOCKER_STEP=OK or what went
# wrong. multibox.sh reads the Docker Health check on the server after each.
#   box_agentbox.sh docker start   stop the agent timer, a running container
#   box_agentbox.sh docker exit    a second container ends with exit 1, no restart policy
#   box_agentbox.sh docker rerun   one more agent run
#   box_agentbox.sh docker down    stop the Docker daemon
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT" || exit 1
# shellcheck source=scripts/vm/lib.sh
. "$(dirname "$0")/../vm/lib.sh"

# The two containers of the docker steps: multibox.sh finds them by name in the details of
# the check.
DOCK_RUN=mb-dock-run; DOCK_EXIT=mb-dock-exit
# The image docker_start picked. Outside the checkout: a later `vm.py run --sync` replaces it.
DOCK_IMAGE_FILE="$HOME/.mb-docker-image"

# docker_image — echoes an image for both containers: busybox from the registry or, when
# the box gets no pull, a scratch image around a static binary built here with the Go of
# the agent profile. Both run on `sleep 86400` and end with exit 1 on `false`.
docker_image() {
  local dir
  if timeout 180 sudo docker pull -q busybox >/dev/null 2>&1; then echo busybox; return 0; fi
  echo "[agentbox] docker: no pull of busybox, building a scratch image" >&2
  dir="$(mktemp -d -p "$HOME")" || return 1
  cat > "$dir/main.go" <<'GO'
package main

import (
	"os"
	"time"
)

func main() {
	if len(os.Args) > 1 && os.Args[1] == "false" {
		os.Exit(1)
	}
	for {
		time.Sleep(time.Hour)
	}
}
GO
  printf 'FROM scratch\nCOPY mb-sleeper /mb-sleeper\nENTRYPOINT ["/mb-sleeper"]\n' > "$dir/Dockerfile"
  if (cd "$dir" && CGO_ENABLED=0 go build -o mb-sleeper main.go) >&2 \
     && sudo docker build -q -t mb-sleeper:local "$dir" >/dev/null; then
    rm -rf "$dir"; echo mb-sleeper:local; return 0
  fi
  rm -rf "$dir"; return 1
}

# docker_start — the timer stops first: its runs would push between the steps and move the
# fail counter the states depend on. docker-ce comes from bootstrap_linux.sh (every profile).
docker_start() {
  local engine image="" state rc=0 timer verdict
  echo "[agentbox] docker: stop the agent timer, start a container that keeps running"
  sudo systemctl stop adminhelper-agent.timer adminhelper-agent.service
  timer="$(systemctl is-active adminhelper-agent.timer 2>/dev/null)"
  engine="$(sudo docker version --format '{{.Server.Version}}' 2>/dev/null)"
  echo "AGENT_DOCKER_ENGINE=${engine:-none}"
  if [ -n "$engine" ] && image="$(docker_image)"; then
    printf '%s\n' "$image" > "$DOCK_IMAGE_FILE"
    sudo docker run -d --name "$DOCK_RUN" "$image" sleep 86400 >/dev/null
  fi
  echo "AGENT_DOCKER_IMAGE=${image:-none}"
  state="$(sudo docker inspect -f '{{.State.Status}}' "$DOCK_RUN" 2>/dev/null)"
  sudo adminhelper-agent run --once || rc=$?
  if [ "$timer" = active ]; then verdict=TIMER_ACTIVE
  elif [ -z "$engine" ]; then verdict=NO_ENGINE
  elif [ -z "$image" ]; then verdict=NO_IMAGE
  elif [ "$state" != running ]; then verdict=NOT_RUNNING
  elif [ "$rc" != 0 ]; then verdict=RUN_FAILED
  else verdict=OK; fi
  echo "AGENT_DOCKER_STEP=$verdict"
  [ "$verdict" = OK ] || echo "    timer ${timer:-unknown}, $DOCK_RUN ${state:-missing}, agent run exit $rc"
}

# docker_exit — in the foreground: docker run returns once the container has ended.
docker_exit() {
  local image ended policy state rc=0 verdict
  echo "[agentbox] docker: a second container ends with exit 1, no restart policy"
  image="$(cat "$DOCK_IMAGE_FILE" 2>/dev/null)"
  [ -n "$image" ] && sudo docker run --name "$DOCK_EXIT" "$image" false
  ended="$(sudo docker inspect -f '{{.State.Status}} {{.State.ExitCode}}' "$DOCK_EXIT" 2>/dev/null)"
  policy="$(sudo docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' "$DOCK_EXIT" 2>/dev/null)"
  state="$(sudo docker inspect -f '{{.State.Status}}' "$DOCK_RUN" 2>/dev/null)"
  sudo adminhelper-agent run --once || rc=$?
  if [ "$ended" != "exited 1" ]; then verdict=NOT_EXITED
  elif [ "$policy" != no ] && [ -n "$policy" ]; then verdict=RESTART_POLICY
  elif [ "$state" != running ]; then verdict=NOT_RUNNING
  elif [ "$rc" != 0 ]; then verdict=RUN_FAILED
  else verdict=OK; fi
  echo "AGENT_DOCKER_STEP=$verdict"
  [ "$verdict" = OK ] || echo "    $DOCK_EXIT ${ended:-missing}, policy ${policy:-none}; $DOCK_RUN ${state:-missing}; agent run exit $rc"
}

docker_rerun() {
  local rc=0
  sudo adminhelper-agent run --once || rc=$?
  if [ "$rc" = 0 ]; then echo "AGENT_DOCKER_STEP=OK"; else echo "AGENT_DOCKER_STEP=RUN_FAILED"; fi
}

# docker_down — the socket too: socket activation would start the daemon again on the
# agent's next docker call. Checked after the agent run, which made that call.
docker_down() {
  local rc=0 verdict
  echo "[agentbox] docker: stop the daemon and its socket"
  sudo systemctl stop docker.socket docker.service
  sudo adminhelper-agent run --once || rc=$?
  if sudo docker info >/dev/null 2>&1; then verdict=STILL_UP
  elif [ "$rc" != 0 ]; then verdict=RUN_FAILED
  else verdict=OK; fi
  echo "AGENT_DOCKER_STEP=$verdict"
}

if [ "${1:-}" = docker ]; then
  export PATH="$PATH:/usr/local/go/bin"
  case "${2:-}" in
    start) docker_start ;;
    exit)  docker_exit ;;
    rerun) docker_rerun ;;
    down)  docker_down ;;
    *) echo "unknown docker step: ${2:-}"; exit 2 ;;
  esac
  exit 0
fi

SRV_IP="${1:?}"; SID="${2:?}"; PTOK="${3:?}"; REPO_FP="${4:-}"; CA_FP="${5:-}"

echo "[agentbox] hydrate (agent profile: Go + packaging, no Tauri)"
AH_BOOTSTRAP_PROFILE=agent bash scripts/vm/bootstrap_linux.sh || { echo "[agentbox] bootstrap failed"; exit 1; }
export PATH="$PATH:/usr/local/go/bin"

if [ -n "$REPO_FP" ]; then
  echo "[agentbox] install via scripts/agent-install.sh over the :8445 repo plane (user path)"
  ARGS=(--server "https://$SRV_IP" --token "$PTOK" --server-id "$SID" --gpg-fp "$REPO_FP")
  [ -n "$CA_FP" ] && ARGS+=(--ca-fp "$CA_FP")
  sudo bash scripts/agent-install.sh "${ARGS[@]}" \
    && echo "AGENT_PROVISION_OK" || { echo "AGENT_PROVISION_FAIL"; exit 1; }
  # Prove the package really came through the repo plane and the steady state
  # got hardened (CAInfo pin after enrollment).
  grep -q "URIs: https://$SRV_IP:8445/apt" /etc/apt/sources.list.d/adminhelper.sources 2>/dev/null \
    && echo "AGENT_REPO_OK" || echo "AGENT_REPO_MISSING"
  grep -q "CAInfo" /etc/apt/apt.conf.d/99adminhelper-ca 2>/dev/null \
    && echo "AGENT_CAFLIP_OK" || echo "AGENT_CAFLIP_MISSING"
else
  echo "[agentbox] no repo fingerprint from the server box — legacy local .deb path"
  echo "[agentbox] build the Go agent + .deb from the repo root"
  DEB="$(vm_build_agent_deb agentbox)" || exit 1
  echo "AGENT_DEB=$DEB"

  echo "[agentbox] install + provision against https://$SRV_IP (server $SID)"
  sudo apt-get install -y -o DPkg::Lock::Timeout=300 "$DEB" 2>/dev/null || sudo dpkg -i "$DEB" || { echo "[agentbox] install failed"; exit 1; }
  # --insecure = TOFU-pin the presented chain on first contact; the agent then pins
  # the CA from the enroll response and verifies the IP-SAN leaf on every later call.
  sudo adminhelper-agent provision --url "https://$SRV_IP" --token "$PTOK" --server-id "$SID" --insecure \
    && echo "AGENT_PROVISION_OK" || { echo "AGENT_PROVISION_FAIL"; exit 1; }
fi

echo "[agentbox] one monitoring collection run"
sudo adminhelper-agent run --once && echo "AGENT_RUN_OK" || echo "AGENT_RUN_FAIL"

echo "[agentbox] assert enrolled mTLS identity present"
if sudo test -s /etc/adminhelper/identity/agent.crt; then
  echo "AGENT_CERT_OK"
else
  echo "AGENT_CERT_MISSING"
fi
