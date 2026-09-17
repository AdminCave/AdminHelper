#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# multibox.sh — distributed, multi-host AdminHelper E2E on Proxmox VMs (scenario S1+).
#
# Clones a SERVER box + N AGENT boxes on the same bridge and wires a real
# cross-host topology the single-host scripts/tests/*.sh cannot reach:
#   server-box  = full docker-compose stack (gateway 443/8444/8445, frps 7000/7443)
#   agent-box(s)= real .deb install + `adminhelper-agent provision` over a network hop
# Then asserts each agent enrolled an mTLS identity and pushed a monitoring report.
#
#   bash scripts/tests/multibox.sh [--agents N] [--rpm] [--tunnel]
#       [--desktop] [--moncheck] [--enforce] [--capstone] [--keep] [--strict]
#   --strict   a guard that could not run fails the capstone (release gate)
#   --rpm      + a cross-distro rpm agent (rockylinux)      (S2)
#   --tunnel   + frps + agent frpc STCP server + a visitor  (S4, 3-host tunnel)
#   --desktop  + the real Tauri GUI vs the remote server     (S3)
#   --moncheck + pull ping-checks + a closed-loop email alert (S5)
#   --enforce  + MTLS_ENFORCE=true: the certless data plane must be rejected
#   --capstone = --agents 1 --rpm --tunnel --desktop --moncheck --enforce
#              (S6: all in one run — the release gate)
#   --keep     leave the VMs up after the run (still bounded by their ttl)
#
# Every VM of one run carries the same `sc-` tag, so the teardown is a single
# `vm.py destroy --scenario`: a box whose clone succeeded but whose boot did not
# is torn down with the rest instead of surviving as a leak. AH_DESKTOP_VM
# reuses an already warm desktop box (AH_DESKTOP_ID is the old name, kept for
# one release).
#
# Validates over the single-host suites: cross-host mTLS with SAN=<server IP> (not
# localhost), real package install + systemd, and the monitoring pipeline over a real
# hop. Box-side logic lives in scripts/tests/box_serverbox.sh / box_agentbox.sh.
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/vm/lib.sh
. "$DIR/../vm/lib.sh"
cd "$VM_ROOT" || exit 1

AGENTS=1; KEEP=0; DESKTOP=0; RPM=0; TUNNEL=0; MONCHECK=0; ENFORCE=0
SKIPPED=0; MB_DEBIAN9_SKIPPED=0
while [ $# -gt 0 ]; do case "$1" in
  --agents) AGENTS="${2:?}"; shift ;; --keep) KEEP=1 ;; --desktop) DESKTOP=1 ;; --rpm) RPM=1 ;;
  --tunnel) TUNNEL=1 ;; --moncheck) MONCHECK=1 ;; --enforce) ENFORCE=1 ;;  # D2: MTLS_ENFORCE=true
  # S6: everything, one run. --enforce included (R-0022): without it the
  # MTLS_ENFORCE guard never ran in a release capstone, which is the one place
  # the cert-gated data plane is supposed to be proven.
  --capstone) AGENTS=1; RPM=1; TUNNEL=1; DESKTOP=1; MONCHECK=1; ENFORCE=1 ;;
  # A flag, not just the env: AH_STRICT is set by run.sh alone, which never
  # starts this script, and a `AH_STRICT=1 multibox.sh` prefix is what
  # .claude/rules/testing.md forbids ("Env-Bedarf loest das Skript auf").
  --strict) AH_STRICT=1 ;;
  *) echo "unknown arg: $1"; exit 2 ;; esac; shift; done

vm_load_env || exit 1

