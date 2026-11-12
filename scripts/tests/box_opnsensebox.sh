#!/bin/sh
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# box_opnsensebox.sh — runs ON the OPNsense box (template ah-tpl-base-opnsense), from
# scripts/tests/opnsense_box.sh via `vm.py run`. POSIX sh: OPNsense has no bash, and FreeBSD's sh
# is what the plugin's scripts meet as well. The agent's tests run there through box_freebsdbox.sh.
#
#   sudo box_opnsensebox.sh pkg <dir>   as root: os-adminhelper and the agent of this checkout
#                                       from a signed local repo, the views against the real
#                                       configctl, one agent run with the opnsense module's
#                                       plan, the repository script, the settings switch and
#                                       pkg delete
#
# <dir> is what opnsense_box.sh built on the dev box, relative to the checkout. Each check prints
# `  ok` or `  FAIL`, an observation `  note` (not counted); the last line is
# `opnsbox <phase>: N passed, M failed`, and a failure ends with exit 1. Nothing is written into
# the checkout: the next `vm.py run --sync` deletes with --delete, and a root-owned file there
# would stop it.
set -u
# An ssh session's PATH and sudo's may both lack /usr/local, where configctl, php and pkg's packages are.
PATH=/sbin:/bin:/usr/sbin:/usr/bin:/usr/local/sbin:/usr/local/bin; export PATH
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT" || exit 1
PHASE="${1:?pkg}"; BUILD="$ROOT/${2:?build dir}"
PASS=0; FAIL=0
ok()   { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad()  { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }
note() { echo "  note $*"; }
done_phase() {
  echo "OPNS_${PHASE}_PASSED=$PASS OPNS_${PHASE}_FAILED=$FAIL"
  echo "opnsbox $PHASE: $PASS passed, $FAIL failed"
  [ "$FAIL" -eq 0 ]
  exit $?
}
# The package name as a variable: the box CLI check (box_cli_test.go) reads every bare
# `adminhelper-agent` word in these scripts as a call of the agent.
PKG=adminhelper-agent
PLUGIN=os-adminhelper
ETC=/usr/local/etc/adminhelper
RCVAR_FILE=/etc/rc.conf.d/adminhelper_frpc
CRON=/usr/local/etc/cron.d/adminhelper
FIXTURES=apps/agent/internal/opnsense/testdata

# What reaches the log of the dev box carries no address of the lab.
mask() { sed -E 's/[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+/<ip>/g; s/[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}/<mac>/g'; }

# report <file> — the PASS|, FAIL| and NOTE| lines of a PHP check as our own.
report() {
  while IFS='|' read -r kind text; do
    text="$(printf '%s' "$text" | mask)"
    case "$kind" in
      PASS) ok "$text" ;;
      FAIL) bad "$text" ;;
      NOTE) note "$text" ;;
      *) bad "unexpected line of a PHP check: $(printf '%s|%s' "$kind" "$text" | mask)" ;;
    esac
  done < "$1"
}

# wait_until <seconds> <command...> — asks every half second until the command succeeds; 1 once the
# seconds are up (testing.md, Fristen).
wait_until() {
  wu_end=$(($(date +%s) + $1))
  shift
  until "$@"; do
    [ "$(date +%s)" -lt "$wu_end" ] || return 1
    sleep 0.5
  done
}

