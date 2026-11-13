#!/bin/sh
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# box_freebsdbox.sh — runs ON the FreeBSD box (template ah-tpl-base-freebsd), from
# scripts/tests/freebsd_box.sh via `vm.py run`. POSIX sh: the base system has no bash at
# /bin/sh, and FreeBSD's sh is what a package script meets as well.
#
#   box_freebsdbox.sh tests <dir>       as the box user, like `go test` in CI: every agent test
#                                       binary listed in <dir>/manifest, each in its package dir
#   sudo box_freebsdbox.sh roottests <dir>
#                                       as root: the tests the box user leaves out (ROOT_TESTS, PROBE_ROOT_TESTS)
#   sudo box_freebsdbox.sh pkg <dir>    as root: the package of this checkout from a signed
#                                       local repo, the cron entry, the rc.d tunnel, one agent
#                                       run against a stand-in monitoring service, pkg delete
#
# <dir> is what freebsd_box.sh built on the dev box, relative to the checkout. Each check
# prints `  ok` or `  FAIL`; the last line is `fbsdbox <phase>: N passed, M failed`, and a
# failure ends with exit 1. Nothing is written into the checkout: the next `vm.py run --sync`
# deletes with --delete, and a root-owned file there would stop it.
set -u
# An ssh session's PATH and sudo's may both lack /usr/local, where pkg puts the agent and bash.
PATH=/sbin:/bin:/usr/sbin:/usr/bin:/usr/local/sbin:/usr/local/bin; export PATH
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT" || exit 1
PHASE="${1:?tests|roottests|pkg}"; BUILD="$ROOT/${2:?build dir}"
PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }
done_phase() {
  echo "FBSD_${PHASE}_PASSED=$PASS FBSD_${PHASE}_FAILED=$FAIL"
  echo "fbsdbox $PHASE: $PASS passed, $FAIL failed"
  [ "$FAIL" -eq 0 ]
  exit $?
}
# The package name as a variable: the box CLI check (box_cli_test.go) reads every bare
# `adminhelper-agent` word in these scripts as a call of the agent.
PKG=adminhelper-agent

# The tests of internal/monitor that read service(8) status, which reads pidfiles in /var/run only
# root may read: the box user leaves them out, phase roottests runs them.
ROOT_TESTS="TestCollectServiceHealthOnFreeBSD TestCollectWatchedServicesOnFreeBSD"

# The tests of internal/probe that ask the kernel (net.inet.tcp.getcred, root only) which socket took
# a connection; they skip themselves for the box user. The pf redirect test changes the host's pf, so
# it runs only with AH_FREEBSD_PF=1, which freebsd_box.sh sets and opnsense_box.sh does not (there pf
# is the firewall).
PROBE_ROOT_TESTS="TestPeerSocketOnFreeBSDFindsTheTaker TestGuardConnectsWhenFreeBSDListsTheTaker"
[ "${AH_FREEBSD_PF:-}" != 1 ] || PROBE_ROOT_TESTS="$PROBE_ROOT_TESTS TestGuardRefusesAPfRedirectOnFreeBSD"

# skip_for <package dir> — the tests the box user leaves out there: the cross-build guard calls go,
# which the box lacks (freebsd_box.sh runs it on the dev box); the gopsutil source check calls go
# list and reads the module cache, both missing on the box (it has no build tag, every go test run
# elsewhere covers it); and ROOT_TESTS.
skip_for() {
  case "$1" in
    cmd/adminhelper-agent) echo '^TestAgentPackagesBuildForFreeBSD$' ;;
    internal/monitor) echo "^($(echo "$ROOT_TESTS TestFreeBSDNoSwapMatchesGopsutil" | tr ' ' '|'))\$" ;;
  esac
}

# excerpt <log> — what failed and where: the FAIL and panic lines, each test's own message lines
# (file_test.go:N:), then the end of the log.
excerpt() {
  grep -E '^(--- FAIL|FAIL|panic)|_test\.go:[0-9]+:' "$1" | head -n 40 | sed 's/^/      /'
  tail -n 20 "$1" | sed 's/^/      /'
}

