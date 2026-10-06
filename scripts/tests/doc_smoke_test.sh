#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# doc_smoke_test.sh — hermetic test for scripts/dev/doc-smoke.py.
#
# Fixture checkouts under --root: a docs/ tree, a few real files to point at and
# an allow list. No network, no repo state — python3 and coreutils. The check is
# a gate whose value is being red for the right reason, so every case asserts the
# exit code AND the wording that names the finding.
#
# Run: bash scripts/tests/doc_smoke_test.sh

set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
CHECK="$HERE/../dev/doc-smoke.py"

PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

command -v python3 >/dev/null 2>&1 || { echo "python3 not installed — skipping (75)"; exit 75; }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# fixture <dir> — a git checkout whose docs reference 48 tracked paths. The
# collector refuses to pass on a thin scan, so a fixture below that floor tests
# nothing; and it resolves existence through `git ls-files`, so the fixture has
# to be a real repository — that is the code path CI takes.
fixture() {
  local d="$1" i
  mkdir -p "$d/docs/developer" "$d/scripts/dev" "$d/apps/server/app/core" "$d/apps/monitoring/app/core" "$d/apps/ca-issuer/app" "$d/apps/server/real"
  for i in $(seq 1 48); do
    : > "$d/apps/server/real/file${i}.py"
  done
  {
    echo '<html><body>'
    for i in $(seq 1 48); do
      echo "  <p>siehe <code>apps/server/real/file${i}.py</code></p>"
    done
    echo '</body></html>'
  } > "$d/docs/developer/good.html"
  printf 'DATABASE_URL = os.environ.get("DATABASE_URL", "")\n' > "$d/apps/server/app/core/config.py"
  printf 'MONITOR_API_KEY = os.environ.get("MONITOR_API_KEY", "")\n' > "$d/apps/monitoring/app/core/config.py"
  printf 'CA_ROOT_PASSPHRASE = os.environ.get("CA_ROOT_PASSPHRASE", "")\n' > "$d/apps/ca-issuer/app/config.py"
  # .env.example carries the rest of the known names (the floor is 10).
  printf 'SECRET_KEY=\nADMIN_PASSWORD=\nDOMAIN=\nTZ=\nLOG_LEVEL=\n# SMTP_HOST=\n# SMTP_PORT=\n# MTLS_ENFORCE=\n# ENROLL_PORT=\n# WEB_CONCURRENCY=\n' > "$d/.env.example"
  git -C "$d" init -q
  git -C "$d" config user.email t@example.com
  git -C "$d" config user.name Test
  git -C "$d" add -A
  git -C "$d" commit -qm fixture
}

# run_case <name> <expect-rc> <expect-substring> -- <args...>
run_case() {
  local name="$1" want_rc="$2" want="$3"; shift 3; [ "$1" = "--" ] && shift
  local out rc=0
  out=$(python3 "$CHECK" "$@" 2>&1) || rc=$?
  if [ "$rc" != "$want_rc" ]; then
    bad "$name: rc=$rc (expected $want_rc)"; printf '%s\n' "$out" | sed 's/^/       /'; return
  fi
  if [ -n "$want" ] && ! printf '%s' "$out" | grep -qF -- "$want"; then
    bad "$name: output does not mention '$want'"; printf '%s\n' "$out" | sed 's/^/       /'; return
  fi
  ok "$name"
}

# ── a documentation that matches its tree is clean ───────────────────────────
REPO="$WORK/r1"; fixture "$REPO"
run_case "matching docs -> exit 0" 0 "matches the tree" -- --strict --root "$REPO"

# ── a path that no longer exists is a finding, named with file and line ──────
REPO="$WORK/r2"; fixture "$REPO"
echo '<p>alt: <code>apps/server/app/gone.py</code></p>' >> "$REPO/docs/developer/good.html"
run_case "missing path -> exit 1 under --strict" 1 "apps/server/app/gone.py" -- --strict --root "$REPO"
run_case "missing path names file:line" 1 "good.html:" -- --strict --root "$REPO"
# Without --strict the finding is information, not a gate.
run_case "missing path -> exit 0 without --strict" 0 "apps/server/app/gone.py" -- --root "$REPO"

