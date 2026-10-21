#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# openapi_breaking_test.sh — hermetic test for scripts/dev/openapi-breaking.sh.
#
# A fixture git repo under --root and a fake `oasdiff` in front of PATH: no
# network, no Go toolchain, bash + git + coreutils. The gate's whole value is its
# exit code, so every case asserts that code AND the wording that explains it;
# the fake records its invocation so a case can prove WHICH files were compared —
# "it exited 0" would hold just as well if the script had diffed a file against
# itself. The ERR exception file is the one part a fake cannot judge: those cases
# run the real oasdiff from PATH on fixture specs, and without it the test exits
# 75 (not verified).
#
# Run: bash scripts/tests/openapi_breaking_test.sh

set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
CHECK="$HERE/../dev/openapi-breaking.sh"

PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

command -v git >/dev/null 2>&1 || { echo "git not installed — skipping (75)"; exit 75; }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# A fake oasdiff that answers from the environment instead of doing real work:
#   FAKE_RC  the exit code it reports   FAKE_LOG  where it records its arguments
FAKE="$WORK/fakebin"; mkdir -p "$FAKE"
cat > "$FAKE/oasdiff" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE_LOG"
# Record the CONTENT of the first operand too. Asserting only on the argument
# list would still pass if the script diffed the working tree against itself —
# the exact mistake this test is supposed to rule out.
printf 'base-operand: %s\n' "$(tr -d '\n' < "$2" 2>/dev/null)" >> "$FAKE_LOG"
[ "${FAKE_RC:-0}" = 0 ] || { echo "fake: breaking changes found"; exit "$FAKE_RC"; }
echo "fake: no breaking changes"
EOF
chmod +x "$FAKE/oasdiff"
FAKE_LOG="$WORK/oasdiff.log"; : > "$FAKE_LOG"; export FAKE_LOG

REL="apps/server/tests/openapi.snapshot.json"
SNAP_BASE='{"openapi":"3.1.0","paths":{"/a":{}}}'
SNAP_HEAD='{"openapi":"3.1.0","paths":{"/a":{},"/b":{}}}'

# fixture <dir> <base-has-snapshot: yes|no>
# A git repo whose HEAD may or may not carry the snapshot, with a differing one
# in the working tree — the shape every real invocation sees.
fixture() {
  local d="$1" commit="$2"
  mkdir -p "$d/apps/server/tests"
  git -C "$d" init -q
  git -C "$d" config user.email t@example.com
  git -C "$d" config user.name Test
  if [ "$commit" = yes ]; then printf '%s\n' "$SNAP_BASE" > "$d/$REL"
  else printf 'placeholder\n' > "$d/README"; fi
  git -C "$d" add -A
  git -C "$d" commit -qm base
  printf '%s\n' "$SNAP_HEAD" > "$d/$REL"
}

# run_case <name> <expect-rc> <expect-substring> -- <args...>
# FAKE_RC and PATH come from the caller's environment.
run_case() {
  local name="$1" want_rc="$2" want="$3"; shift 3; [ "$1" = "--" ] && shift
  local out rc=0
  out=$(bash "$CHECK" "$@" 2>&1) || rc=$?
  if [ "$rc" != "$want_rc" ]; then
    bad "$name: rc=$rc (expected $want_rc)"; printf '%s\n' "$out" | sed 's/^/       /'; return
  fi
  if [ -n "$want" ] && ! grep -qF -- "$want" <<<"$out"; then
    bad "$name: output does not mention '$want'"; printf '%s\n' "$out" | sed 's/^/       /'; return
  fi
  ok "$name"
}

# The real binary, found before the fake shadows it: the exception file below is
# only as exact as oasdiff's own matcher, which no fake can stand in for.
REAL_OASDIFF=$(command -v oasdiff 2>/dev/null || true)
export PATH="$FAKE:$PATH"