phase_tests() {
  [ -s "$BUILD/manifest" ] || { bad "no test manifest at $BUILD/manifest"; return; }
  work="$(mktemp -d "${TMPDIR:-/tmp}/fbsdbox-tests.XXXXXX")" || { bad "mktemp"; return; }
  while read -r rel bin; do
    [ -n "$rel" ] || continue
    skip="$(skip_for "$rel")"
    # -test.v for the counts only: a package whose binary ran no test is no evidence.
    set -- -test.v -test.timeout 10m -test.count 1
    [ -z "$skip" ] || set -- "$@" -test.skip "$skip"
    if (cd "apps/agent/$rel" && "$BUILD/tests/$bin" "$@") >"$work/$bin.log" 2>&1; then
      passed="$(grep -c '^--- PASS' "$work/$bin.log")"; skipped="$(grep -c '^--- SKIP' "$work/$bin.log")"
      if [ "$passed" -gt 0 ]; then
        ok "$rel ($passed tests passed, $skipped skipped${skip:+, left out here: $skip})"
      else
        bad "$rel ran no test"
      fi
    else
      bad "$rel"; excerpt "$work/$bin.log"
    fi
  done < "$BUILD/manifest"
  rm -rf -- "$work"
}

# root_tests <package dir> <tests> — run the named tests of one package as root.
root_tests() {
  rel="$1"; tests="$2"
  bin="$(awk -v rel="$rel" '$1 == rel { print $2 }' "$BUILD/manifest")"
  [ -n "$bin" ] || { bad "no $rel test binary in $BUILD/manifest"; return; }
  log="$(mktemp "${TMPDIR:-/tmp}/fbsdbox-root.XXXXXX")" || { bad "mktemp"; return; }
  if (cd "apps/agent/$rel" && "$BUILD/tests/$bin" -test.v -test.timeout 10m -test.count 1 \
        -test.run "^($(echo "$tests" | tr ' ' '|'))\$") >"$log" 2>&1; then
    # Each by name: a pattern that matched fewer tests would pass with less.
    for t in $tests; do
      grep -q "^--- PASS: $t " "$log" && ok "$rel as root: $t" || bad "$rel as root: $t did not run"
    done
  else
    bad "$rel as root"; excerpt "$log"
  fi
  rm -f -- "$log"
}

phase_roottests() {
  [ "$(id -u)" = 0 ] || { bad "the roottests phase runs as root"; return; }
  root_tests internal/monitor "$ROOT_TESTS"
  root_tests internal/probe "$PROBE_ROOT_TESTS"
}

# A stand-in for the monitoring service, built by freebsd_box.sh (sink.go). It writes its
# port to $WORK/sink/port and one SINK_REPORT line per POST to its log.
start_sink() {
  mkdir -p "$WORK/sink"
  nohup "$BUILD/sink" "$WORK/sink" </dev/null >"$WORK/sink.log" 2>&1 &
  SINK_PID=$!
  i=0
  while [ ! -s "$WORK/sink/port" ] && [ "$i" -lt 50 ]; do sleep 0.2; i=$((i + 1)); done
  SINK_PORT="$(cat "$WORK/sink/port" 2>/dev/null)"
  [ -n "$SINK_PORT" ]
}

repo_conf() {  # repo_conf <dir> <name> <pubkey> — a repos dir that holds only this repo
  mkdir -p "$1"
  cat > "$1/$2.conf" <<EOF
$2: {
  url: "file://$WORK/out/freebsd/\${ABI}",
  signature_type: "pubkey",
  pubkey: "$3",
  enabled: yes
}
EOF
}

