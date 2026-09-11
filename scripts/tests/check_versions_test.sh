#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# check_versions_test.sh — hermetic test for scripts/release/check-versions.sh.
#
# Builds a fixture tree carrying all six version sites (--root points the script
# at it), then breaks exactly one site per case. No docker, no network, no
# toolchain: bash + coreutils. The script is a RELEASE GATE — it must be red for
# the right reason and green for no other, and "it printed something" is not
# that. Every case therefore asserts the exit code AND the offending name.
#
# Run: bash scripts/tests/check_versions_test.sh

set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
CHECK="$HERE/../release/check-versions.sh"

PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# fixture <dir> <version> <footer-count> — a tree where every site carries <version>.
fixture() {
  local d="$1" v="$2" n="$3" i
  mkdir -p "$d/apps/desktop/src-tauri" "$d/docs/en" "$d/docs/admin" "$d/docs/en/admin"
  printf '{\n  "productName": "adminhelper",\n  "version": "%s"\n}\n' "$v" \
    > "$d/apps/desktop/src-tauri/tauri.conf.json"
  printf '[package]\nname = "adminhelper"\nversion = "%s"\nedition = "2021"\n\n[dependencies]\nserde = { version = "1.0.0" }\n' "$v" \
    > "$d/apps/desktop/src-tauri/Cargo.toml"
  printf '[[package]]\nname = "serde"\nversion = "1.0.0"\n\n[[package]]\nname = "adminhelper"\nversion = "%s"\ndependencies = [\n "serde",\n]\n' "$v" \
    > "$d/apps/desktop/src-tauri/Cargo.lock"
  printf '# Changelog\n\n## [Unreleased]\n\n## [%s] - 2026-01-01\n\n### Added\n- something\n' "$v" \
    > "$d/CHANGELOG.md"
  printf '<html><h2>Was ist neu in %s?</h2><div class="sidebar-footer"><span>v%s</span></div></html>\n' "$v" "$v" \
    > "$d/docs/index.html"
  # Double quotes so the apostrophe of "What's" survives — the real landing page
  # carries a literal one, and an HTML entity here would make the fixture green
  # for a check the real docs would fail.
  printf '<html><h2>%s</h2><div class="sidebar-footer"><span>v%s</span></div></html>\n' \
    "What's new in $v?" "$v" > "$d/docs/en/index.html"
  # The two landing pages already carry a footer; top up to <n> in total.
  # page2 gets the MULTI-LINE markup the real landing pages use — the variant a
  # one-line pattern silently skipped for three releases.
  printf '<html>\n  <div class="sidebar-footer">\n    <span>v%s</span>\n    <span id="year"></span>\n  </div>\n</html>\n' "$v" \
    > "$d/docs/admin/page2.html"
  i=3
  while [ "$i" -lt "$n" ]; do
    printf '<html><div class="sidebar-footer"><span>v%s</span><span id="year"></span></div></html>\n' "$v" \
      > "$d/docs/admin/page$i.html"
    i=$((i + 1))
  done
}

# run_case <name> <expect-rc> <expect-substring> -- <check-versions args...>
run_case() {
  local name="$1" want_rc="$2" want="$3"; shift 3; [ "$1" = "--" ] && shift
  local out rc=0
  out=$(bash "$CHECK" "$@" 2>&1) || rc=$?
  if [ "$rc" != "$want_rc" ]; then
    bad "$name: rc=$rc (expected $want_rc)"; printf '%s\n' "$out" | sed 's/^/       /'; return
  fi
  if [ -n "$want" ] && ! printf '%s' "$out" | grep -qF "$want"; then
    bad "$name: output does not mention '$want'"; printf '%s\n' "$out" | sed 's/^/       /'; return
  fi
  ok "$name"
}

# ── 1: every site correct ────────────────────────────────────────────────────
GOOD="$WORK/good"; fixture "$GOOD" 1.2.3 38
run_case "all six sites at 1.2.3 -> exit 0" 0 "6 ok, 0 missing" -- 1.2.3 --root "$GOOD"
# The same tree against another version must be red at all six — otherwise a
# green above would only prove the script prints "ok" unconditionally.
run_case "same tree, version 1.2.4 -> six missing" 1 "0 ok, 6 missing" -- 1.2.4 --root "$GOOD"

# ── 2: one stale footer, named ───────────────────────────────────────────────
STALE="$WORK/stale"; fixture "$STALE" 1.2.3 38
printf '<html><div class="sidebar-footer"><span>v1.2.2</span></div></html>\n' > "$STALE/docs/admin/page7.html"
run_case "one stale footer -> exit 1" 1 "docs/admin/page7.html" -- 1.2.3 --root "$STALE"
run_case "one stale footer -> the other five stay ok" 1 "5 ok, 1 missing" -- 1.2.3 --root "$STALE"

# ── 2b: a stale MULTI-LINE footer ────────────────────────────────────────────
# The real regression: docs/index.html and docs/en/index.html write the footer
# across two lines and hung at v0.43.2 through two releases while the check
# reported "36 files at v0.45.0".
MULTI="$WORK/multiline"; fixture "$MULTI" 1.2.3 38
printf '<html>\n  <div class="sidebar-footer">\n    <span>v1.2.2</span>\n  </div>\n</html>\n' \
  > "$MULTI/docs/admin/page9.html"
run_case "stale multi-line footer -> exit 1" 1 "docs/admin/page9.html" -- 1.2.3 --root "$MULTI"

# ── 3: CHANGELOG section missing ─────────────────────────────────────────────
NOCL="$WORK/nochangelog"; fixture "$NOCL" 1.2.3 38
printf '# Changelog\n\n## [Unreleased]\n\n## [1.2.2] - 2025-12-01\n' > "$NOCL/CHANGELOG.md"
run_case "CHANGELOG section missing -> exit 1" 1 "no section '## [1.2.3]'" -- 1.2.3 --root "$NOCL"

# ── 4: too few footers (a page that LOST its footer) ─────────────────────────
FEW="$WORK/few"; fixture "$FEW" 1.2.3 10
run_case "only 10 footer files -> below the floor" 1 "only 10 of >= 38" -- 1.2.3 --root "$FEW"

# ── 5: argument handling ─────────────────────────────────────────────────────
run_case "no version -> usage, exit 2" 2 "usage:" --
run_case "unknown flag -> exit 2" 2 "unknown flag" -- 1.2.3 --nope
# Tags are written vX.Y.Z; the sites carry X.Y.Z. Both spellings must work.
run_case "a leading v is accepted" 0 "6 ok, 0 missing" -- v1.2.3 --root "$GOOD"
# '.' in the version must not be a regex wildcard. Checked in the direction that
# actually discriminates: a tree literally carrying "1X2X3" must NOT satisfy a
# check for "1.2.3" (without the escaping it does).
WILD="$WORK/wildcard"; fixture "$WILD" 1.2.3 38
printf '# Changelog\n\n## [1X2X3] - 2026-01-01\n' > "$WILD/CHANGELOG.md"
run_case "a literal 1X2X3 does not satisfy 1.2.3" 1 "no section '## [1.2.3]'" -- 1.2.3 --root "$WILD"

echo ""
echo "check_versions_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