# One scenario tag for the whole run — the teardown's only handle, and what
# keeps `vm.py list` from calling this run's seven boxes a leak while it lasts.
SCENARIO="mb-$$"; export AH_VM_SCENARIO="$SCENARIO"
PASS=0; FAIL=0; RPM_AGENTS=0
ok(){ echo "  ok   $*"; PASS=$((PASS+1)); }; bad(){ echo "  FAIL $*"; FAIL=$((FAIL+1)); }
# A check that could not run is its own outcome: counted, named in the summary,
# and a failure under AH_STRICT=1 — a capstone that quietly dropped a guard is
# not the evidence a release needs ("SKIP heisst nicht verifiziert").
skipped(){ echo "  SKIP $*"; SKIPPED=$((SKIPPED+1)); [ "${AH_STRICT:-0}" = "1" ] && bad "strict: $*"; return 0; }
cleanup() {
  [ "$KEEP" = 1 ] && { echo "--keep: leaving scenario $SCENARIO up (bounded by the ttl)"; return; }
  echo "== teardown scenario $SCENARIO =="
  # By tag, not by a list this script kept: a clone that came back and then
  # failed to boot never made it into any list, and it is exactly the box that
  # would otherwise be left running.
  vm_py destroy --scenario "$SCENARIO" 2>&1 | sed 's/^/  /' || true
}
trap cleanup EXIT INT TERM

DESKTOP_VM="${AH_DESKTOP_VM:-${AH_DESKTOP_ID:-}}"
# Only when this run actually has a desktop role to reuse — `--agents 3` in a
# shell that still exports the old name is not being told anything useful.
[ "$DESKTOP" = 1 ] && [ -n "${AH_DESKTOP_ID:-}" ] && [ -z "${AH_DESKTOP_VM:-}" ] \
  && echo "note: AH_DESKTOP_ID is the old name — use AH_DESKTOP_VM (the alias goes after the next release)"

# The roles this run is about to clone, in the order they will be asked for.
planned_roles() {
  local roles="server" i
  for i in $(seq 1 "$AGENTS"); do roles="$roles,agent"; done
  [ "$MONCHECK" = 1 ] && roles="$roles,moncheck"
  [ "$RPM" = 1 ] && roles="$roles,rpm"
  [ "$TUNNEL" = 1 ] && roles="$roles,tunnel,visitor"
  [ "$DESKTOP" = 1 ] && [ -z "$DESKTOP_VM" ] && roles="$roles,desktop"
  printf '%s' "$roles"
}

# Capacity BEFORE the first clone: seven boxes that die on the fifth leave four
# running and an hour spent. doctor answers 74 with the arithmetic and the list
# of VMs already holding the RAM, which is what makes it actionable.
echo "== doctor: does this hypervisor fit $(planned_roles)? =="
doctor_rc=0
vm_py doctor --roles "$(planned_roles)" || doctor_rc=$?
if [ "$doctor_rc" != 0 ]; then
  # NOT `if ! vm_py doctor`: inside that branch $? is the status of the
  # negation, which is 0 — a refused capacity check would exit 0 and read as a
  # run that passed without doing anything.
  echo ""
  echo "  multibox: 0 ok, 1 failed, 0 skipped  (doctor refused the scenario, exit $doctor_rc)"
  exit "$doctor_rc"
fi

# lease <role> <profile> -> echoes "<vmid> <ip>"; blocks until the box answers ssh.
# No retry: the clone is a two-second API call against the hypervisor, and every
# reason it fails (capacity, no free VMID, no template, a lost privilege) is one
# a second attempt meets again. vm.py answers those with 74 and names them.
lease() {
  local role="$1" profile="$2" vmid ip
  vmid="$(vm_py clone --profile "$profile" --role "$role" --scenario "$SCENARIO" --ttl 90m \
          | awk 'NR==1{print $1}')" || { echo "clone failed for role $role" >&2; return 1; }
  [ -n "$vmid" ] || { echo "clone printed no VMID for role $role" >&2; return 1; }
  ip="$(vm_py wait "$vmid" | tail -1)" || { echo "$role box $vmid never came up" >&2; return 1; }
  [ -n "$ip" ] || { echo "no address for $role box $vmid" >&2; return 1; }
  echo "$vmid $ip"
}

