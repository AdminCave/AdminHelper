#!/usr/bin/env bash
#
# box_serverbox.sh — runs ON the server box. Brings up the full stack
# reachable at https://<SRV_IP> on the production ports (443/8444/8445 + frps
# 7000/7443), seeds an admin, a server record and a provision token, and prints
#   MB_SID=<server-uuid> MB_PTOK=<provision-token>
# on stdout for the orchestrator to hand to the agent box.
#
# Called by scripts/tests/multibox.sh via `vm.py run`. After the bring-up, the
# --tunnel stage of R-0411 watches frps under its supervisor, one mode per step:
#   box_serverbox.sh frps-mark                      the supervisor before a config change
#   box_serverbox.sh frps-restart <mark> <tunnel…>  after it: one restart, the tunnels back
# and, once the tunnel box is up, that frps has no way out of its network:
#   box_serverbox.sh frps-egress <ip> <port>        frps cannot reach it, the server can
set -uo pipefail

# ── frps under its supervisor (R-0411) ──────────────────────────────────────────
# Seen as integration_stack_test.sh 11b sees it: the supervisor's status file where the
# server reads it, and the pid of frps in its container, both through the mb-dc of the
# bring-up. Every wait is a bounded number of tries a second apart, and ends in a verdict.

# tries <n> <command…> — the command up to n times, a second apart, until it succeeds.
tries() {
  local n="$1" i; shift
  for i in $(seq 1 "$n"); do
    "$@" && return 0
    [ "$i" -lt "$n" ] && sleep 1
  done
  return 1
}

# sv_file mark | state | heartbeat | since <boot> <seq> | at <boot> <seq> — from the status
# file. mark: "<boot>:<last seq>"; since: "=" followed by the events after <seq> as
# <event>/<reason>/<tokenChanged>, joined by "+", or "rebooted" when the supervisor has
# started anew; at: one second before the first of those events, for `logs --since`. Empty
# when the file cannot be read, so that no comparison passes on it.
sv_file() {
  mb-dc exec -T server cat /app/frps-state/status.json 2>/dev/null | python3 -c '
import datetime, json, sys
s, what = json.load(sys.stdin), sys.argv[1]
events = s["events"]
if what == "mark":
    print("%s:%d" % (s["boot"], events[-1]["seq"] if events else 0))
elif what in ("since", "at"):
    boot, seq = sys.argv[2], int(sys.argv[3])
    new = [e for e in events if e["seq"] > seq]
    if what == "since":
        print("rebooted" if boot != s["boot"] else "=" + "+".join(
            "%s/%s/%s" % (e["event"], e["reason"], str(e["tokenChanged"]).lower()) for e in new))
    elif boot == s["boot"] and new:
        at = datetime.datetime.strptime(new[0]["at"], "%Y-%m-%dT%H:%M:%SZ")
        print((at - datetime.timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ"))
else:
    print(s[what])' "$@" 2>/dev/null
}

# frps_pid — the pid of frps in its container, empty when none runs; non-zero when the exec or
# pidof fails otherwise, so that "no process" never rests on an error.
frps_pid() {
  local out
  # shellcheck disable=SC2016 # expanded by the container's sh
  out="$(mb-dc exec -T frps sh -c 'pids=$(pidof frps); echo "rc=$? $pids"' 2>/dev/null)" || return 2
  case "$out" in
    "rc=0 "?*) echo "${out#rc=0 }" ;;
    "rc=1 ") ;;
    *) return 2 ;;
  esac
}

frps_running() { [ "$(sv_file state)" = running ] && [ -n "$(frps_pid)" ]; }

# sv_has_new <boot> <seq> — the supervisor wrote an event since then, or started anew.
sv_has_new() { local s; s="$(sv_file since "$1" "$2")"; [ -n "$s" ] && [ "$s" != "=" ]; }