# ── the allow list silences exactly its entry ────────────────────────────────
REPO="$WORK/r3"; fixture "$REPO"
echo '<p>alt: <code>apps/server/app/gone.py</code></p>' >> "$REPO/docs/developer/good.html"
printf 'apps/server/app/gone.py  # bewusst: Beispielpfad\n' > "$REPO/scripts/dev/doc-smoke-allow.txt"
run_case "allowlisted path -> exit 0" 0 "matches the tree" -- --strict --root "$REPO"

# ── more than five exceptions is a refusal, not a bigger list ────────────────
REPO="$WORK/r4"; fixture "$REPO"
for i in 1 2 3 4 5 6; do echo "apps/server/app/gone${i}.py  # Grund ${i}" >> "$REPO/scripts/dev/doc-smoke-allow.txt"; done
run_case "6 allow entries -> exit 2" 2 "the cap is 5" -- --strict --root "$REPO"

# ── an unknown env name is a finding only under --env ────────────────────────
REPO="$WORK/r5"; fixture "$REPO"
echo '<p><code>NICHT_BEKANNTE_VARIABLE</code> und <code>DATABASE_URL</code></p>' >> "$REPO/docs/developer/good.html"
run_case "unknown env name -> exit 1 under --env" 1 "NICHT_BEKANNTE_VARIABLE" -- --env --strict --root "$REPO"
# The output first, then grep: under pipefail a pipe takes python's exit, and the
# finding above makes that 1 — the if would never see the grep.
out=$(python3 "$CHECK" --env --strict --root "$REPO" 2>&1)
if printf '%s\n' "$out" | grep -q "DATABASE_URL"; then
  bad "a documented env name that the config reads was reported"
else
  ok "known env name is not reported"
fi
# The path check must not report it either way.
run_case "env name is no path finding" 0 "matches the tree" -- --paths --strict --root "$REPO"

# ── a name the rest of the repository carries is known (R-0044) ──────────────
# The docs name more than the services read in config.py: agent settings, CI
# secrets, harness variables, states, constants. A tracked file outside docs/ makes
# a name known; the changelog, the ledgers and an untracked file do not.
REPO="$WORK/r5c"; fixture "$REPO"
mkdir -p "$REPO/scripts/tests" "$REPO/tasks"
printf 'AH_FIXTURE_FLAG=1\n' > "$REPO/scripts/tests/tool.sh"
printf 'CHECK_KIND_FIXTURE = "x"\n' > "$REPO/apps/server/real/consts.py"
printf -- '- removed HISTORIC_ONLY_NAME\n' > "$REPO/CHANGELOG.md"
printf 'Notiz: LEDGER_ONLY_NAME\n' > "$REPO/tasks/x.md"
git -C "$REPO" add -A; git -C "$REPO" commit -qm "more names"
printf 'UNTRACKED_ONLY_NAME=1\n' > "$REPO/scripts/tests/local.sh"
echo '<p><code>AH_FIXTURE_FLAG</code> und <code>CHECK_KIND_FIXTURE</code></p>' >> "$REPO/docs/developer/good.html"
run_case "names a tracked script or module carries -> clean under --env" 0 "matches the tree" -- --env --strict --root "$REPO"
for n in HISTORIC_ONLY_NAME LEDGER_ONLY_NAME UNTRACKED_ONLY_NAME; do
  echo "<p><code>$n</code></p>" >> "$REPO/docs/developer/good.html"
done
run_case "a name only in CHANGELOG.md -> finding" 1 "HISTORIC_ONLY_NAME" -- --env --strict --root "$REPO"
run_case "a name only in tasks/ -> finding" 1 "LEDGER_ONLY_NAME" -- --env --strict --root "$REPO"
run_case "a name only in an untracked file -> finding" 1 "UNTRACKED_ONLY_NAME" -- --env --strict --root "$REPO"
# --paths --env runs both checks, the form the CI gate uses (R-0044); --env alone
# turns the path check off, which is why the gate names both flags.
REPO="$WORK/r5e"; fixture "$REPO"
echo '<p><code>apps/server/app/gone.py</code> und <code>NICHT_BEKANNTE_VARIABLE</code></p>' >> "$REPO/docs/developer/good.html"
run_case "--paths --env --strict: the path finding" 1 "apps/server/app/gone.py" -- --paths --env --strict --root "$REPO"
run_case "--paths --env --strict: the name finding" 1 "NICHT_BEKANNTE_VARIABLE" -- --paths --env --strict --root "$REPO"
out=$(python3 "$CHECK" --env --strict --root "$REPO" 2>&1)
if printf '%s\n' "$out" | grep -q "apps/server/app/gone.py"; then
  bad "--env alone reported a path"