# box <vmid> <timeout> <command…> — a role script on a box, with the checkout
# synced first. 3000 s for every agent-profile role setup: each one runs the
# bootstrap, and a bootstrap that waits out the apt-lock race can take 20+
# minutes on its own. The 2026-09-11 weekly lost the moncheck and tunnel setups
# to a smaller bound, and every later failure that day was a consequence.
box() { local vmid="$1" tmo="$2"; shift 2; vm_py run "$vmid" --sync --timeout "$tmo" -- "$@"; }
# ask <vmid> <timeout> <command…> — a short query on a box that already has the
# tree. No --sync: re-pushing the checkout for a `docker logs` is a minute of
# rsync per question.
ask() { local vmid="$1" tmo="$2"; shift 2; vm_py run "$vmid" --timeout "$tmo" -- "$@"; }

echo "== clone 1 server + $AGENTS agent box(es) (scenario $SCENARIO) =="
read -r SRV_VM SRV_IP < <(lease server linux-server) || { bad "server lease"; exit 1; }
ok "server-box $SRV_VM @ $SRV_IP"
AGENT_VMS=()
for i in $(seq 1 "$AGENTS"); do
  if read -r a_vm a_ip < <(lease agent linux-server); then
    AGENT_VMS+=("$a_vm"); ok "agent-box$i $a_vm @ $a_ip"
    [ "$a_ip" = "$SRV_IP" ] && bad "agent$i IP $a_ip collides with server — DHCP/capacity? (need distinct concurrent VMs)"
  else bad "agent$i lease"; fi
done

MC_VM=""; MC_IP=""
if [ "$MONCHECK" = 1 ]; then
  echo "== moncheck (S5): clone the client/sink box + start mailhog (before the seed) =="
  if read -r MC_VM MC_IP < <(lease moncheck linux-server); then
    ok "moncheck-box $MC_VM @ $MC_IP"
    MCSTART="$(box "$MC_VM" 3000 bash scripts/tests/box_moncheckbox.sh start "$MC_IP" 2>&1)"
    echo "$MCSTART" | grep -vE 'Compiling|Downloaded ' | tail -20
    printf '%s' "$MCSTART" | grep -q MC_MAILHOG_UP && ok "mailpit sink up on $MC_IP (:1025/:8025, STARTTLS)" || bad "mailpit did not start"
    # The sink's self-signed cert travels to the server box so the monitoring
    # container can verify it — the alerter refuses unverified TLS (3.24).
    MC_CA_B64="$(vm_marker MC_CA_B64 "$MCSTART")"
    [ -n "$MC_CA_B64" ] || bad "sink CA marker missing (STARTTLS verify will fail)"
  else bad "moncheck-box lease"; fi
fi