# ── oasdiff reports a breaking change -> the gate is red and says so ─────────
REPO="$WORK/r1"; fixture "$REPO" yes
FAKE_RC=1 run_case "breaking oasdiff -> exit 1" 1 "::error::" -- server --base HEAD --root "$REPO"

# The comparison must be base-ref against working tree, not tree against tree.
LAST=$(grep -v '^base-operand:' "$FAKE_LOG" | tail -1)
case "$LAST" in
  *"--fail-on ERR"*"--format text"*) ok "oasdiff called with --fail-on ERR --format text" ;;
  *) bad "unexpected oasdiff arguments: $LAST" ;;
esac
case "$LAST" in
  *"--severity-levels"*oasdiff-severity.levels*) ok "the narrowing exception is handed to oasdiff" ;;
  *) bad "no --severity-levels in the call: $LAST" ;;
esac
case "$LAST" in
  *"--err-ignore"*oasdiff-err-ignore.txt*) ok "the named ERR exceptions are handed to oasdiff" ;;
  *) bad "no --err-ignore in the call: $LAST" ;;
esac
case "$LAST" in
  "breaking "*" $REL "*|"breaking "*" $REL") ok "second operand is the working-tree snapshot" ;;
  *) bad "working-tree snapshot is not the second operand: $LAST" ;;
esac
# And the FIRST operand really carries the base ref's content, not the working
# tree's. Without this the case above passes for `oasdiff breaking $REL $REL`.
if grep -qF "base-operand: $SNAP_BASE" "$FAKE_LOG"; then
  ok "first operand carries the base ref's snapshot"
else
  bad "first operand is not the base ref's snapshot: $(grep '^base-operand:' "$FAKE_LOG" | tail -1)"
fi

# ── oasdiff is happy -> green ────────────────────────────────────────────────
REPO="$WORK/r2"; fixture "$REPO" yes
FAKE_RC=0 run_case "compatible oasdiff -> exit 0" 0 "no breaking changes" -- server --base HEAD --root "$REPO"

# ── no oasdiff on PATH -> 75, never a silent pass ────────────────────────────
REPO="$WORK/r3"; fixture "$REPO" yes
EMPTY="$WORK/emptybin"; mkdir -p "$EMPTY"
OLD_PATH="$PATH"; PATH="$EMPTY:/usr/bin:/bin"
run_case "missing oasdiff -> exit 75 (SKIP)" 75 "not installed" -- server --base HEAD --root "$REPO"
PATH="$OLD_PATH"

# ── base ref carries no snapshot yet -> there is no contract to break ────────
REPO="$WORK/r4"; fixture "$REPO" no
FAKE_RC=1 run_case "absent base snapshot -> exit 0" 0 "nothing to compare" -- server --base HEAD --root "$REPO"

# ── a base snapshot that is not an OpenAPI document is a setup error ─────────
# oasdiff answers "no breaking changes" and exits 0 for an unparsable base, even
# when the revision removed a path — the gate would go green on a broken baseline.
REPO="$WORK/r4b"; fixture "$REPO" yes
git -C "$REPO" rm -q --cached "$REL" >/dev/null
printf 'not json at all\n' > "$REPO/$REL"
git -C "$REPO" add "$REL" && git -C "$REPO" commit -qm garbage
printf '%s\n' "$SNAP_HEAD" > "$REPO/$REL"
FAKE_RC=0 run_case "unparsable base snapshot -> exit 2" 2 "not an OpenAPI document" -- server --base HEAD --root "$REPO"

# ── usage errors ─────────────────────────────────────────────────────────────
REPO="$WORK/r5"; fixture "$REPO" yes
run_case "missing component -> exit 2" 2 "needs a component" -- --root "$REPO"
run_case "unknown component -> exit 2" 2 "unknown component" -- gateway --root "$REPO"
run_case "--base without a ref -> exit 2" 2 "needs a ref" -- server --root "$REPO" --base

# A base ref that is not in the checkout must NOT read as "nothing to compare":
# a shallow CI clone would otherwise turn the gate green on every PR.
REPO="$WORK/r7"; fixture "$REPO" yes
run_case "unresolvable base ref -> exit 2" 2 "does not resolve" -- server --base origin/nope --root "$REPO"