# A stand-in for the monitoring service, built by opnsense_box.sh (sink.go of freebsd_box.sh). It
# writes its port to $WORK/sink/port, one report-N.json per POST there and a SINK_REPORT line to
# its log.
start_sink() {
  mkdir -p "$WORK/sink"
  nohup "$BUILD/sink" "$WORK/sink" </dev/null >"$WORK/sink.log" 2>&1 &
  SINK_PID=$!
  wait_until 30 test -s "$WORK/sink/port"
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

# The PHP helpers, written to $WORK: OPNsense brings PHP, and it reads JSON as configd's own
# scripts do.
write_php() {
  # keys.php <list|map|object|text> <real> <fixture> — the keys of a configctl output beside those
  # of its fixture: a list of objects, an object of objects, one object, or `word value` lines.
  cat > "$WORK/keys.php" <<'PHP'
<?php
function keys_of($kind, $path)
{
    $raw = (string)file_get_contents($path);
    if ($kind === 'text') {
        $keys = [];
        foreach (preg_split('/\R/', $raw) as $line) {
            $line = trim($line);
            if ($line !== '') {
                $keys[] = strtok($line, " \t");
            }
        }
        return $keys;
    }
    $data = json_decode($raw, true);
    if (!is_array($data)) {
        return null;
    }
    if ($kind === 'object') {
        return array_keys($data);
    }
    $keys = [];
    foreach ($data as $item) {
        if (is_array($item)) {
            $keys = array_merge($keys, array_keys($item));
        }
    }
    return $keys;
}
$real = keys_of($argv[1], $argv[2]);
$fixture = keys_of($argv[1], $argv[3]);
if ($real === null || $real === []) {
    echo "FAIL|{$argv[4]}: no {$argv[1]} in the output\n";
    exit;
}
$real = array_values(array_unique($real));
$fixture = array_values(array_unique($fixture ?? []));
echo "PASS|{$argv[4]}: " . count($real) . " keys\n";
$only_fixture = array_diff($fixture, $real);
$only_real = array_diff($real, $fixture);
if ($only_fixture) {
    echo "NOTE|{$argv[4]}: in the fixture only: " . implode(',', $only_fixture) . "\n";
}
if ($only_real) {
    echo "NOTE|{$argv[4]}: in the real output only: " . implode(',', $only_real) . "\n";
}
PHP
  # check.php <plan> <report> — every probe of the plan has its result in the report: status ok,
  # values, none outside its fields; the discovery found the module's marker.
  cat > "$WORK/check.php" <<'PHP'
<?php
$plan = json_decode((string)file_get_contents($argv[1]), true);
$report = json_decode((string)file_get_contents($argv[2]), true);
if (!is_array($plan) || !is_array($report)) {
    echo "FAIL|the plan or the report is no JSON\n";
    exit;
}
$results = is_array($report['probes'] ?? null) ? $report['probes'] : [];
foreach ($plan['probes'] as $probe) {
    $id = $probe['id'];
    $r = $results[$id] ?? null;
    if (!is_array($r)) {
        echo "FAIL|$id: no result in the report\n";
        continue;
    }
    if (($r['status'] ?? '') !== 'ok') {
        echo "FAIL|$id: status " . json_encode($r['status'] ?? null) . ', error ' . json_encode($r['error'] ?? null) . "\n";
        continue;
    }
    $values = is_array($r['values'] ?? null) ? $r['values'] : [];
    if (!$values) {
        echo "FAIL|$id: status ok without values\n";
        continue;
    }
    $outside = array_diff(array_keys($values), $probe['fields']);
    if ($outside) {
        echo "FAIL|$id: values outside the plan's fields: " . implode(',', $outside) . "\n";
        continue;
    }
    echo "PASS|$id: ok, " . count($values) . ' of ' . count($probe['fields']) . " fields\n";
    $missing = array_diff($probe['fields'], array_keys($values));
    if ($missing) {
        echo "NOTE|$id: no value for " . implode(',', $missing) . "\n";
    }
    echo "NOTE|$id: " . json_encode($values, JSON_UNESCAPED_SLASHES) . "\n";
}
$markers = $report['discovery']['markers'] ?? null;
if (is_array($markers) && ($markers['opnsense.core'] ?? null) === true) {
    echo "PASS|discovery: marker opnsense.core found\n";
} else {
    echo 'FAIL|discovery: markers ' . json_encode($markers) . "\n";
}
PHP
  # info.php <port> — the plugin's info action (configctl adminhelper info) on stdin, field by field.
  cat > "$WORK/info.php" <<'PHP'
<?php
$info = json_decode(stream_get_contents(STDIN), true);
if (!is_array($info)) {
    echo "FAIL|info: no JSON\n";
    exit;
}
$want = [
    'registered' => $info['registered'] === true,
    'server' => $info['server'] === "https://127.0.0.1:{$argv[1]}",
    'version' => is_string($info['version']) && $info['version'] !== '',
    'scheduled' => $info['scheduled'] === true,
    'tunnel' => $info['tunnel'] === 'running',
    'last_run' => is_int($info['last_run']) && $info['last_run'] > time() - 3600,
];
foreach ($want as $field => $good) {
    echo ($good ? 'PASS' : 'FAIL') . "|info $field: " . json_encode($info[$field] ?? null, JSON_UNESCAPED_SLASHES) . "\n";
}
PHP
  # service.php — exit 0 and the status if `configctl service list` (stdin) names adminhelper_frpc,
  # 1 if not, 2 without JSON.
  cat > "$WORK/service.php" <<'PHP'
<?php
$list = json_decode(stream_get_contents(STDIN), true);
if (!is_array($list)) {
    exit(2);
}
foreach ($list as $service) {
    if (is_array($service) && ($service['name'] ?? '') === 'adminhelper_frpc') {
        echo ($service['status'] ?? ''), PHP_EOL;
        exit(0);
    }
}
exit(1);
PHP
  # enabled.php <0|1> — the settings page's switch, saved through the model as its API does.
  cat > "$WORK/enabled.php" <<'PHP'
<?php
require_once '/usr/local/opnsense/mvc/script/load_phalcon.php';
$model = new OPNsense\AdminHelper\General();
$model->setNodes(['enabled' => $argv[1]]);
$model->serializeToConfig();
OPNsense\Core\Config::getInstance()->save();
echo (string)(new OPNsense\AdminHelper\General())->enabled, PHP_EOL;
PHP
}

# configd answers OK for an action of type script that exited 0.
configd_ok() { [ "$(configctl "$@" 2>&1 | tr -d '\n')" = OK ]; }
rcvar() { sed -n 's/^adminhelper_frpc_enable="\(.*\)"$/\1/p' "$RCVAR_FILE" 2>/dev/null; }
frpc_runs() { service adminhelper_frpc onestatus >/dev/null 2>&1; }
frpc_stopped() { ! frpc_runs; }
# rc.subr: "adminhelper_frpc is running as pid N."
frpc_pid() { service adminhelper_frpc onestatus 2>/dev/null | sed -n 's/.* as pid \([0-9]*\).*/\1/p'; }

# listed <yes|no> <when> — whether the services page lists the tunnel client.
listed() {
  configctl service list > "$WORK/services.json" 2>&1
  status="$(php "$WORK/service.php" < "$WORK/services.json")"
  rc=$?
  case "$1:$rc" in
    yes:0) ok "$2: service list names adminhelper_frpc ($status)" ;;
    no:1) ok "$2: service list leaves adminhelper_frpc out" ;;
    *:2) bad "$2: service list is no JSON: $(head -c 200 "$WORK/services.json" | mask)" ;;
    yes:*) bad "$2: service list does not name adminhelper_frpc" ;;
    no:*) bad "$2: service list names adminhelper_frpc ($status)" ;;
  esac
}