echo "== bring up the server stack on $SRV_VM ($SRV_IP) =="
SRVARG=""
[ "$TUNNEL" = 1 ]   && SRVARG="$SRVARG tunnel"
# Only when the lease succeeded — an empty MC_IP would pass `moncheck` with no IP,
# shifting serverbox's positional args (4.124).
[ "$MONCHECK" = 1 ] && [ -n "$MC_IP" ] && SRVARG="$SRVARG moncheck $MC_IP ${MC_CA_B64:-none}"
[ "$ENFORCE" = 1 ]  && SRVARG="$SRVARG enforce"
# shellcheck disable=SC2086
SRVOUT="$(box "$SRV_VM" 2700 bash scripts/tests/box_serverbox.sh "$SRV_IP" $SRVARG 2>&1)"; echo "$SRVOUT" | grep -vE 'Compiling|Downloaded |Container |Network |Volume |Pulling|Waiting|Pull complete' | tail -40
# mb <KEY> — server-box marker via the shared vm_marker (scripts/vm/lib.sh),
# bound to $SRVOUT. Dedups 13 near-identical greps; a parsing fix lands once.
mb() { vm_marker "$1" "$SRVOUT"; }
SID="$(mb MB_SID)"
PTOK="$(mb MB_PTOK)"
ADMIN_PW="$(mb MB_ADMIN_PW)"
MONITOR_KEY="$(mb MB_MONITOR_KEY)"
SID2="$(mb MB_SID2)"
PTOK2="$(mb MB_PTOK2)"
TUN_SID="$(mb MB_TUN_SID)"
TUN_PTOK="$(mb MB_TUN_PTOK)"
VIS_SID="$(mb MB_VIS_SID)"
VIS_PTOK="$(mb MB_VIS_PTOK)"
VIS_B64="$(mb MB_VISITOR_B64)"
MC_OK_STATUS="$(mb MC_OK_STATUS)"
MC_CRIT_STATUS="$(mb MC_CRIT_STATUS)"
REPO_FP="$(mb MB_REPO_GPG_FP)"
CAFP="$(mb MB_CA_FP)"
OLDDPKG="$(mb MB_DEB_OLDDPKG_OK)"
[ -n "$SID" ] && [ -n "$PTOK" ] && ok "stack up + provision token minted (server $SID)" \
  || { bad "server bring-up / token seed"; exit 1; }
# The signed test repo is the backbone of the user install path — its absence
# means the dogfooded agent-install.sh flow silently degrades, so fail loudly.
[ -n "$REPO_FP" ] && ok "signed test repo live on :8445 (gpg $REPO_FP)" \
  || bad "signed repo missing on :8445 (serverbox package/repo build failed — agents fall back to the local .deb path)"
[ -n "$CAFP" ] && ok "gateway intermediate fingerprint extracted (--ca-fp $CAFP)" \
  || bad "MB_CA_FP missing — agents fall back to TOFU first contact"
# Old-Debian regression guard: the .deb must install AND its binary must run on
# debian:9 (dpkg 1.18 + glibc 2.24 = Stretch / UniFi firmware). "0" is either the
# zstd-compression break (v0.43.0) or the dynamic-glibc break (v0.43.1); empty
# means the archived image could not pull (skip, not verified).
case "$OLDDPKG" in
  1) ok "agent .deb installs + binary runs on old Debian (debian:9: dpkg 1.18, glibc 2.24)" ;;
  0) bad "agent .deb/binary fails on debian:9 — zstd-compression OR dynamic-glibc regression!" ;;
  *) MB_DEBIAN9_SKIPPED=1
     skipped "old-Debian check (marker missing: debian:9 not pullable, or the .deb build failed) — the two release-breaking regressions of 0.43.x are unguarded" ;;
esac
if [ "$ENFORCE" = 1 ]; then
  printf '%s' "$SRVOUT" | grep -q 'MB_ENFORCE_CERTLESS_REJECTED=1' \
    && ok "MTLS_ENFORCE=true: certless :443 rejected (400) — cert-gated data plane over the hop" \
    || bad "enforce: certless :443 was not rejected (check MB_ENFORCE_CERTLESS_REJECTED)"
else
  skipped "MTLS_ENFORCE guard (no --enforce; --capstone implies it) — the cert-gated data plane is unverified"
fi

echo "== provision each agent against https://$SRV_IP =="
for a in "${AGENT_VMS[@]:-}"; do
  [ -n "$a" ] || continue
  AOUT="$(box "$a" 3000 bash scripts/tests/box_agentbox.sh "$SRV_IP" "$SID" "$PTOK" "$REPO_FP" "$CAFP" 2>&1)"; echo "$AOUT" | grep -vE 'Compiling|Downloaded |go: downloading' | tail -50
  printf '%s' "$AOUT" | grep -q AGENT_PROVISION_OK && printf '%s' "$AOUT" | grep -q AGENT_CERT_OK \
    && ok "agent $a: provisioned + mTLS-enrolled over the network hop" \
    || bad "agent $a: provision/enroll (see output above; check IP-SAN + firewall)"
  if [ -n "$REPO_FP" ]; then
    printf '%s' "$AOUT" | grep -q AGENT_REPO_OK && printf '%s' "$AOUT" | grep -q AGENT_CAFLIP_OK \
      && ok "agent $a: installed from the :8445 repo via agent-install.sh, CA-pinned steady state" \
      || bad "agent $a: user-path markers missing (AGENT_REPO_OK/AGENT_CAFLIP_OK)"
  else
    skipped "agent $a: user install path (no MB_REPO_GPG_FP) — the :8445 repo and the CA-pin flip are unverified"
  fi