# wait_polls <n> — until the supervisor has rewritten its status n more times (once a poll,
# 5 s apart). A change takes one poll to be noted and the next to be taken over, so a second
# event can only come with a later poll than the first: the events are read after these.
wait_polls() {
  local last now seen=0
  last="$(sv_file heartbeat)"
  for _ in $(seq 1 $((10 * $1 + 10))); do
    sleep 1
    now="$(sv_file heartbeat)"
    if [ -n "$now" ] && [ -n "$last" ] && [ "$now" != "$last" ]; then seen=$((seen + 1)); fi
    [ -n "$now" ] && last="$now"
    [ "$seen" -ge "$1" ] && return 0
  done
  return 1
}

# tunnels_back <since> <tunnel…> — frps logged the STCP registration of every tunnel since
# then, in the line multibox.sh frps_registered reads; MISSING names the ones it did not.
tunnels_back() {
  local since="$1" log t; shift
  log="$(mb-dc logs --no-color --since "$since" frps 2>/dev/null)"
  MISSING=""
  for t in "$@"; do
    grep -qE "new proxy \[[^]]*\.$t\] type \[stcp\] success" <<<"$log" || MISSING="${MISSING:+$MISSING+}$t"
  done
  [ -z "$MISSING" ]
}

# A boot id as the supervisor writes it and the server's reader (supervisor_status.py) wants it.
BOOT_ID='^[0123456789abcdef]{16}$'

# step_frps_mark — before the config change: the supervisor runs frps. Prints
# MB_FRPS_MARK=<boot>:<seq>:<pid>, what step_frps_restart holds the change against.
step_frps_mark() {
  local mark state pid
  mark="$(sv_file mark)"; state="$(sv_file state)"; pid="$(frps_pid)" || pid=""
  if [[ "${mark%%:*}" =~ $BOOT_ID ]] && [ "$state" = running ] && [[ "$pid" =~ ^[0123456789]+$ ]]; then
    echo "MB_FRPS_MARK=$mark:$pid"
  else
    echo "MB_FRPS_MARK_FAIL"; echo "    supervisor ${mark:-unreadable}, state ${state:-unknown}, frps pid ${pid:-none}"
  fi
}

# step_frps_restart <mark> <tunnel…> — after the change. MB_FRPS_RESTART: frps restarted
# exactly once for it — the supervisor wrote one event since the mark, applied without a new
# token, read two polls after the first event appeared; its log shows one start of frps since
# then and no exit (a frps that ends on its own is started again after 2 s without an event,
# crashed comes only with the third exit in 60 s); and frps runs as a new process, the one
# that ran when the event appeared. MB_FRPS_TUNNELS: the agent's frpc logged in again by
# itself, frps registered every tunnel anew after that event. 60 tries for the event, 30 for
# the polls, 120 for the logins.
step_frps_restart() {
  local boot seq pid_before events="" pid_first="" pid_after="" verdict at="" log starts="-" exits="-" back
  IFS=: read -r boot seq pid_before <<<"$1"; shift
  if ! [[ "$boot" =~ $BOOT_ID ]] || ! [[ "$seq" =~ ^[0123456789]+$ ]] || ! [[ "$pid_before" =~ ^[0123456789]+$ ]]; then
    verdict=NO_MARK
  elif ! tries 60 sv_has_new "$boot" "$seq"; then
    verdict=NO_EVENT
  else
    pid_first="$(frps_pid)" || pid_first=""
    if ! wait_polls 2; then
      verdict=NO_POLL
    else
      events="$(sv_file since "$boot" "$seq")"
      at="$(sv_file at "$boot" "$seq")"
      log=""
      [ -z "$at" ] || log="$(mb-dc logs --no-color --since "$at" frps 2>/dev/null)"
      # The supervisor's own lines (frps-supervisor.sh start_frps, check_frps).
      starts="$(grep -cF '[frps-supervisor] frps started from ' <<<"$log")"
      exits="$(grep -cF '[frps-supervisor] frps exited (' <<<"$log")"
      pid_after="$(frps_pid)" || pid_after=""
      if [ "$events" = rebooted ]; then
        verdict=REBOOTED
      elif [ "$events" != "=applied/none/false" ]; then
        verdict=EVENTS
      elif [ "$exits" != 0 ] || [ "$starts" -gt 1 ]; then
        verdict=CRASHED
      elif [ "$starts" = 0 ]; then
        verdict=NO_START_LOG
      elif ! [[ "$pid_after" =~ ^[0123456789]+$ ]]; then
        verdict=NO_FRPS
      elif [ "$pid_after" = "$pid_before" ]; then
        verdict=SAME_PID
      elif [ "$pid_after" != "$pid_first" ]; then
        verdict=CRASHED
      else
        verdict=OK
      fi
    fi
  fi
  echo "MB_FRPS_RESTART=$verdict"
  [ -n "$events" ] || [ "$verdict" = NO_MARK ] || events="$(sv_file since "$boot" "$seq")"
  events="${events#=}"
  echo "MB_FRPS_SEEN=events:${events:-none},pid:${pid_before:-none}-${pid_first:-none}-${pid_after:-none},starts:$starts,exits:$exits"
  [ -n "$at" ] || [ "$verdict" = NO_MARK ] || at="$(sv_file at "$boot" "$seq")"
  if [ -z "$at" ]; then
    back=NO_RESTART
  elif tries 120 tunnels_back "$at" "$@"; then
    back=OK
  else
    back="MISSING:$MISSING"
  fi
  echo "MB_FRPS_TUNNELS=$back"
  if [ "$verdict" != OK ] || [ "$back" != OK ]; then
    mb-dc logs --no-color --tail 20 frps 2>/dev/null | sed 's/^/    frps: /'
  fi
}