# A working tree without a snapshot is a setup error, not a skip: exiting 75 here
# would let a deleted snapshot pass the gate as "not verified" rather than red.
REPO="$WORK/r6"; fixture "$REPO" yes; rm -f "$REPO/$REL"
run_case "missing working-tree snapshot -> exit 2" 2 "--update-openapi-snapshot" -- server --base HEAD --root "$REPO"

# ── without the exception file the gate stays strict ─────────────────────────
# The script reads its two files from its own directory, so a copy next to the
# levels file alone is the checkout that lost oasdiff-err-ignore.txt.
NOIGN="$WORK/noignore"; mkdir -p "$NOIGN"
cp "$CHECK" "$HERE/../dev/oasdiff-severity.levels" "$NOIGN/"
REPO="$WORK/r8"; fixture "$REPO" yes
CHECK_SAVED="$CHECK"; CHECK="$NOIGN/openapi-breaking.sh"
FAKE_RC=0 run_case "missing exception file -> a note, no silent pass" 0 "oasdiff-err-ignore.txt is missing" -- server --base HEAD --root "$REPO"
CHECK="$CHECK_SAVED"
LAST=$(grep -v '^base-operand:' "$FAKE_LOG" | tail -1)
case "$LAST" in
  *"--err-ignore"*) bad "--err-ignore passed without the file: $LAST" ;;
  *"--severity-levels"*) ok "without the file: no --err-ignore, the levels still apply" ;;
  *) bad "unexpected oasdiff arguments: $LAST" ;;
esac

# ── called by a relative path from another directory ─────────────────────────
# The script finds both files next to itself. Resolved only after its cd into
# --root, a relative $0 points nowhere: both files read as missing, and the
# gate reports the named exceptions and the two bound WARN as ERR.
REPO="$WORK/r9"; fixture "$REPO" yes
rc=0; out=$(cd "$HERE" && FAKE_RC=0 bash ../dev/openapi-breaking.sh server --base HEAD --root "$REPO" 2>&1) || rc=$?
LAST=$(grep -v '^base-operand:' "$FAKE_LOG" | tail -1)
if [ "$rc" = 0 ] && ! grep -qF "is missing" <<<"$out" \
   && [[ "$LAST" == *"--severity-levels /"*"--err-ignore /"* ]]; then
  ok "relative call from another directory: both files found, by absolute path"
else
  bad "relative call from another directory: rc=$rc, oasdiff got: $LAST"; printf '%s\n' "$out" | sed 's/^/       /'
fi

# ── the severity file itself ─────────────────────────────────
# oasdiff rejects the whole file over one bad line, and it does so at gate time —
# on a box without oasdiff nobody would notice until CI. Its parser takes exactly
# two whitespace-separated fields per line and allows neither comments nor blank
# lines (checker/level.go:42 @v1.32.0), so the format is checked here.
LEVELS="$HERE/../dev/oasdiff-severity.levels"
if [ -r "$LEVELS" ]; then
  awk 'NF!=2 { bad=1; print "  line " NR ": " $0 } END { exit bad?1:0 }' "$LEVELS" >/dev/null \
    && ok "every line has exactly two fields" || bad "a line is not two fields — oasdiff would refuse the file"
  [ -z "$(awk '$2 != "warn"' "$LEVELS")" ] \
    && ok "every rule is lowered to warn, none to none/info" || bad "a rule is set to something other than warn"
  [ "$(cut -d' ' -f1 "$LEVELS" | sort | uniq -d | wc -l)" -eq 0 ] \
    && ok "no rule id appears twice" || bad "a rule id appears twice"
  # The list is deliberately closed: only "a bound was added" is lowered, so a rule
  # that creeps in here later has to be argued for in the ledger, not just added.
  EXPECTED="request-body-exclusive-max-set request-body-exclusive-min-set request-body-max-set request-body-min-set request-parameter-exclusive-max-set request-parameter-exclusive-min-set request-parameter-max-set request-parameter-min-set request-property-exclusive-max-set request-property-exclusive-min-set request-property-max-set request-property-min-set"
  [ "$(cut -d' ' -f1 "$LEVELS" | sort | tr '\n' ' ')" = "$EXPECTED " ] \
    && ok "exactly the twelve narrowing rules, nothing else" \
    || bad "the rule list drifted: $(cut -d' ' -f1 "$LEVELS" | sort | tr '\n' ' ')"