done

if [ "$RPM" = 1 ]; then
  echo "== cross-distro (S2): build the .rpm + provision it in a rockylinux container =="
  if read -r R_VM R_IP < <(lease rpm linux-server); then
    ok "rpm-agent-box $R_VM @ $R_IP"
    ROUT="$(box "$R_VM" 3000 bash scripts/tests/box_agentbox_rpm.sh "$SRV_IP" "$SID2" "$PTOK2" 2>&1)"
    echo "$ROUT" | grep -vE 'Compiling|Downloaded |go: downloading' | tail -45
    printf '%s' "$ROUT" | grep -q RPM_ALL_OK \
      && { ok "rpm agent: built + installed + mTLS-enrolled in rockylinux over the hop"; RPM_AGENTS=1; } \
      || bad "rpm agent (see output above)"
  else bad "rpm-agent lease"; fi
fi

if [ "$TUNNEL" = 1 ]; then
  echo "== tunnel (S4): agent frpc STCP server over the hop to frps on $SRV_IP =="
  printf '%s' "$SRVOUT" | grep -q 'MB_FRPS_UP=1' && ok "frps up on the server box" || bad "frps did not start on the server"
  if [ -n "$TUN_SID" ] && [ -n "$TUN_PTOK" ] && read -r T_VM T_IP < <(lease tunnel linux-server); then
    ok "tunnel-agent-box $T_VM @ $T_IP"
    TOUT="$(box "$T_VM" 3000 bash scripts/tests/box_tunnelbox.sh "$SRV_IP" "$TUN_SID" "$TUN_PTOK" 2>&1)"
    echo "$TOUT" | grep -vE 'Compiling|Downloaded |go: downloading' | tail -40
    printf '%s' "$TOUT" | grep -q TUNNEL_FRPC_CONNECTED \
      && ok "tunnel agent: frpc STCP server connected to the remote frps" \
      || bad "tunnel agent: frpc did not connect (see output above)"
    # Independent check on the server: frps logged the STCP registration cross-host.
    FRPSLOG="$(ask "$SRV_VM" 300 'mb-dc logs --no-color frps 2>/dev/null | grep -iE "new proxy|start proxy success|stcp" | tail -5' 2>/dev/null)"
    printf '%s' "$FRPSLOG" | grep -qiE 'new proxy|start proxy success|stcp' \
      && ok "frps registered the agent's STCP tunnel (cross-host)" \
      || bad "frps shows no STCP registration from the agent"
    # Phase 2: a visitor on a THIRD box completes the data path (visitor -> frps ->
    # agent frpc -> the agent's sshd), proving the full cross-host tunnel.
    if [ -n "$VIS_SID" ] && [ -n "$VIS_B64" ] && read -r V_VM V_IP < <(lease visitor linux-server); then
      ok "visitor-box $V_VM @ $V_IP"
      VOUT="$(box "$V_VM" 3000 bash scripts/tests/box_visitorbox.sh "$SRV_IP" "$VIS_SID" "$VIS_PTOK" "$VIS_B64" 2>&1)"
      echo "$VOUT" | grep -vE 'Compiling|Downloaded |go: downloading' | tail -40
      printf '%s' "$VOUT" | grep -q VIS_TUNNEL_SSH_OK \
        && ok "visitor reached the agent's sshd THROUGH the tunnel (3-host data path)" \
        || bad "visitor could not reach the agent's sshd through the tunnel"
    else bad "visitor lease or missing visitor config"; fi
  else bad "tunnel-agent lease or missing tunnel seed"; fi