# ── frps without a way out (frpedge) ───────────────────────────────────────────
# frpedge runs without IP masquerading (docker-compose.yml): a connection frps opens leaves
# the box with the container's own address, and no other host answers it. The same
# connection from the server container, whose network masquerades, shows the target is up.

# egress_frps <ip> <port> — open, blocked or error: nc -z in the frps container. The image's
# nc (OpenBSD) says nothing on a failed connect without -v, so blocked is exit 1 without a
# word; no nc, a usage line or a failed exec is an error, so that blocked never rests on one.
egress_frps() {
  local out
  # shellcheck disable=SC2016 # expanded by the container's sh
  out="$(mb-dc exec -T frps sh -c 'err=$(nc -z -w3 "$1" "$2" 2>&1); echo "rc=$? $err"' sh "$1" "$2" 2>/dev/null)" \
    || { echo error; return; }
  case "$out" in
    "rc=0 "*) echo open ;;
    "rc=1 ") echo blocked ;;
    *) echo error ;;
  esac
}

# egress_server <ip> <port> — open, closed or error: the same connection from the server
# container; no answer from its python is an error.
egress_server() {
  local out
  out="$(mb-dc exec -T server python -c '
import socket, sys
try:
    socket.create_connection((sys.argv[1], int(sys.argv[2])), 3).close()
except OSError:
    print("closed")
else:
    print("open")' "$1" "$2" 2>/dev/null)"
  case "$out" in
    open|closed) echo "$out" ;;
    *) echo error ;;
  esac
}

# step_frps_egress <ip> <port> — MB_FRPS_EGRESS=frps:<…>,server:<…>, both results in one
# line; exit 0 only for frps:blocked,server:open.
step_frps_egress() {
  local frps server
  frps="$(egress_frps "$1" "$2")"; server="$(egress_server "$1" "$2")"
  echo "MB_FRPS_EGRESS=frps:$frps,server:$server"
  [ "$frps" = blocked ] && [ "$server" = open ]
}

case "${1:-}" in
  frps-mark)    cd "$(dirname "$0")/../.." || exit 1; step_frps_mark; exit 0 ;;
  frps-restart) cd "$(dirname "$0")/../.." || exit 1; step_frps_restart "${2:?}" "${3:?}" "${@:4}"; exit 0 ;;
  frps-egress)  cd "$(dirname "$0")/../.." || exit 1; step_frps_egress "${2:?}" "${3:?}"; exit $? ;;
esac