phase_pkg() {
  [ "$(id -u)" = 0 ] || { bad "the pkg phase runs as root"; return; }
  WORK="$(mktemp -d /var/tmp/fbsdbox.XXXXXX)" || { bad "mktemp"; return; }
  echo "[fbsdbox] work dir $WORK"
  export ASSUME_ALWAYS_YES=yes

  echo "[fbsdbox] package: throwaway RSA key, build-pkg.sh, signed repo"
  if openssl genrsa -out "$WORK/repo.key" 4096 2>/dev/null \
     && openssl rsa -in "$WORK/repo.key" -pubout -out "$WORK/repo.pub" 2>/dev/null \
     && openssl genrsa -out "$WORK/other.key" 2048 2>/dev/null \
     && openssl rsa -in "$WORK/other.key" -pubout -out "$WORK/other.pub" 2>/dev/null; then
    ok "throwaway signing keys"
  else
    bad "openssl could not make the throwaway keys"; return
  fi
  if VERSION=0.0.1 AGENT_BINARY="$BUILD/adminhelper-agent-freebsd" FRPC_BINARY="$BUILD/frpc" \
       OUT_DIR="$WORK/out" PKG_REPO_KEY="$WORK/repo.key" bash apps/agent/build-pkg.sh >"$WORK/build.log" 2>&1; then
    ok "build-pkg.sh: $(cd "$WORK/out/freebsd" && ls -1 ./*/All/*.pkg | tr '\n' ' ')"
  else
    bad "build-pkg.sh"; tail -n 40 "$WORK/build.log" | sed 's/^/      /'; return
  fi

  # The pinned key decides: a repo signed by another key must not load. pkg update names the bad
  # signature, drops the repo and still exits 0 (pkg on 15.1), so the check is that nothing of
  # that repo is left to query or install; the same query against the right key finds the package.
  repo_conf "$WORK/repos-other" ahother "$WORK/other.pub"
  pkg -R "$WORK/repos-other" update -f -r ahother >"$WORK/other.log" 2>&1
  other_rc=$?
  if grep -q 'Invalid signature' "$WORK/other.log" \
     && ! pkg -R "$WORK/repos-other" rquery -r ahother %n "$PKG" >>"$WORK/other.log" 2>&1 \
     && ! pkg -R "$WORK/repos-other" install -y -r ahother "$PKG" >>"$WORK/other.log" 2>&1 \
     && ! pkg info -e "$PKG"; then
    ok "a repo signed by another key is refused (update exit $other_rc: $(grep -m1 'Invalid signature' "$WORK/other.log" | cut -c1-80))"
  else
    bad "a repo signed by another key was not refused"; tail -n 30 "$WORK/other.log" | sed 's/^/      /'
  fi
  repo_conf "$WORK/repos" ahbox "$WORK/repo.pub"
  if pkg -R "$WORK/repos" update -f -r ahbox >"$WORK/update.log" 2>&1 \
     && found="$(pkg -R "$WORK/repos" rquery -r ahbox %n-%v "$PKG" 2>>"$WORK/update.log")" \
     && [ "$found" = "$PKG-0.0.1" ]; then
    ok "the repo signed by the pinned key loads ($found)"
  else
    bad "pkg update/rquery from the signed repo"; tail -n 30 "$WORK/update.log" | sed 's/^/      /'; return
  fi
  if pkg -R "$WORK/repos" install -y -r ahbox "$PKG" >"$WORK/install.log" 2>&1; then
    ok "pkg install from the signed repo ($(pkg query '%n-%v %q' "$PKG"))"
  else
    bad "pkg install from the signed repo"; tail -n 30 "$WORK/install.log" | sed 's/^/      /'; return
  fi
  for f in /usr/local/bin/adminhelper-agent /usr/local/libexec/adminhelper/frpc /usr/local/etc/rc.d/adminhelper_frpc; do
    [ -x "$f" ] && ok "installed: $f" || bad "not installed or not executable: $f"
  done

  echo "[fbsdbox] the agent's scheduling: service install writes the cron entry"
  cron=/usr/local/etc/cron.d/adminhelper
  if adminhelper-agent service install >"$WORK/service.log" 2>&1 && [ -f "$cron" ]; then
    mode="$(stat -f %Lp "$cron")"
    [ "$mode" = 644 ] && grep -q '/usr/local/bin/adminhelper-agent run --once' "$cron" \
      && ok "cron entry $cron ($mode): $(grep '^\*/5' "$cron")" \
      || bad "cron entry $cron ($mode) is not the expected one: $(cat "$cron")"
  else
    bad "service install wrote no $cron"; sed 's/^/      /' "$WORK/service.log"
  fi

  echo "[fbsdbox] the tunnel service: enable, start, status"
  mkdir -p /usr/local/etc/adminhelper/frp
  # No frps behind it: loginFailExit = false keeps frpc retrying instead of exiting.
  printf 'serverAddr = "127.0.0.1"\nserverPort = 7\nloginFailExit = false\n' \
    > /usr/local/etc/adminhelper/frp/frpc.toml
  service adminhelper_frpc enable >/dev/null 2>&1
  [ "$(sysrc -n adminhelper_frpc_enable 2>/dev/null)" = YES ] \
    && ok "rc.conf: adminhelper_frpc_enable=YES" || bad "service enable set no rcvar"
  if service adminhelper_frpc start >"$WORK/frpc-start.log" 2>&1; then
    sleep 2
    status="$(service adminhelper_frpc status 2>&1)"
    case "$status" in
      *"is running"*) ok "status: $status" ;;
      *) bad "status: $status" ;;
    esac
    pgrep -f '^/usr/local/libexec/adminhelper/frpc -c ' >/dev/null \
      && ok "frpc runs under daemon(8)" || bad "no frpc process"
    log=/var/log/adminhelper/frpc.log
    if [ -f "$log" ]; then
      mode="$(stat -f %Lp "$log")"
      [ "$mode" = 600 ] && ok "frpc log $log ($mode)" || bad "frpc log $log has mode $mode, want 600"
      [ -s "$log" ] && ok "frpc writes to $log" || bad "frpc wrote nothing to $log"
    else
      bad "daemon(8) wrote no $log"
    fi
    grep -q adminhelper-frpc /var/log/messages \
      && bad "frpc output reached /var/log/messages" || ok "no frpc output in /var/log/messages"
    # newsyslog finds the package's entry through /etc/newsyslog.conf's include of newsyslog.conf.d.
    if newsyslog -F "$log" >"$WORK/newsyslog.log" 2>&1 && [ -f "$log.0.bz2" ] && [ -f "$log" ]; then
      mode="$(stat -f %Lp "$log") $(stat -f %Lp "$log.0.bz2")"
      [ "$mode" = "600 600" ] && ok "newsyslog -F rotated $log (modes $mode)" \
        || bad "newsyslog -F: modes of the new log and its archive are $mode, want 600 600"
      [ -s "$WORK/newsyslog.log" ] \
        && { bad "newsyslog -F reported:"; sed 's/^/      /' "$WORK/newsyslog.log"; } \
        || ok "newsyslog -F reported nothing"
      sleep 2
      pgrep -f '^/usr/local/libexec/adminhelper/frpc -c ' >/dev/null \
        && ok "frpc runs after the rotation's SIGHUP" || bad "no frpc process after the rotation"
      # daemon -H reopens its -o file on SIGHUP: the supervisor (its -P pid) must hold the new
      # log's inode, not the rotated one's. fstat's fifth and sixth columns are MOUNT and INUM;
      # an inode number alone could belong to a file on another file system.
      pid="$(cat /var/run/adminhelper_frpc.pid 2>/dev/null)"
      inum="$(stat -f %i "$log")"
      mnt="$(df -P "$log" | awk 'NR == 2 { print $NF }')"
      held="$(fstat -p "${pid:-0}" 2>/dev/null \
        | awk -v i="$inum" -v m="$mnt" 'NR > 1 && $5 == m && $6 == i' | wc -l | tr -d ' ')"
      [ -n "$pid" ] && [ "$held" -ge 1 ] \
        && ok "daemon(8) pid $pid reopened $log (inode $inum on $mnt)" \
        || bad "daemon(8) pid ${pid:-?} does not hold $log (inode $inum on $mnt) after the rotation"
    else
      bad "newsyslog -F did not rotate $log"; sed 's/^/      /' "$WORK/newsyslog.log"
    fi
  else
    bad "service adminhelper_frpc start"; sed 's/^/      /' "$WORK/frpc-start.log"
  fi

  echo "[fbsdbox] one agent run against a stand-in monitoring service"
  if start_sink; then
    ok "sink on 127.0.0.1:$SINK_PORT"
    if adminhelper-agent monitor init --url "https://127.0.0.1:$SINK_PORT/api/monitoring" \
         --api-key fbsdbox --server-id 7 --insecure >"$WORK/init.log" 2>&1; then
      ok "monitor init (TOFU pin, test push)"
    else
      bad "monitor init"; sed 's/^/      /' "$WORK/init.log"
    fi
    mode="$(stat -f %Lp /usr/local/etc/adminhelper 2>/dev/null)"
    [ "$mode" = 700 ] && ok "data dir /usr/local/etc/adminhelper 700" || bad "data dir mode $mode"
    before="$(grep -c '^SINK_REPORT' "$WORK/sink.log")"
    if adminhelper-agent run --once >"$WORK/run.log" 2>&1; then
      ok "run --once exit 0"
    else
      bad "run --once"; tail -n 30 "$WORK/run.log" | sed 's/^/      /'
    fi
    after="$(grep -c '^SINK_REPORT' "$WORK/sink.log")"
    last="$(grep '^SINK_REPORT' "$WORK/sink.log" | tail -n 1)"
    if [ "$after" -gt "$before" ]; then
      ok "the run pushed a report: $last"
      case "$last" in *" path=/api/monitoring/agent/7/report "*) ok "report endpoint" ;; *) bad "report endpoint: $last" ;; esac
      case "$last" in *" os=freebsd "*) ok "host.os = freebsd" ;; *) bad "host.os: $last" ;; esac
      case "$last" in *" system_state=true "*) ok "system_state present" ;; *) bad "no system_state: $last" ;; esac
      case "$last" in *" api_key=true "*) ok "X-API-Key sent" ;; *) bad "no X-API-Key: $last" ;; esac
    else
      bad "no report reached the sink during run --once"; sed 's/^/      /' "$WORK/sink.log"
    fi
    kill "$SINK_PID" 2>/dev/null
  else
    bad "the sink did not start"; sed 's/^/      /' "$WORK/sink.log"
  fi

  echo "[fbsdbox] pkg delete clears the cron entry and the service"
  if pkg delete -y "$PKG" >"$WORK/delete.log" 2>&1; then
    ok "pkg delete"
  else
    bad "pkg delete"; sed 's/^/      /' "$WORK/delete.log"
  fi
  [ ! -e "$cron" ] && ok "cron entry removed" || bad "cron entry left: $cron"
  [ ! -e /usr/local/etc/rc.d/adminhelper_frpc ] && ok "rc.d script removed" || bad "rc.d script left"
  [ -z "$(sysrc -n adminhelper_frpc_enable 2>/dev/null)" ] && ok "rcvar removed" \
    || bad "rc.conf still has adminhelper_frpc_enable"
  sleep 1
  pgrep -f '^/usr/local/libexec/adminhelper/frpc' >/dev/null && bad "frpc still runs" || ok "frpc stopped"
  [ -f /usr/local/etc/adminhelper/monitor.conf ] && ok "configuration kept (monitor.conf)" \
    || bad "monitor.conf removed with the package"

  [ "$FAIL" -eq 0 ] && rm -rf -- "$WORK"
}

case "$PHASE" in
  tests) phase_tests ;;
  roottests) phase_roottests ;;
  pkg) phase_pkg ;;
  *) bad "unknown phase $PHASE" ;;
esac
done_phase