fi

if [ "$DESKTOP" = 1 ]; then
  # AH_DESKTOP_VM reuses an already-warm desktop box (skip clone + re-bootstrap).
  if [ -n "$DESKTOP_VM" ]; then
    DT_VM="$DESKTOP_VM"; ok "desktop-box $DT_VM (reused via AH_DESKTOP_VM)"
  elif read -r DT_VM DT_IP < <(lease desktop linux-full); then
    ok "desktop-box $DT_VM @ $DT_IP"
  else DT_VM=""; bad "desktop lease"; fi
  if [ -n "$DT_VM" ]; then
    # With --enforce the data plane is cert-gated, so the GUI has to enroll a device
    # identity before it can log in. Two constraints shape this:
    #   - one token per SPEC, not per run: every spec is its own `wdio run` in its
    #     own dbus session with an empty keyring, so each starts un-enrolled; and
    #     an enrollment token is one-time.
    #   - minted HERE, not on the server box hours ago: the default TTL is 60 min
    #     and this stage starts after the agent, rpm, tunnel and visitor boxes.
    # Kept in sync with the default in box_desktopbox.sh — named here because
    # the number of tokens to mint depends on it.
    DESK_SPECS="server-crud.live.js monitoring-check.live.js"
    DESK_ETOKS=""
    if [ "$ENFORCE" = 1 ]; then
      # ONE run for all tokens, not one per spec: the first capstone lost one of
      # two that way, with no diagnosis left because the output had been thrown
      # at /dev/null.
      # --ttl-minutes 240, not the 60-minute default: the last token is redeemed
      # after the box bootstrap, the ~20 min Tauri build and every earlier spec.
      # The stage's own deckel is the 3000 s below — the TTL has to outlive it
      # with room, or raising that timeout breaks this silently.
      MINTLOG="${AH_OUT_DIR:-$VM_ROOT/.ah-out}/mint-desktop-tokens.log"
      mkdir -p "$(dirname "$MINTLOG")" 2>/dev/null
      n_want=0; for _ in $DESK_SPECS; do n_want=$((n_want + 1)); done
      ask "$SRV_VM" 600 \
        "for i in \$(seq 1 $n_want); do mb-dc exec -T server python -m app.cli mint-enroll-token --username admin --ttl-minutes 240; done" \
        >"$MINTLOG" 2>&1
      # Anchored: the CLI prints each token on a line of its own, so ^…$ cannot
      # pick up a long word from the wrapper's own output.
      DESK_ETOKS="$(tr -d '\r' < "$MINTLOG" | grep -oE '^[A-Za-z0-9_-]{20,}$' | tail -n "$n_want" | paste -sd' ' -)"
      [ -n "$DESK_ETOKS" ] || echo "  (mint failed — see $MINTLOG)"
    fi
    # The values are hex/IPv4/token_urlsafe today, none can contain a quote.
    n_tok=0; for _ in $DESK_ETOKS; do n_tok=$((n_tok + 1)); done
    n_spec=0; for _ in $DESK_SPECS; do n_spec=$((n_spec + 1)); done
    if [ "$ENFORCE" = 1 ] && [ "$n_tok" -lt "$n_spec" ]; then
      # Skip the stage rather than spend up to 50 minutes of VM time on a run that
      # cannot pass: without a token per spec the enforced gateway rejects the login.
      bad "desktop: only $n_tok of $n_spec enrollment tokens minted (see ${MINTLOG:-the mint log})"
      skipped "desktop GUI journeys (not enough enrollment tokens under --enforce) — the S3 scenario is unverified"
      DTOUT=""
    else
      echo "== drive the real Tauri GUI on $DT_VM against https://$SRV_IP =="
      DTOUT="$(box "$DT_VM" 3000 \
        "AH_DESKTOP_ENROLL_TOKENS='$DESK_ETOKS' bash scripts/tests/box_desktopbox.sh '$SRV_IP' '$ADMIN_PW' '$MONITOR_KEY' $DESK_SPECS" 2>&1)"
      echo "$DTOUT" | grep -vE 'Compiling|Downloaded |npm warn|go: downloading' | tail -40
      printf '%s' "$DTOUT" | grep -q DESKTOP_ALL_OK \
        && ok "desktop GUI journeys green against the remote server (login/CRUD/monitoring)" \
        || bad "desktop GUI journeys (see output above)"
    fi
  else
    # On top of the lease FAIL above, not instead of it: the two facts differ —
    # the box could not be had, AND the S3 journeys are therefore unverified.
    # Only the second one is what a reader of "N skipped" is looking for.
    skipped "desktop GUI journeys (no desktop box) — the S3 scenario is unverified"
  fi