SRV_IP="${1:?usage: box_serverbox.sh <server-ip> [tunnel] [moncheck <SMTP_IP>]}"; shift || true
# Independent, composable modes (so the S6 capstone can do BOTH at once):
#   tunnel            S4: seed an STCP tunnel + wait for frps to run from its config
#   moncheck <IP>     S5: seed ping checks + an email alert to the mailhog sink <IP>
DO_TUNNEL=0; DO_MONCHECK=0; DO_ENFORCE=0; SMTP_IP=""; SMTP_CA_B64=""
while [ $# -gt 0 ]; do case "$1" in
  tunnel)   DO_TUNNEL=1 ;;
  moncheck) DO_MONCHECK=1; SMTP_IP="${2:-}"; SMTP_CA_B64="${3:-}"; shift 2 ;;
  enforce)  DO_ENFORCE=1 ;;   # S5-hardening (D2): MTLS_ENFORCE=true + cert-based seed
  *) ;; esac; shift; done
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT" || exit 1

echo "[serverbox] hydrate (server profile: docker stack, no Tauri)"
AH_BOOTSTRAP_PROFILE=server bash scripts/vm/bootstrap_linux.sh || { echo "[serverbox] bootstrap failed"; exit 1; }

echo "[serverbox] .env: DOMAIN=$SRV_IP (IP-SAN gateway+frps leaf), MTLS_ENFORCE=$([ "$DO_ENFORCE" = 1 ] && echo true || echo false), admin pw"
[ -f .env ] || cp .env.example .env
bash scripts/init-secrets.sh || true
ADMIN_PW="$(openssl rand -hex 16)"
upsert() { if grep -qE "^#?[[:space:]]*$1=" .env; then sed -i -E "s|^#?[[:space:]]*$1=.*|$1=$2|" .env; else printf '%s=%s\n' "$1" "$2" >> .env; fi; }
# DOMAIN must be set BEFORE first `up` — the ca-issuer mints the gateway leaf SAN once.
upsert DOMAIN "$SRV_IP"
upsert EXTRA_SANS "$SRV_IP"
upsert FRP_SERVER_ADDR "$SRV_IP"
upsert MTLS_ENFORCE "$([ "$DO_ENFORCE" = 1 ] && echo true || echo false)"
upsert ADMIN_PASSWORD "$ADMIN_PW"

# The test overlay supplies build: contexts but drops the :8445 plane and moves
# :443 to a high port — restore the production gateway ports on top.
cat > /tmp/mb-ports.yml <<'YML'
services:
  gateway:
    ports: !override
      - "443:443"
      - "8444:8444"
      - "8445:8445"
YML

DC=(sudo docker compose -f docker-compose.yml -f docker-compose.test.yml -f /tmp/mb-ports.yml)
# Expose the exact compose invocation as `mb-dc` so the orchestrator's log-greps
# don't have to hard-code this box's compose-file set (an implicit contract that
# breaks silently if the overlay is renamed or a 4th file is added) (1.49).
printf '#!/bin/sh\nexec sudo docker compose -f docker-compose.yml -f docker-compose.test.yml -f /tmp/mb-ports.yml "$@"\n' \
  | sudo tee /usr/local/bin/mb-dc >/dev/null && sudo chmod +x /usr/local/bin/mb-dc
echo "[serverbox] build + up (images from checkout, production ports)"
# Start ONLY the services the stages need (+their deps auto-start); `scheduler` stays
# out. frps is built from apps/frps (the test overlay) and comes up before any FRP
# config exists: its supervisor waits for one and starts frps from it by itself, so
# frps has no `up` of its own below (R-0411).
"${DC[@]}" up -d --build gateway server ca-issuer monitoring frps \
  || { echo "[serverbox] compose up failed"; "${DC[@]}" ps; exit 1; }

echo "[serverbox] wait for the gateway data plane on :443"
up=0; for _ in $(seq 1 60); do curl -sk --max-time 5 "https://localhost/" >/dev/null 2>&1 && { up=1; break; }; sleep 3; done
[ "$up" = 1 ] || { echo "[serverbox] gateway never came up"; "${DC[@]}" logs --tail 30 gateway ca-issuer server; exit 1; }

