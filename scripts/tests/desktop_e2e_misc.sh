#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# desktop_e2e_misc.sh — the live desktop specs no other desktop_e2e_*.sh runs.
#
# Five specs existed in apps/desktop/e2e/test/specs/ without an orchestration
# script: login-error, logout, monitoring-alerts, connection-editor,
# theme-toggle. They were linted and reachable ad hoc via `crabbox_iter.sh
# --desktop <spec>`, but no suite ran them, so nothing in the heavy tier would
# have noticed them breaking. They share one stack and one seed here.
#
# Boots the stack permissive (login by JWT is enough — none of the five needs an
# enrolled identity) WITH the monitoring service, since the alerts tab talks to
# it. Seeds an admin + a server + an FRP config, then drives the real app under
# xvfb in a fresh D-Bus session with an empty gnome-keyring.
#
# AH_SPEC=<name> runs exactly one of them ("theme-toggle", or the full
# test/specs/theme-toggle.live.js — the basename is what counts). heavy.sh uses
# it to re-run a single red spec.
#
# Boot/seed/teardown are shared via lib_e2e_stack.sh. Needs the same tools as
# desktop_e2e_live.sh; SKIPs (exit 75) when any is missing.
# Run: bash scripts/tests/desktop_e2e_misc.sh

# shellcheck disable=SC2015
set -uo pipefail

# shellcheck source=scripts/tests/lib_e2e_stack.sh
. "$(cd "$(dirname "$0")" && pwd)/lib_e2e_stack.sh"

E2E_DIR="$E2E_REPO_ROOT/apps/desktop/e2e"

# Order is cosmetic — every spec gets its own app, its own driver and its own
# keyring, so none can influence the next. Cheapest first anyway.
SPECS="login-error logout theme-toggle connection-editor monitoring-alerts"

PASS=0
FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

# AH_SPEC narrows the run to one spec. Rejected when unknown: a typo would
# otherwise run nothing and exit 0 — a green that verified nothing.
if [ -n "${AH_SPEC:-}" ]; then
    want="${AH_SPEC##*/}"; want="${want%.live.js}"
    case " $SPECS " in
        *" $want "*) SPECS="$want" ;;
        *) echo "unknown AH_SPEC '$AH_SPEC' — known: $SPECS"; exit 2 ;;
    esac
fi

e2e_require node xvfb-run WebKitWebDriver tauri-driver dbus-run-session gnome-keyring-daemon
( cd "$E2E_REPO_ROOT/apps/desktop/src-tauri" && cargo tauri --version >/dev/null 2>&1 ) \
    || { echo "SKIP: tauri-cli (cargo tauri) not available"; exit 75; }

# Standalone-run self-sufficiency (fresh box, no prior run.sh layer): without the
# local node_modules, `npx wdio` fetches the interactive wizard instead of the
# local @wdio/cli, and the tauri beforeBuildCommand dies on `svelte-check: not found`.
( cd "$E2E_REPO_ROOT/apps/desktop/ui" && { [ -d node_modules ] || npm ci; } ) || exit 1
( cd "$E2E_DIR" && { [ -d node_modules ] || npm ci; } ) || exit 1

e2e_init false                                 # permissive: login (JWT) reaches the API
e2e_up gateway monitoring \
    && ok "gateway + monitoring live on :$E2E_HTTPS_PORT" \
    || { bad "stack never came up"; e2e_dc logs --tail 40 monitoring; exit 1; }

# ── Seed an admin token + a server + an FRP config ───────────────────────────
TOKEN=$(e2e_admin_token)
[ -n "$TOKEN" ] && ok "admin login through the gateway" || { bad "admin login failed"; e2e_dc logs --tail 40 server; exit 1; }
e2e_api "$TOKEN" server e2e-server e2e.local >/dev/null || { bad "seed server"; exit 1; }
e2e_api "$TOKEN" config e2e-frps localhost 7000 >/dev/null || { bad "seed FRP config"; exit 1; }
ok "seeded a server + FRP config"

# ── Isolated app config: server mode + trust the stack's self-signed cert ─────
XDG_DATA_HOME="$E2E_WORK/xdg-data"; export XDG_DATA_HOME
mkdir -p "$XDG_DATA_HOME/com.admincave.adminhelper"
echo '{"mode": "server", "allowSelfSignedCerts": true}' > "$XDG_DATA_HOME/com.admincave.adminhelper/settings.json"

export AH_SERVER_URL="$E2E_SERVER_URL" AH_ADMIN_USER="admin" AH_ADMIN_PASS="$E2E_ADMIN_PW" E2E_DIR

# ── Drive the GUI, one spec per wdio run ─────────────────────────────────────
# One wdio run per spec, not one run with five --spec: a single run yields a
# single exit code, and the per-spec `pass|fail` line is the point of this
# script. wdio already isolates per spec FILE, so the only price is five
# `onPrepare` builds (~5-10 min in the heavy tier). Same shape as
# crabbox_desktopbox.sh.
for s in $SPECS; do
    echo "[e2e-misc] running $s under xvfb..."
    SPEC="test/specs/$s.live.js"; export SPEC
    # Fresh D-Bus session + empty gnome-keyring → a CLEAN app keyring: the real
    # one may hold an enrolled identity whose pinned CA rejects this throwaway
    # stack's gateway cert (is_enrolled() true → login fails CA-pin/MITM).
    if dbus-run-session -- bash -c '
        eval "$(printf "\n" | gnome-keyring-daemon --unlock --components=secrets 2>/dev/null)" || true
        export GNOME_KEYRING_CONTROL SSH_AUTH_SOCK
        cd "$E2E_DIR" && xvfb-run -a npx wdio run wdio.conf.js --spec "$SPEC"
    '; then
        echo "spec $s: pass"; ok "spec $s"
    else
        echo "spec $s: fail"; bad "spec $s"
    fi
done

echo ""
echo "desktop_e2e_misc: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