fi

if [ "$MONCHECK" = 1 ]; then
  echo "== moncheck (S5): pull-check verdicts + closed-loop alert delivery =="
  [ "$MC_CRIT_STATUS" = critical ] && ok "ping check to an unreachable target -> critical" || bad "unreachable ping check status=${MC_CRIT_STATUS:-?} (expected critical)"
  [ "$MC_OK_STATUS" = ok ] && ok "ping check to the reachable client -> ok" || bad "reachable ping check status=${MC_OK_STATUS:-?} (expected ok)"
  if [ -n "$MC_VM" ]; then
    MCA="$(ask "$MC_VM" 300 bash scripts/tests/box_moncheckbox.sh assert 2>&1)"
    printf '%s' "$MCA" | grep -E 'MC_MAIL_COUNT|MC_ALERT' | sed 's/^/  /'
    printf '%s' "$MCA" | grep -q MC_ALERT_RECEIVED \
      && ok "critical alert email delivered to the mailhog sink over the network (closed loop)" \
      || bad "no alert email reached the sink"
  else
    skipped "closed-loop alert delivery (no moncheck box) — S5 mail delivery is unverified"
  fi
fi

echo "== assert monitoring ingested a report from the remote agent(s) =="
REPORTS="$(ask "$SRV_VM" 300 'mb-dc logs monitoring 2>/dev/null | grep -cE "POST /agent/[^/]+/report HTTP"' 2>/dev/null | grep -oE '^[0-9]+$' | tail -1)"
EXPECT=$(( ${#AGENT_VMS[@]} + RPM_AGENTS ))
if [ $(( AGENTS + RPM )) -ge 1 ]; then
  # Floor of 1 (R-0021): every agent lease failing left EXPECT=0, and "0 >= 0"
  # passed a run in which no agent ever reported. Keyed on the agents ASKED FOR,
  # not on the ones that arrived — `--agents 0 --desktop` (server + GUI, no .deb)
  # is a real partial run and must not fail for a hop it never requested.
  [ "$EXPECT" -lt 1 ] && EXPECT=1
  [ -n "${REPORTS:-}" ] && [ "$REPORTS" -ge "$EXPECT" ] 2>/dev/null \
    && ok "monitoring ingested $REPORTS report(s) from remote agent(s)" \
    || bad "monitoring saw ${REPORTS:-0} reports (expected >= $EXPECT)"
else
  skipped "monitoring ingest (no agent role requested) — the report hop is unverified"
fi

echo ""
echo "──────────────────────────────────────────────"
echo "  multibox: $PASS ok, $FAIL failed, $SKIPPED skipped  (server=$SRV_IP, agents=${AGENT_VMS[*]:-none})"
[ "${MB_DEBIAN9_SKIPPED:-0}" = 1 ] && echo "  MB_DEBIAN9_SKIPPED=1"
[ "$FAIL" -gt 0 ] && exit 1 || exit 0