# Enforce mode (D2): the data plane (:443) now requires a client cert, so the seed
# below must present one. Enroll an admin cert on the certless enroll plane (:8444,
# mirrors integration_stack_test), and prove a certless :443 request is rejected.
if [ "$DO_ENFORCE" = 1 ]; then
  echo "[serverbox] enforce: enroll an admin client cert (:8444) + assert certless :443 is rejected"
  # The admin user is created by the startup lifespan only AFTER Alembic migration,
  # so minting can be too early right after gateway-up — retry (like integration_stack_test).
  ETOK=""
  for _ in $(seq 1 45); do
    ETOK="$("${DC[@]}" exec -T server python -m app.cli mint-enroll-token --username admin 2>/dev/null | tr -d '\r\n')"
    [ -n "$ETOK" ] && break; sleep 2
  done
  [ -n "$ETOK" ] || { echo "[serverbox] mint-enroll-token failed (admin not ready)"; exit 1; }
  openssl ecparam -name prime256v1 -genkey -noout -out /tmp/mb-admin.key 2>/dev/null
  openssl req -new -key /tmp/mb-admin.key -subj "/CN=mb-admin" -out /tmp/mb-admin.csr 2>/dev/null
  python3 - "$ETOK" <<'PY'
import json, ssl, sys, urllib.request
tok = sys.argv[1]; csr = open("/tmp/mb-admin.csr").read()
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
req = urllib.request.Request("https://localhost:8444/enroll",
    data=json.dumps({"token": tok, "csr": csr}).encode(), headers={"Content-Type": "application/json"})
open("/tmp/mb-admin-fullchain.pem", "w").write(json.load(urllib.request.urlopen(req, context=ctx, timeout=20))["fullchain"])
PY
  [ -s /tmp/mb-admin-fullchain.pem ] || { echo "[serverbox] admin enroll failed"; exit 1; }
  code="$(curl -k -s -o /dev/null -w '%{http_code}' --max-time 5 "https://localhost/api/auth/me" 2>/dev/null || echo 000)"
  [ "$code" = 400 ] && echo "MB_ENFORCE_CERTLESS_REJECTED=1" || echo "MB_ENFORCE_CERTLESS_REJECTED=0 (got $code)"
  export AH_CERT=/tmp/mb-admin-fullchain.pem AH_KEY=/tmp/mb-admin.key
  # The desktop box needs enrollment tokens too (cert-gated :443), but NOT from
  # here: they live 60 minutes by default and the desktop stage starts hours
  # later, after the agent, rpm, tunnel and visitor boxes. The orchestrator mints
  # them just before that stage instead (multibox.sh).
fi

echo "[serverbox] seed admin JWT -> server record -> provision token"
export ADMIN_PW SRV_IP DO_TUNNEL
OUT="$(python3 - <<'PY'
import json, ssl, os, time, urllib.request
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
if os.environ.get("AH_CERT"):  # enforce mode: present the enrolled admin client cert
    ctx.load_cert_chain(os.environ["AH_CERT"], os.environ.get("AH_KEY"))
base = "https://localhost"
def call(method, path, tok=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method, headers={"Content-Type": "application/json"})
    if tok: req.add_header("Authorization", "Bearer " + tok)
    return json.load(urllib.request.urlopen(req, context=ctx, timeout=20))
tok = ""
for _ in range(45):  # admin is created by the startup lifespan after Alembic
    try:
        tok = call("POST", "/api/auth/login", body={"username": "admin", "password": os.environ["ADMIN_PW"]})["access_token"]; break
    except Exception: time.sleep(2)