# switch_to <0|1> — the settings page's switch as its API applies it: the model, then the
# template, then reconfigure (ServiceController::reconfigureAction).
switch_to() {
  word=off; [ "$1" = 1 ] && word=on
  set_to="$(php "$WORK/enabled.php" "$1" 2>&1)"
  [ "$set_to" = "$1" ] && ok "switch $word: the model holds enabled=$1" || bad "switch $word: the model holds $(printf '%s' "$set_to" | head -c 200)"
  configd_ok template reload OPNsense/AdminHelper \
    && ok "switch $word: template reload OK" || bad "switch $word: template reload failed"
  configd_ok adminhelper reconfigure "$word" \
    && ok "switch $word: configctl adminhelper reconfigure $word OK" || bad "switch $word: reconfigure $word failed"
}

phase_pkg() {
  [ "$(id -u)" = 0 ] || { bad "the pkg phase runs as root"; return; }
  WORK="$(mktemp -d /var/tmp/opnsbox.XXXXXX)" || { bad "mktemp"; return; }
  echo "[opnsbox] work dir $WORK, $(opnsense-version) on FreeBSD $(uname -r)"
  df -h / | sed 's/^/      /'
  export ASSUME_ALWAYS_YES=yes
  write_php

  echo "[opnsbox] php -l with OPNsense's PHP"
  find apps/agent/opnsense/src -type f \( -name '*.php' -o -name '*.inc' \) > "$WORK/php-files"
  n=0; nbad=0
  while read -r f; do
    n=$((n + 1))
    php -l "$f" >"$WORK/php-l.log" 2>&1 || { nbad=$((nbad + 1)); bad "php -l $f"; sed 's/^/      /' "$WORK/php-l.log"; }
  done < "$WORK/php-files"
  if [ "$n" -eq 0 ]; then
    bad "no .php or .inc below apps/agent/opnsense/src"
  elif [ "$nbad" -eq 0 ]; then
    ok "php -l (PHP $(php -r 'echo PHP_VERSION;')): $n files"
  fi

  echo "[opnsbox] package: build-pkg.sh needs bash, which is there for the build only"
  ! pkg info -e "$PKG" && ! pkg info -e "$PLUGIN" \
    && ok "neither $PKG nor $PLUGIN installed before" || bad "$PKG or $PLUGIN installed before the test"
  if pkg install -y bash >"$WORK/bash.log" 2>&1; then
    ok "bash for the build ($(pkg query %n-%v bash))"
  else
    bad "pkg install bash"; tail -n 20 "$WORK/bash.log" | sed 's/^/      /'; return
  fi
  if openssl genrsa -out "$WORK/repo.key" 4096 2>/dev/null \
     && openssl rsa -in "$WORK/repo.key" -pubout -out "$WORK/repo.pub" 2>/dev/null; then
    ok "throwaway signing key"
  else
    bad "openssl could not make the throwaway key"; return
  fi
  if VERSION=0.0.1 AGENT_BINARY="$BUILD/adminhelper-agent-freebsd" FRPC_BINARY="$BUILD/frpc" \
       OUT_DIR="$WORK/out" PKG_REPO_KEY="$WORK/repo.key" bash apps/agent/build-pkg.sh >"$WORK/build.log" 2>&1; then
    ok "build-pkg.sh: $(cd "$WORK/out/freebsd" && ls -1 ./*/All/*.pkg | tr '\n' ' ')"
  else
    bad "build-pkg.sh"; tail -n 40 "$WORK/build.log" | sed 's/^/      /'; return
  fi
  # Nothing of the plugin or the agent may need bash: the rest of this phase runs without it.
  if pkg delete -y bash >"$WORK/bash-delete.log" 2>&1 && ! pkg info -e bash && [ ! -e /usr/local/bin/bash ]; then
    ok "bash removed again"
  else
    bad "pkg delete bash"; tail -n 20 "$WORK/bash-delete.log" | sed 's/^/      /'
  fi

  echo "[opnsbox] pkg install $PLUGIN from the signed repo pulls in the agent"
  repo_conf "$WORK/repos" ahbox "$WORK/repo.pub"
  if pkg -R "$WORK/repos" update -f -r ahbox >"$WORK/update.log" 2>&1 \
     && found="$(pkg -R "$WORK/repos" rquery -r ahbox %n-%v "$PLUGIN" 2>>"$WORK/update.log")" \
     && [ "$found" = "$PLUGIN-0.0.1" ]; then
    ok "the signed repo loads ($found)"
  else
    bad "pkg update/rquery from the signed repo"; tail -n 30 "$WORK/update.log" | sed 's/^/      /'; return
  fi
  if pkg -R "$WORK/repos" install -y -r ahbox "$PLUGIN" >"$WORK/install.log" 2>&1; then
    ok "pkg install $PLUGIN ($(pkg query %n-%v "$PLUGIN"))"
  else
    bad "pkg install $PLUGIN"; tail -n 30 "$WORK/install.log" | sed 's/^/      /'; return
  fi
  # %a: installed as a dependency, not asked for.
  agent="$(pkg query '%n-%v %a' "$PKG" 2>/dev/null)"
  [ "$agent" = "$PKG-0.0.1 1" ] && ok "the agent came along as a dependency ($agent)" \
    || bad "the agent did not come along as a dependency: '$agent'"
  grep -q '^Reloading template OPNsense/AdminHelper: OK$' "$WORK/install.log" \
    && ok "+POST_INSTALL: template reload OK" \
    || { bad "+POST_INSTALL: no 'Reloading template OPNsense/AdminHelper: OK'"; sed 's/^/      /' "$WORK/install.log" | tail -n 20; }
  pkg info -ql "$PLUGIN" > "$WORK/files"
  missing=0
  while read -r f; do [ -e "$f" ] || { bad "listed but not installed: $f"; missing=$((missing + 1)); }; done < "$WORK/files"
  listed_files="$(wc -l < "$WORK/files" | tr -d ' ')"
  if [ "$listed_files" -eq 0 ]; then
    bad "pkg info -ql $PLUGIN lists no file"
  elif [ "$missing" -eq 0 ]; then
    ok "every file of $PLUGIN installed ($listed_files)"
  fi
  abi="$(php -r 'echo json_decode(file_get_contents($argv[1]), true)["product_abi"] ?? "";' /usr/local/opnsense/version/adminhelper)"
  [ "$abi" = "$(opnsense-version -a)" ] && ok "version file: product_abi $abi is this OPNsense's" \
    || bad "version file: product_abi '$abi', this OPNsense is $(opnsense-version -a)"
  [ "$(rcvar)" = NO ] && ok "$RCVAR_FILE: NO without a tunnel" || bad "$RCVAR_FILE: '$(rcvar)' without a tunnel"
  case "$(configctl adminhelper status 2>&1)" in
    *"is not running"*) ok "configd knows the plugin's actions (adminhelper status: not running)" ;;
    *) bad "configctl adminhelper status: $(configctl adminhelper status 2>&1 | head -c 200)" ;;
  esac
  listed no "without a tunnel"

  echo "[opnsbox] the views against the real configctl, beside their fixtures"
  for spec in "services list services.json service list" \
              "gateways map gateways.json interface gateways status" \
              "firmware object firmware.json firmware product" \
              "states text states.txt filter diag state_size" \
              "carp object carp_global.json interface show carp" \
              "ifconfig map carp_ifconfig.json interface list ifconfig"; do
    # shellcheck disable=SC2086 # the configctl arguments are words
    set -- $spec
    name="$1" kind="$2" fixture="$3"; shift 3
    if configctl "$@" >"$WORK/raw-$name" 2>&1 && [ -s "$WORK/raw-$name" ]; then
      php "$WORK/keys.php" "$kind" "$WORK/raw-$name" "$FIXTURES/$fixture" "configctl $*" > "$WORK/keys-$name"
      report "$WORK/keys-$name"
      # ifconfig's raw output is all addresses: its keys say enough.
      [ "$name" = ifconfig ] || echo "      $(tr -s ' \n\t' '   ' < "$WORK/raw-$name" | head -c 240 | mask)"
    else
      bad "configctl $*: $(head -c 200 "$WORK/raw-$name" | mask)"
    fi
  done

  echo "[opnsbox] firmware product opens no network connection (ktrace of configd)"
  # configd runs the action in a child of its daemon: -d takes the children there are, -i the
  # ones to come. sockstat would miss a connection that came and went between two looks.
  cpid="$(cat /var/run/configd.pid 2>/dev/null)"
  if [ -n "$cpid" ] && ktrace -d -i -t cnt -f "$WORK/fw.ktr" -p "$cpid"; then
    configctl firmware product >/dev/null 2>&1
    ktrace -c -d -p "$cpid"
    kdump -f "$WORK/fw.ktr" > "$WORK/fw.kdump" 2>&1
    execs="$(grep -c 'CALL  execve' "$WORK/fw.kdump")"
    # Proof that the trace saw the action: its execve calls, product.php among the names.
    if [ "$execs" -gt 0 ] && grep -q 'product\.php' "$WORK/fw.kdump"; then
      ok "the trace saw firmware product run ($execs execve)"
    else
      bad "the trace did not see firmware product run ($execs execve)"
    fi
    inet="$(grep -c 'AF_INET' "$WORK/fw.kdump")"
    if [ "$inet" -eq 0 ]; then
      ok "firmware product: no AF_INET/AF_INET6 address in $(grep -c 'struct sockaddr' "$WORK/fw.kdump") sockaddrs"
    else
      bad "firmware product reached for the network ($inet AF_INET lines):"
      grep 'AF_INET' "$WORK/fw.kdump" | head -n 10 | mask | sed 's/^/      /'
    fi
  else
    bad "ktrace of configd (pid '${cpid}')"
  fi
  # The control: ktrace records the address of a connect at all.
  ktrace -i -t cnt -f "$WORK/nc.ktr" nc -z -w 2 127.0.0.1 9 >/dev/null 2>&1
  kdump -f "$WORK/nc.ktr" 2>/dev/null | grep 'struct sockaddr' | grep -q 'AF_INET.*127\.0\.0\.1' \
    && ok "control: the trace of nc -z 127.0.0.1 9 holds its AF_INET address" \
    || bad "control: the trace of nc holds no AF_INET address, the check above proves nothing"

  echo "[opnsbox] one agent run with the opnsense module's plan"
  if start_sink; then
    ok "sink on 127.0.0.1:$SINK_PORT"
    if adminhelper-agent monitor init --url "https://127.0.0.1:$SINK_PORT/api/monitoring" \
         --api-key opnsbox --server-id 7 --insecure >"$WORK/init.log" 2>&1; then
      ok "monitor init"
    else
      bad "monitor init"; sed 's/^/      /' "$WORK/init.log"
    fi
    # init schedules the agent every five minutes. Off until the switch turns it on: no cron run
    # crosses the one below, and reconfigure on has the schedule to write.
    if [ -f "$CRON" ] && adminhelper-agent service uninstall >"$WORK/uninstall.log" 2>&1 && [ ! -e "$CRON" ]; then
      ok "init scheduled the agent; unscheduled until the switch"
    else
      bad "monitor init wrote no $CRON, or service uninstall left it"; sed 's/^/      /' "$WORK/uninstall.log"
    fi
    # The sink answers {} for the plan, which the agent refuses and keeps its saved one: this.
    install -m 600 "$BUILD/plan.json" "$ETC/.plan.json"
    before="$(grep -c '^SINK_REPORT' "$WORK/sink.log")"
    if adminhelper-agent run --once >"$WORK/run.log" 2>&1; then
      ok "run --once exit 0"
    else
      bad "run --once"; tail -n 30 "$WORK/run.log" | mask | sed 's/^/      /'
    fi
    after="$(grep -c '^SINK_REPORT' "$WORK/sink.log")"
    last="$(grep '^SINK_REPORT' "$WORK/sink.log" | tail -n 1)"
    if [ "$after" -gt "$before" ] && [ -s "$WORK/sink/report-$after.json" ]; then
      case "$last" in *" path=/api/monitoring/agent/7/report "*) ok "the run pushed its report" ;; *) bad "report endpoint: $last" ;; esac
      php "$WORK/check.php" "$BUILD/plan.json" "$WORK/sink/report-$after.json" > "$WORK/check.out"
      report "$WORK/check.out"
    else
      bad "no report reached the sink during run --once"; mask < "$WORK/sink.log" | sed 's/^/      /'
    fi
  else
    bad "the sink did not start"; sed 's/^/      /' "$WORK/sink.log"
  fi

  echo "[opnsbox] the repository script points pkg at the server the agent is registered with"
  repo=/usr/local/etc/pkg/repos/AdminHelper.conf
  configctl firmware reload >"$WORK/reload.log" 2>&1
  # shellcheck disable=SC2016 # ${ABI} is pkg's, literally in the file
  if grep -qF 'url: "https://127.0.0.1:8445/freebsd/${ABI}",' "$repo" 2>/dev/null \
     && grep -qF 'SSL_NO_VERIFY_PEER: "1"' "$repo"; then
    ok "firmware reload wrote $repo (the monitoring host, port 8445, unverified until enrolled)"
  else
    bad "firmware reload: $repo is not the expected one"; mask < "$repo" 2>/dev/null | sed 's/^/      /'
  fi
  pkg -vv > "$WORK/pkg-vv" 2>&1
  grep -q '^  AdminHelper: {' "$WORK/pkg-vv" && ok "pkg -vv lists the AdminHelper repository" \
    || bad "pkg -vv lists no AdminHelper repository"

  echo "[opnsbox] the switch: rcvar, services page, schedule and tunnel"
  mkdir -p "$ETC/frp"
  # No frps behind it: loginFailExit = false keeps frpc retrying instead of exiting.
  printf 'serverAddr = "127.0.0.1"\nserverPort = 7\nloginFailExit = false\n' > "$ETC/frp/frpc.toml"
  configd_ok template reload OPNsense/AdminHelper && [ "$(rcvar)" = YES ] \
    && ok "with a tunnel: $RCVAR_FILE YES" || bad "with a tunnel: $RCVAR_FILE '$(rcvar)'"
  listed yes "with a tunnel"
  configd_ok adminhelper reconfigure on && ok "configctl adminhelper reconfigure on OK" \
    || bad "configctl adminhelper reconfigure on failed"
  wait_until 30 frpc_runs && ok "on: frpc runs" || bad "on: frpc does not run"
  [ -f "$CRON" ] && ok "on: the agent is scheduled ($CRON)" || bad "on: no $CRON"
  configd_ok adminhelper stop && wait_until 30 frpc_stopped && ok "configctl adminhelper stop: frpc stopped" \
    || bad "configctl adminhelper stop"
  configd_ok adminhelper start && wait_until 30 frpc_runs && ok "configctl adminhelper start: frpc runs" \
    || bad "configctl adminhelper start"
  started_pid="$(frpc_pid)"
  case "$(configctl adminhelper status 2>&1)" in
    *"is running"*) ok "configctl adminhelper status: running" ;;
    *) bad "configctl adminhelper status: $(configctl adminhelper status 2>&1 | head -c 200)" ;;
  esac
  configctl adminhelper info > "$WORK/info.json" 2>&1
  php "$WORK/info.php" "${SINK_PORT:-0}" < "$WORK/info.json" > "$WORK/info.out"
  report "$WORK/info.out"
  # The same pid after the status and info calls: frpc stays up without an frps (loginFailExit), so
  # the stops that follow stop it, and it did not end by itself.
  [ -n "$started_pid" ] && [ "$(frpc_pid)" = "$started_pid" ] && ok "frpc stays up (pid $started_pid)" \
    || bad "frpc did not stay up: pid '$started_pid', now '$(frpc_pid)'"

  switch_to 0
  [ "$(rcvar)" = NO ] && ok "off: $RCVAR_FILE NO" || bad "off: $RCVAR_FILE '$(rcvar)'"
  wait_until 30 frpc_stopped && ok "off: frpc stopped" || bad "off: frpc still runs"
  [ -e "$CRON" ] && bad "off: $CRON left" || ok "off: the schedule is gone"
  listed no "off"
  [ -f "$ETC/monitor.conf" ] && [ -f "$ETC/frp/frpc.toml" ] && ok "off: the registration stays" \
    || bad "off: the agent's files are gone"

  switch_to 1
  [ "$(rcvar)" = YES ] && ok "on again: $RCVAR_FILE YES" || bad "on again: $RCVAR_FILE '$(rcvar)'"
  wait_until 30 frpc_runs && ok "on again: frpc runs" || bad "on again: frpc does not run"
  [ -f "$CRON" ] && ok "on again: scheduled" || bad "on again: no $CRON"
  listed yes "on again"
  [ -n "${SINK_PID:-}" ] && kill "$SINK_PID" 2>/dev/null

  echo "[opnsbox] pkg delete $PLUGIN takes the plugin, the agent stays"
  if pkg delete -y "$PLUGIN" >"$WORK/delete.log" 2>&1; then
    ok "pkg delete $PLUGIN"
  else
    bad "pkg delete $PLUGIN"; sed 's/^/      /' "$WORK/delete.log"
  fi
  left=0
  while read -r f; do [ -e "$f" ] && { bad "left after pkg delete: $f"; left=$((left + 1)); }; done < "$WORK/files"
  [ "$left" -eq 0 ] && ok "every file of $PLUGIN removed (menu, model, templates, actions, version file)"
  [ ! -e "$repo" ] && ok "+POST_DEINSTALL removed $repo" || bad "$repo left"
  pkg info -e "$PKG" && ok "$PKG stays installed" || bad "$PKG went with the plugin"
  note "after the plugin: $RCVAR_FILE $(rcvar), frpc $(frpc_runs && echo runs || echo stopped)"
  service adminhelper_frpc faststop >/dev/null 2>&1

  [ "$FAIL" -eq 0 ] && rm -rf -- "$WORK"
}

case "$PHASE" in
  pkg) phase_pkg ;;
  *) bad "unknown phase $PHASE" ;;
esac
done_phase