elif ! printf '%s\n' "$out" | grep -q "NICHT_BEKANNTE_VARIABLE"; then
  bad "--env alone did not run the name check: $out"
else
  ok "--env alone checks no path"
fi
# A whole word only: HTTPServer does not make HTTPS known, nor getFOO_BAR FOO_BAR.
REPO="$WORK/r5f"; fixture "$REPO"
printf 'class HTTPServer: pass\nvalue = getFOO_BAR()\n' > "$REPO/apps/server/real/words.py"
git -C "$REPO" add -A; git -C "$REPO" commit -qm "words inside words"
echo '<p><code>HTTPS</code> und <code>FOO_BAR</code></p>' >> "$REPO/docs/developer/good.html"
run_case "a word inside a longer identifier is not known (HTTPS)" 1 "HTTPS" -- --env --strict --root "$REPO"
run_case "a word inside a longer identifier is not known (FOO_BAR)" 1 "FOO_BAR" -- --env --strict --root "$REPO"
# Outside a repository the three config.py files and .env.example remain the sources.
REPO="$WORK/r5d"; fixture "$REPO"
printf 'AH_FIXTURE_FLAG=1\n' > "$REPO/scripts/dev/tool.sh"
rm -rf -- "$REPO/.git"
echo '<p><code>DATABASE_URL</code></p>' >> "$REPO/docs/developer/good.html"
run_case "no repository: a name a config.py reads stays known" 0 "matches the tree" -- --env --strict --root "$REPO"
echo '<p><code>AH_FIXTURE_FLAG</code></p>' >> "$REPO/docs/developer/good.html"
run_case "no repository: only the old sources count" 1 "AH_FIXTURE_FLAG" -- --env --strict --root "$REPO"

# ── a path that exists only in the working tree is NOT a path ───────────────
# This is the bug the check had: `apps/web/dist/` exists on a developer box and
# never in a fresh checkout, so a filesystem test passes locally and the CI job
# is red — a gate that disagrees with the runner is worse than no gate.
REPO="$WORK/r5b"; fixture "$REPO"
mkdir -p "$REPO/apps/web/dist"
: > "$REPO/apps/web/dist/index.html"
printf 'apps/web/dist/\n' > "$REPO/.gitignore"
echo '<p>Build-Ausgabe: <code>apps/web/dist/</code></p>' >> "$REPO/docs/developer/good.html"
run_case "untracked build output -> finding" 1 "apps/web/dist/" -- --strict --root "$REPO"
printf 'apps/web/dist/  # Build-Ausgabe\n' > "$REPO/scripts/dev/doc-smoke-allow.txt"
run_case "untracked build output can be allowlisted" 0 "matches the tree" -- --strict --root "$REPO"

# ── a thin scan is a broken scan, not a clean documentation ──────────────────
REPO="$WORK/r6"; mkdir -p "$REPO/docs"
echo '<p><code>apps/server/app/only.py</code></p>' > "$REPO/docs/thin.html"
run_case "too few distinct paths -> exit 2" 2 "floor is 45" -- --strict --root "$REPO"

# ── a highlighted <code class="…"> must not fall out of the scan ─────────────
REPO="$WORK/r7"; fixture "$REPO"
echo '<p><code class="hl">apps/server/app/gone.py</code></p>' >> "$REPO/docs/developer/good.html"
run_case "code tag with a class is scanned" 1 "apps/server/app/gone.py" -- --strict --root "$REPO"

# ── every path of a multi-line block counts, not just the first ──────────────
REPO="$WORK/r8"; fixture "$REPO"
printf '<pre><code>apps/server/real/file1.py\napps/server/app/gone_a.py\nscripts/gone_b.sh</code></pre>\n' \
  >> "$REPO/docs/developer/good.html"
run_case "multi-line block: later path found" 1 "scripts/gone_b.sh" -- --strict --root "$REPO"

# ── no docs/ at all is a setup error ─────────────────────────────────────────
run_case "missing docs/ -> exit 2" 2 "no docs/" -- --strict --root "$WORK"

echo "doc_smoke_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