if not tok: raise SystemExit("login failed")
sid = call("POST", "/api/servers", tok, {"name": "mb-agent", "hostname": "mb-agent.local"})["id"]
ptok = call("POST", f"/api/servers/{sid}/provision/token", tok, {})["token"]
# A second server + token for the cross-distro (rpm) agent so it enrolls as its own
# identity — no shared/one-shot provision-token conflict with the deb agent (S2).
sid2 = call("POST", "/api/servers", tok, {"name": "mb-agent-rpm", "hostname": "mb-agent-rpm.local"})["id"]
ptok2 = call("POST", f"/api/servers/{sid2}/provision/token", tok, {})["token"]
print(f"MB_SID={sid} MB_PTOK={ptok} MB_SID2={sid2} MB_PTOK2={ptok2}")
# Tunnel mode (S4): an FRP config pointing at THIS server's IP + an STCP tunnel
# exposing the tunnel-agent's own sshd (:22). Creating the config writes frps.toml
# into the shared volume, and the supervisor in the frps container starts frps from
# it. The agent provisions against MB_TUN_* and its frpc.toml (fetched for these
# tunnels) runs the STCP server.
if os.environ.get("DO_TUNNEL") == "1":
    srv_ip = os.environ["SRV_IP"]
    tsid = call("POST", "/api/servers", tok, {"name": "mb-tunnel", "hostname": "mb-tunnel.local"})["id"]
    tptok = call("POST", f"/api/servers/{tsid}/provision/token", tok, {})["token"]
    cfg = call("POST", "/api/frp/server-config", tok, {"name": "mb-frps", "server_addr": srv_ip, "bind_port": 7000})["id"]
    call("POST", "/api/frp/tunnels", tok, {"server_id": tsid, "frp_config_id": cfg, "name": "mb-ssh", "tunnel_type": "stcp", "protocol": "ssh", "local_port": 22})
    # A visitor server+token (its provisioned tunnel-scoped cert is CA-signed -> frps
    # accepts it for the visitor's TLS) + the generated visitor.toml for the container.
    vsid = call("POST", "/api/servers", tok, {"name": "mb-visitor", "hostname": "mb-visitor.local"})["id"]
    vptok = call("POST", f"/api/servers/{vsid}/provision/token", tok, {})["token"]
    import base64
    vreq = urllib.request.Request(base + "/api/frp/generate/visitor-toml", headers={"Authorization": "Bearer " + tok})
    vtoml = urllib.request.urlopen(vreq, context=ctx, timeout=20).read()
    print(f"MB_TUN_SID={tsid} MB_TUN_PTOK={tptok} MB_CFG={cfg} MB_VIS_SID={vsid} MB_VIS_PTOK={vptok}")
    print("MB_VISITOR_B64=" + base64.b64encode(vtoml).decode())
PY
)" || { echo "[serverbox] seeding failed"; exit 1; }
echo "$OUT"
# Also hand the desktop-capstone box what it needs to log in + inject SSE events.
echo "MB_ADMIN_PW=$ADMIN_PW"
echo "MB_MONITOR_KEY=$(grep -E '^MONITOR_API_KEY=' .env | head -1 | cut -d= -f2-)"