else
  bad "scripts/dev/oasdiff-severity.levels is missing"
fi

# ── the exception file itself ────────────────────────────────────────────────
# oasdiff matches the WHOLE line, reason included: a finding is dropped when the
# line contains its text (strings.Contains), and the path it compares exactly is
# the line's first field starting with "/" (checker/ignore.go,
# api_change.go:131 @v1.32.0). So this holds two things. The file, byte for byte,
# is the list below — date, roadmap id, reason and finding text of all seventeen
# lines (Kevin 2026-10-17, 2026-10-21); a further exception is Kevin's call and
# changes the list. And every line, the next one too, has the form <date> <R-id>
# <reason>: <METHOD> <path> <text>, its reason only letters, digits, blanks and
# hyphens: no backtick and no quote, so no finding text can hide in it, and no
# slash, so the path stays the field after the method. The rules:
# docs/developer/cicd.html.
IGNORE="$HERE/../dev/oasdiff-err-ignore.txt"
if [ -r "$IGNORE" ]; then
  # LC_ALL=C: under de_DE a bracket range like [0-9] matches more than ASCII digits.
  BAD_LINES=$(LC_ALL=C grep -nvE '^[0-9]{4}-[0-9]{2}-[0-9]{2} R-[0-9]{4} [A-Za-z0-9 -]+: (GET|PUT|POST|PATCH|DELETE) /[^ ]+ [^ ].*$' "$IGNORE")
  [ -z "$BAD_LINES" ] && ok "every line is <date> <R-id> <reason>: <METHOD> <path> <oasdiff text>, the reason plain" \
    || bad "lines off the format: $BAD_LINES"
  [ -z "$(sort "$IGNORE" | uniq -d)" ] && ok "no line appears twice" || bad "a line appears twice"
  EXPECTED_IGNORE=$(cat <<'EXPECTED_EXCEPTIONS'
2026-10-17 R-0411 tighter port bounds: POST /api/frp/server-config the `bind_port` request property's max was decreased to `65535.00`
2026-10-17 R-0411 tighter port bounds: POST /api/frp/server-config the `bind_port` request property's min was increased to `1.00`
2026-10-17 R-0411 tighter port bounds: POST /api/frp/server-config the `dashboard_port/anyOf[subschema #1]/` request property's max was decreased to `65535.00`
2026-10-17 R-0411 tighter port bounds: POST /api/frp/server-config the `dashboard_port/anyOf[subschema #1]/` request property's min was increased to `1.00`
2026-10-17 R-0411 tighter port bounds: POST /api/frp/server-config the `vhost_https_port/anyOf[subschema #1]/` request property's max was decreased to `65535.00`
2026-10-17 R-0411 tighter port bounds: POST /api/frp/server-config the `vhost_https_port/anyOf[subschema #1]/` request property's min was increased to `1.00`
2026-10-17 R-0411 tighter port bounds: POST /api/frp/server-config the `max_ports_per_client/anyOf[subschema #1]/` request property's min was increased to `0.00`
2026-10-17 R-0411 tighter port bounds: PUT /api/frp/server-config/{config_id} request property `bind_port` list-of-types was narrowed by removing types `null` from media type `application/json`
2026-10-17 R-0411 tighter port bounds: PUT /api/frp/server-config/{config_id} the `dashboard_port/anyOf[subschema #1]/` request property's max was decreased to `65535.00`
2026-10-17 R-0411 tighter port bounds: PUT /api/frp/server-config/{config_id} the `dashboard_port/anyOf[subschema #1]/` request property's min was increased to `1.00`
2026-10-17 R-0411 tighter port bounds: PUT /api/frp/server-config/{config_id} the `vhost_https_port/anyOf[subschema #1]/` request property's max was decreased to `65535.00`
2026-10-17 R-0411 tighter port bounds: PUT /api/frp/server-config/{config_id} the `vhost_https_port/anyOf[subschema #1]/` request property's min was increased to `1.00`
2026-10-17 R-0411 tighter port bounds: PUT /api/frp/server-config/{config_id} the `max_ports_per_client/anyOf[subschema #1]/` request property's min was increased to `0.00`
2026-10-21 R-0533 tighter visitor port bounds: POST /api/frp/tunnels the `visitor_port/anyOf[subschema #1]/` request property's max was decreased to `65535.00`
2026-10-21 R-0533 tighter visitor port bounds: POST /api/frp/tunnels the `visitor_port/anyOf[subschema #1]/` request property's min was increased to `1.00`
2026-10-21 R-0533 tighter visitor port bounds: PUT /api/frp/tunnels/{tunnel_id} the `visitor_port/anyOf[subschema #1]/` request property's max was decreased to `65535.00`
2026-10-21 R-0533 tighter visitor port bounds: PUT /api/frp/tunnels/{tunnel_id} the `visitor_port/anyOf[subschema #1]/` request property's min was increased to `1.00`
EXPECTED_EXCEPTIONS
)
  # diff against the file itself, not a $(…) copy of it: that would drop
  # trailing blank lines, and the comparison must see every byte. Its exit code
  # decides, not an empty output: a diff that could not run prints nothing too.
  DRIFT_RC=0; DRIFT=$(diff <(printf '%s\n' "$EXPECTED_IGNORE") "$IGNORE" 2>&1) || DRIFT_RC=$?
  [ "$DRIFT_RC" = 0 ] && ok "the file is exactly the seventeen expected lines, reasons included" \
    || bad "the exception file drifted from the expected lines (diff rc=$DRIFT_RC): $DRIFT"
  # oasdiff checks no path for a component or a security change: a line with the
  # word "components" or "security" could match one of those by its text alone.
  WORDS=$(grep -niE 'components|security' "$IGNORE")
  [ -z "$WORDS" ] && ok "no line names components or security" || bad "a line names components or security: $WORDS"
