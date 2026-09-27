#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# web_live.sh — the web admin panel against the real stack: Playwright's `live`
# project (apps/web/tests/live), no mocks (run.sh integration, step web-live).
#
# The chromium project keeps running in the PR CI against mockApi; this one logs
# in as the seed admin the stack creates and writes for real, so what the mocks
# promise about the API is checked against the API itself.
#
# JUnit lands in $AH_OUT_DIR/junit/web-live.xml: PLAYWRIGHT_JUNIT_OUTPUT_FILE
# wins over the config's outputFile (web-playwright.xml stays the e2e step's).
#
# Exit: 0 green · 1 red, or the stack/browser could not be set up · 75 a
# precondition is missing (docker, compose, node, npx, …)
#
# Run: bash scripts/tests/web_live.sh

set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=scripts/tests/lib_e2e_stack.sh
. "$HERE/lib_e2e_stack.sh"

e2e_require node npm npx
e2e_init false   # permissive edge: the browser has no client certificate
e2e_up gateway || { echo "[web-live] the stack never answered on :$E2E_HTTPS_PORT"; exit 1; }
# The admin exists once the server's startup has created it from ADMIN_PASSWORD;
# a login before that would fail for a reason that is not the UI's.
[ -n "$(e2e_admin_token)" ] || { echo "[web-live] the seed admin never became able to log in"; exit 1; }

export AH_OUT_DIR="${AH_OUT_DIR:-$E2E_REPO_ROOT/.ah-out}"
export ITEST_WEB_URL="$E2E_SERVER_URL" ITEST_ADMIN_PW="$E2E_ADMIN_PW"
cd "$E2E_REPO_ROOT/apps/web" || exit 1
# run.sh's npm_ci_if_stale, for a run of this script on its own.
if [ ! -d node_modules ] || [ package-lock.json -nt node_modules ]; then
  npm ci --no-audit --no-fund || exit 1
fi
npx playwright install --with-deps chromium || exit 1
echo "[web-live] Playwright project live against $ITEST_WEB_URL"
PLAYWRIGHT_JUNIT_OUTPUT_FILE="$AH_OUT_DIR/junit/web-live.xml" npx playwright test --project live