# Signed test package repo on the :8445 plane: build the agent .deb/.rpm from
# THIS checkout, sign the repo with a throwaway key, and drop it into ./repo —
# the gateway's read-only bind mount (nginx checks the root per request, no
# restart needed). Agent boxes then install through scripts/agent-install.sh
# over the real repo plane, exactly like a user host (dogfooding).
echo "[serverbox] build agent packages + signed test repo for :8445"
# shellcheck source=scripts/vm/lib.sh
. scripts/vm/lib.sh
export PATH="$PATH:/usr/local/go/bin"
REPO_FP=""
if DEB="$(vm_build_agent_deb serverbox)"; then
  # The Go that built the binary both packages ship, read from the binary itself:
  # multibox.sh prints it beside its verdict.
  echo "MB_AGENT_GO=$(go version apps/agent/bin/adminhelper-agent 2>/dev/null | awk '{print $2}')"
  # Old-Debian regression guard on a debian:9 (Stretch) container — the exact
  # dpkg 1.18 + glibc 2.24 environment that failed on UniFi/appliance firmware.
  # Catches TWO distinct breaks that the all-modern build/test fleet hid, both of
  # which shipped to real users:
  #   1. .deb member compression: dpkg-deb --info/--contents reads control.tar +
  #      data.tar — fails on zstd (needs xz), the v0.43.0 break.
  #   2. binary glibc linkage: extract + RUN adminhelper-agent — a dynamically
  #      linked binary (CGO_ENABLED=1) fails with "GLIBC_2.34 not found", the
  #      v0.43.1 break. Only executing it on old glibc surfaces this.
  # Mirrors the rpm cross-distro test (rockylinux:8). Skips (not fails) if the
  # archived image can't pull.
  if sudo docker pull -q debian:9 >/dev/null 2>&1; then
    if sudo docker run --rm -v "$(realpath "$DEB"):/tmp/pkg.deb:ro" debian:9 sh -c '
         set -e
         dpkg-deb --info /tmp/pkg.deb >/dev/null      # control.tar readable?
         dpkg-deb --contents /tmp/pkg.deb >/dev/null   # data.tar readable?
         dpkg-deb --fsys-tarfile /tmp/pkg.deb | tar -xO ./usr/bin/adminhelper-agent > /tmp/ah
         chmod +x /tmp/ah
         /tmp/ah version >/dev/null                    # runs on glibc 2.24 (static)?
       ' 2>/dev/null; then
      echo "MB_DEB_OLDDPKG_OK=1"
    else
      echo "MB_DEB_OLDDPKG_OK=0"
    fi
  else
    echo "[serverbox] debian:9 image unavailable — skipping the old-Debian install+run check"
  fi
  # rpm forbids '-' in Version (0.0.0, not 0.0.0-test); build-repo.sh needs BOTH packages.
  VERSION=0.0.0 bash apps/agent/build-rpm.sh >/dev/null 2>&1 \
    && RPMF="$(ls -1 ./adminhelper-agent-0.0.0-1*.x86_64.rpm 2>/dev/null | head -1)" || RPMF=""
  if [ -n "$RPMF" ]; then
    export GNUPGHOME="$PWD/.mb-gnupg"
    install -d -m 700 "$GNUPGHOME"
    # rsa3072, not ed25519: rocky8's rpm/dnf EdDSA support is patchy, and the
    # rpm repo must verify there too (repo_gpgcheck=1).
    gpg --batch --passphrase '' --quick-generate-key "AH Test Repo <repo@test.invalid>" rsa3072 sign never >/dev/null 2>&1
    REPO_FP="$(gpg --list-secret-keys --with-colons 2>/dev/null | awk -F: '/^fpr:/{print $10; exit}')"
    # Build into a STAGING dir, then copy the contents into ./repo: the gateway
    # already bind-mounts ./repo (root-owned, live), and build-repo.sh rm -rf's
    # its OUT_DIR — nuking a live bind-mount source would leave the container on
    # the old inode (and the rm would fail on the root-owned dir anyway).
    if [ -n "$REPO_FP" ] && VERSION=0.0.0-test DEB="$DEB" RPM="$RPMF" REPO_GPG_KEY_ID="$REPO_FP" \
         OUT_DIR="$PWD/.mb-repo-stage" bash apps/agent/build-repo.sh >/dev/null; then
      sudo mkdir -p repo && sudo cp -a "$PWD/.mb-repo-stage/." repo/ \
        && echo "MB_REPO_GPG_FP=$REPO_FP" \
        || { REPO_FP=""; echo "[serverbox] repo publish (cp into bind mount) failed"; }
    else
      REPO_FP=""; echo "[serverbox] build-repo failed — agent boxes fall back to the local .deb path"
    fi
    unset GNUPGHOME
  else
    echo "[serverbox] rpm build failed — skipping the signed repo (fallback path)"
  fi
else
  echo "[serverbox] deb build failed — skipping the signed repo (fallback path)"
fi
# The CA fingerprint the desktop would embed as --ca-fp: the root is the THIRD and
# last cert the gateway presents (leaf + access intermediate + root).
openssl s_client -connect 127.0.0.1:443 -showcerts </dev/null 2>/dev/null \
  | awk '/-----BEGIN CERTIFICATE-----/{c++} c==3{print} /-----END CERTIFICATE-----/{if(c==3)exit}' \
  > /tmp/mb-root.pem || true
if openssl x509 -in /tmp/mb-root.pem -outform der -out /tmp/mb-root.der 2>/dev/null; then
  echo "MB_CA_FP=$(sha256sum /tmp/mb-root.der | cut -d' ' -f1)"
else
  echo "[serverbox] could not extract the root for MB_CA_FP (agents fall back to TOFU)"