else
  bad "scripts/dev/oasdiff-err-ignore.txt is missing"
fi

# ── the exceptions against the real oasdiff ──────────────────────────────────
# A line drops an ERR finding when its first "/" field equals the finding's path,
# it contains "<method> <path>", and it contains the finding's whole text, value
# included — all case-insensitive (checker/api_change.go:131 @v1.32.0). The base
# carries the FRP request bodies with the INTEGER bounds IntColumn published, the
# head the narrowed ones, as in the server snapshot: the same seventeen texts.
# Base and head also carry one more port field and one more endpoint, so a case
# can narrow those too.
int_schema() { printf '{"type":"integer","minimum":%s,"maximum":%s}' "$1" "$2"; }
or_null()    { printf '{"anyOf":[%s,{"type":"null"}]}' "$1"; }
# props <name> <schema> [<name> <schema> ...] — the members of a properties object
props() { local sep=""; while [ $# -gt 1 ]; do printf '%s"%s":%s' "$sep" "$1" "$2"; sep=","; shift 2; done; }
body()  { printf '{"requestBody":{"content":{"application/json":{"schema":{"type":"object","properties":{%s}}}}},"responses":{"200":{"description":"ok"}}}' "$1"; }
# frp_spec <post-props> <put-props> <other-endpoint-props> <tunnel-props>
# /api/frp/server is a prefix of /api/frp/server-config: "post /api/frp/server"
# is a substring of every POST line, so only the exact path rule keeps it out.
# The tunnel props go to POST /api/frp/tunnels and PUT /api/frp/tunnels/{tunnel_id}
# alike: both bodies carry the same visitor_port schema in the server snapshot.
frp_spec() {
  printf '{"openapi":"3.1.0","info":{"title":"t","version":"1"},"paths":{'
  printf '"/api/frp/server-config":{"post":%s},' "$(body "$1")"
  printf '"/api/frp/server-config/{config_id}":{"parameters":[{"name":"config_id","in":"path","required":true,"schema":{"type":"string"}}],"put":%s},' "$(body "$2")"
  printf '"/api/frp/server":{"post":%s},' "$(body "$3")"
  printf '"/api/frp/tunnels":{"post":%s},' "$(body "$4")"
  printf '"/api/frp/tunnels/{tunnel_id}":{"parameters":[{"name":"tunnel_id","in":"path","required":true,"schema":{"type":"string"}}],"put":%s}}}\n' "$(body "$4")"
}
WIDE=$(int_schema -2147483648 2147483647)
PORT=$(int_schema 1 65535)
COUNT=$(int_schema 0 2147483647)
BASE_PROPS=$(props bind_port "$WIDE" vhost_http_port "$(or_null "$WIDE")" vhost_https_port "$(or_null "$WIDE")" \
  dashboard_port "$(or_null "$WIDE")" max_ports_per_client "$(or_null "$WIDE")")
BASE_PUT=$(props bind_port "$(or_null "$WIDE")" vhost_http_port "$(or_null "$WIDE")" vhost_https_port "$(or_null "$WIDE")" \
  dashboard_port "$(or_null "$WIDE")" max_ports_per_client "$(or_null "$WIDE")")
OTHER_WIDE=$(props bind_port "$WIDE")
# head_props <bind_port schema> <vhost_http_port schema>
head_props() {
  props bind_port "$1" vhost_http_port "$2" vhost_https_port "$(or_null "$PORT")" \
    dashboard_port "$(or_null "$PORT")" max_ports_per_client "$(or_null "$COUNT")"
}
TUNNEL_WIDE=$(props visitor_port "$(or_null "$WIDE")")
TUNNEL_PORT=$(props visitor_port "$(or_null "$PORT")")
FRP_BASE=$(frp_spec "$BASE_PROPS" "$BASE_PUT" "$OTHER_WIDE" "$TUNNEL_WIDE")
FRP_HEAD=$(frp_spec "$(head_props "$PORT" "$(or_null "$WIDE")")" "$(head_props "$PORT" "$(or_null "$WIDE")")" "$OTHER_WIDE" "$TUNNEL_PORT")

# frp_fixture <dir> <head-spec> — fixture() with the FRP base and this head
# (bash locals are visible to the functions this one calls)
frp_fixture() { local SNAP_BASE="$FRP_BASE" SNAP_HEAD="$2"; fixture "$1" yes; }

# The ERR findings of a gate run, one per line: "in API <METHOD> <path> | <text>".
errs_of() {
  awk '/^error\t/ { n = 2; next }
       n == 2 { api = $0; n = 1; next }
       n == 1 { sub(/^\t+/, "", api); sub(/^\t+/, ""); print api " | " $0; n = 0 }' <<<"$1"
}

# real_case <name> <expect-rc> <expect-errors> <every-error-mentions> -- <script> <args...>
# RUN_DIR (optional) is the directory the script is started from.
real_case() {
  local name="$1" want_rc="$2" want_n="$3" want="$4"; shift 4; [ "$1" = "--" ] && shift
  local out rc=0 errs n stray
  out=$(cd "${RUN_DIR:-.}" && PATH="$REALBIN:$PATH" bash "$@" 2>&1) || rc=$?
  errs=$(errs_of "$out"); n=$(grep -c . <<<"$errs")
  stray=$(grep -vF -- "$want" <<<"$errs")
  if [ "$rc" != "$want_rc" ] || [ "$n" != "$want_n" ] || [ -n "$stray" ]; then
    bad "$name: rc=$rc errors=$n (expected rc=$want_rc errors=$want_n, each naming '$want')"
    printf '%s\n' "$out" | sed 's/^/       /'; return
  fi
  ok "$name"
}

REAL_SKIPPED=0
if [ -n "$REAL_OASDIFF" ]; then
  REALBIN="$WORK/realbin"; mkdir -p "$REALBIN"; ln -s "$REAL_OASDIFF" "$REALBIN/oasdiff"
  echo "  (real $("$REAL_OASDIFF" --version 2>&1 | head -1))"

  REPO="$WORK/f1"; frp_fixture "$REPO" "$FRP_HEAD"
  real_case "no exception file: all seventeen are ERR" 1 17 "/api/frp/" \
    -- "$NOIGN/openapi-breaking.sh" server --base HEAD --root "$REPO"
  real_case "with the file: the seventeen pass" 0 0 "" \
    -- "$CHECK" server --base HEAD --root "$REPO"
  # The same by a relative path from another directory: none, not nineteen.
  RUN_DIR="$HERE" real_case "relative call from another directory: the seventeen pass" 0 0 "" \
    -- ../dev/openapi-breaking.sh server --base HEAD --root "$REPO"

  # Same endpoint, another port field, the very same bounds: the field name binds.
  REPO="$WORK/f2"
  frp_fixture "$REPO" "$(frp_spec "$(head_props "$PORT" "$(or_null "$PORT")")" "$(head_props "$PORT" "$(or_null "$WIDE")")" "$OTHER_WIDE" "$TUNNEL_PORT")"
  real_case "another field at POST /api/frp/server-config stays ERR" 1 2 "in API POST /api/frp/server-config | the \`vhost_http_port/anyOf[subschema #1]/\`" \
    -- "$CHECK" server --base HEAD --root "$REPO"

  # Another endpoint, the same field and bounds, so the very same text.
  REPO="$WORK/f3"
  frp_fixture "$REPO" "$(frp_spec "$(head_props "$PORT" "$(or_null "$WIDE")")" "$(head_props "$PORT" "$(or_null "$WIDE")")" "$(props bind_port "$PORT")" "$TUNNEL_PORT")"
  real_case "the same change at another endpoint stays ERR" 1 2 "in API POST /api/frp/server | the \`bind_port\`" \
    -- "$CHECK" server --base HEAD --root "$REPO"

  # The same field, narrowed further: the value is part of the text.
  REPO="$WORK/f4"
  frp_fixture "$REPO" "$(frp_spec "$(head_props "$(int_schema 1 1024)" "$(or_null "$WIDE")")" "$(head_props "$PORT" "$(or_null "$WIDE")")" "$OTHER_WIDE" "$TUNNEL_PORT")"
  real_case "a tighter bound on the same field stays ERR" 1 1 "the \`bind_port\` request property's max was decreased to \`1024.00\`" \
    -- "$CHECK" server --base HEAD --root "$REPO"

  # visitor_port with the minimum 0, not 1: the two min findings stay ERR, at
  # both tunnel endpoints; the max to 65535 is still the named one.
  REPO="$WORK/f5"
  frp_fixture "$REPO" "$(frp_spec "$(head_props "$PORT" "$(or_null "$WIDE")")" "$(head_props "$PORT" "$(or_null "$WIDE")")" "$OTHER_WIDE" "$(props visitor_port "$(or_null "$(int_schema 0 65535)")")")"
  real_case "visitor_port with the minimum 0 stays ERR" 1 2 "the \`visitor_port/anyOf[subschema #1]/\` request property's min was increased to \`0.00\`" \
    -- "$CHECK" server --base HEAD --root "$REPO"
else
  echo "  SKIP: oasdiff not installed — the exceptions are not checked against its matcher"
  REAL_SKIPPED=1
fi

echo "openapi_breaking_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
# Not run against the real matcher is not verified.
[ "$REAL_SKIPPED" = 0 ] || exit 75