fi
# Tunnel mode: the FRP config seed above wrote frps.toml into the shared volume, and
# the supervisor runs frps from it (its ca-issuer-provisioned leaf carries the
# DOMAIN=$SRV_IP SAN). MB_FRPS_UP once it says running and a frps process runs.
if [ "$DO_TUNNEL" = 1 ]; then
  echo "[serverbox] tunnel mode: wait for the supervisor to run frps (STCP relay :7000/:7443)"
  if tries 60 frps_running; then
    echo "MB_FRPS_UP=1"
  else
    echo "MB_FRPS_UP=0"; echo "    supervisor state: $(sv_file state)"; "${DC[@]}" logs --tail 20 frps
  fi
fi
# Moncheck mode (S5): seed pull (ping) checks + an email alert rule via the
# monitoring internal API (reachable only inside the compose net -> exec), then
# trigger them. The critical transition dispatches email to the mailhog sink
# (smtp_host in channel_config; SMTP is not SSRF-guarded, so a private IP is fine).
if [ "$DO_MONCHECK" = 1 ]; then
  # Guard: a failed moncheck-box lease leaves SMTP_IP empty; without this we'd seed a
  # ping check with an empty target + an alert with an empty smtp_host and fail the S5
  # assertions far downstream with a misleading verdict (2.120).
  [ -n "$SMTP_IP" ] || { echo "[serverbox] moncheck: SMTP_IP leer (Moncheck-Box-Lease fehlgeschlagen?) — Abbruch." >&2; exit 1; }
  echo "[serverbox] moncheck mode: seed ping checks + email alert (smtp -> $SMTP_IP:1025, STARTTLS)"
  # Trust the sink's self-signed cert INSIDE the monitoring container: the
  # alerter mandates STARTTLS with a verifying context (3.24), so without this
  # anchor the send dies with "certificate verify failed" and the closed loop
  # proves nothing. Appending to the bundle avoids needing update-ca-certificates
  # (OpenSSL reads concatenated PEMs); the context is built per send, so the
  # anchor is live for the seed run below.
  if [ -n "$SMTP_CA_B64" ] && [ "$SMTP_CA_B64" != none ]; then
    printf '%s' "$SMTP_CA_B64" | base64 -d \
      | "${DC[@]}" exec -T -u root monitoring sh -c 'cat >> /etc/ssl/certs/ca-certificates.crt' \
      && echo "[serverbox] sink CA appended to the monitoring trust store" \
      || { echo "[serverbox] moncheck: sink CA konnte nicht installiert werden — Abbruch." >&2; exit 1; }
  else
    echo "[serverbox] moncheck: kein sink-CA uebergeben — STARTTLS-Verify wuerde fehlschlagen." >&2; exit 1
  fi
  # Quoted heredoc + -e: pass SMTP_IP through the container env, no shell text in the
  # Python literals (matches the seed block's <<'PY' + export pattern) (2.120).
  "${DC[@]}" exec -T -e SMTP_IP="$SMTP_IP" monitoring python - <<'PY'
import os, json, urllib.request
key = os.environ.get("MONITOR_API_KEY", "")
smtp_ip = os.environ["SMTP_IP"]
base = "http://localhost:8080"
def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
        headers={"Content-Type": "application/json", "X-Internal-Key": key})
    return json.load(urllib.request.urlopen(req, timeout=25))
def st(r):
    return r.get("status") or (r.get("state") or {}).get("status") or "?"
ok_id = call("POST", "/checks", {"name": "mc-ping-ok", "check_type": "ping", "config": {"target": smtp_ip}, "consecutive_fails": 1, "severity": "critical"})["id"]
crit_id = call("POST", "/checks", {"name": "mc-ping-crit", "check_type": "ping", "config": {"target": "192.0.2.1"}, "consecutive_fails": 1, "severity": "critical"})["id"]
call("POST", "/alerts", {"name": "mc-email", "channel": "email", "match_severity": "critical", "channel_config": {"recipients": ["ops@example.com"], "smtp_host": smtp_ip, "smtp_port": 1025}})
ok_r = call("POST", f"/checks/{ok_id}/run")
crit_r = call("POST", f"/checks/{crit_id}/run")
print("MC_OK_STATUS=" + st(ok_r))
print("MC_CRIT_STATUS=" + st(crit_r))
PY
fi
echo "[serverbox] READY at https://$SRV_IP"
