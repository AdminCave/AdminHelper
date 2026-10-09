#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# builder_home_test.sh — hermetic test for scripts/dev/builder-home.sh.
#
# The fixture is a main checkout (builder-home.sh, runner-settings.json and the CLI
# pin copied in, a .devenv.sh with a placeholder database URL) whose origin is a
# bare repository, a fixture HOME with a git identity, and fakes on PATH for the
# claude CLI, psql and createdb. The tools venv is a real one without pip and a
# fake pip in it: the python3 wrapper is checked against a real interpreter.
# Nothing here reaches the network or a database.
#
# Run: bash scripts/tests/builder_home_test.sh
# ok()/bad() never fail; `cond && ok || bad` assertions are deliberate.
# shellcheck disable=SC2015
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../.." && pwd)
PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }
for t in git python3 sha256sum; do
  command -v "$t" >/dev/null 2>&1 || { echo "SKIP: $t not available"; exit 75; }
done
python3 -m venv --help >/dev/null 2>&1 || { echo "SKIP: python3 has no venv module"; exit 75; }
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
export HOME="$WORK/home"; mkdir -p "$HOME"
# Else git config --global would write an XDG or named config of the caller's.
unset XDG_CONFIG_HOME GIT_CONFIG_GLOBAL
git config --global user.name "Fixture Kevin"
git config --global user.email kevin@example.invalid
PW_RAW='s3cr@t-placeholder'   # what PGPASSWORD must carry
PW_URL='s3cr%40t-placeholder' # how the URL writes it
TOK_OK='sk-ant-oat01-placeholder'

# The main checkout, and the origin it was cloned from.
MAIN="$WORK/main"; ORIGIN="$WORK/origin.git"
mkdir -p "$MAIN/scripts/dev"
cp "$REPO_ROOT/scripts/dev/builder-home.sh" "$REPO_ROOT/scripts/dev/runner-settings.json" \
  "$REPO_ROOT/scripts/dev/runner-env.sh" "$MAIN/scripts/dev/"
printf '2.1.999\n' > "$MAIN/scripts/dev/runner-claude.version"
printf '.devenv.sh\n' > "$MAIN/.gitignore"
printf 'export AH_TEST_DB="postgresql+psycopg://ah:%s@localhost/adminhelper_test"\n' "$PW_URL" > "$MAIN/.devenv.sh"
git init -q -b main "$MAIN" && git -C "$MAIN" add -A && git -C "$MAIN" commit -qm base
git clone -q --bare "$MAIN" "$ORIGIN"
git -C "$MAIN" remote add origin "$ORIGIN" && git -C "$MAIN" fetch -q origin

# The fakes. claude installs itself as the pinned "binary", so the checksum is the
# fake's own; psql answers whether the database exists (it does once createdb
# ran); all of them record what they were given.
FB="$WORK/bin"; mkdir -p "$FB"; export FIXTURE_LOG="$WORK/fake.log"
cat > "$FB/claude" <<'FAKE'
#!/usr/bin/env bash
echo "claude $* HOME=$HOME" >> "$FIXTURE_LOG"
case "$1" in
  install) mkdir -p "$HOME/.local/share/claude/versions"; cp "$0" "$HOME/.local/share/claude/versions/$2" ;;
  setup-token) echo "open the browser, paste the code there" ;;
esac
FAKE
cat > "$FB/psql" <<'FAKE'
#!/usr/bin/env bash
echo "psql $* PGPASSWORD=${PGPASSWORD-<unset>}" >> "$FIXTURE_LOG"
[ -e "$FIXTURE_LOG.db" ] && echo 1
exit 0
FAKE
cat > "$FB/createdb" <<'FAKE'
#!/usr/bin/env bash
echo "createdb $* PGPASSWORD=${PGPASSWORD-<unset>}" >> "$FIXTURE_LOG"
: > "$FIXTURE_LOG.db"
FAKE
chmod +x "$FB"/*
export PATH="$FB:$PATH"
export AH_BUILDER_CLAUDE="$FB/claude"
sha256sum < "$FB/claude" | cut -d' ' -f1 > "$WORK/sum"
export AH_BUILDER_SUM="$WORK/sum"
unset AH_BUILDER_DIR

# The tools venv, made the way setup would but without pip, and a pip that only
# records and leaves the two console scripts behind.
mkvenv() {
  python3 -m venv --without-pip "$1" || return 1
  printf '#!/usr/bin/env bash\necho "pip $*" >> "$FIXTURE_LOG"\ntouch "%s/bin/ruff" "%s/bin/pytest"; chmod +x "%s/bin/ruff" "%s/bin/pytest"\n' \
    "$1" "$1" "$1" "$1" > "$1/bin/pip"
  chmod +x "$1/bin/pip"
}

BH="$MAIN/scripts/dev/builder-home.sh"
# A TMPDIR of its own: runner-env.sh makes its GH_CONFIG_DIR there.
TMPDIR_STATUS="$WORK/tmp"; mkdir -p "$TMPDIR_STATUS"
run() { : > "$FIXTURE_LOG"; OUT=$(cd "$MAIN" && TMPDIR="$TMPDIR_STATUS" bash "$BH" "$@" 2>&1); rc=$?; }
B="$HOME/.cache/ah-builder"; H="$B/home"; V="$H/.local/share/ah-tools/venv"
ALL_OUT=""

echo "── setup, the first time"
mkvenv "$V"
run setup; ALL_OUT+="$OUT"
[ $rc -eq 0 ] && ok "setup succeeds" || bad "setup: rc=$rc out=$OUT"
modes="$(stat -c %a "$B" "$B/loop" "$H" "$H/.claude" "$H/.config/adminhelper" | sort -u)"
[ "$modes" = 700 ] && [ "$(stat -c %a "$H/.devenv.sh" "$H/.claude/settings.json" | sort -u)" = 600 ] \
  && ok "directories 0700, .devenv.sh and settings.json 0600" || bad "modes: $modes / $(stat -c '%a %n' "$H/.devenv.sh" "$H/.claude/settings.json")"
[ "$(readlink "$H/.local/bin/claude")" = "$H/.local/share/claude/versions/2.1.999" ] \
  && grep -q "claude install 2.1.999 HOME=$H" "$FIXTURE_LOG" \
  && grep -q 'is the CLI runner-setup.sh recorded' <<<"$OUT" \
  && ok "the pinned CLI, installed into the builder HOME, matches the recorded checksum" || bad "cli: $OUT"
[ "$(git -C "$B/repo" config --get remote.origin.url)" = "$ORIGIN" ] \
  && [ "$(git -C "$B/repo" config --get remote.origin.pushurl)" = /dev/null ] \
  && [ "$(git -C "$B/repo" config --get core.hooksPath)" = scripts/dev/hooks ] \
  && [ "$(git -C "$B/repo" rev-parse HEAD)" = "$(git -C "$ORIGIN" rev-parse main)" ] \
  && ok "the clone: origin as the main checkout's, pushurl /dev/null, hooksPath, on origin/main" || bad "clone: $OUT"
[ "$(git config --file "$H/.gitconfig" user.email)" = kevin@example.invalid ] \
  && ok "the git identity is Kevin's, in the builder's .gitconfig" || bad "identity: $(git config --file "$H/.gitconfig" user.email)"
pgargs="$(sed 's/ PGPASSWORD=.*$//' "$FIXTURE_LOG")"
grep -q '^psql -X ' <<<"$pgargs" && ! grep -qF -e "$PW_RAW" -e "$PW_URL" <<<"$pgargs" \
  && ok "psql (without ~/.psqlrc) and createdb get no password in their arguments" || bad "pg args: $pgargs"

# The settings: the clone's runner-settings.json, moved and tightened.
python3 - "$H/.claude/settings.json" "$MAIN/scripts/dev/runner-settings.json" "$B" "$HOME" <<'PY' \
  && ok "settings: every rule of the runner, no //srv/ah left, lane rules on the builder, the hook" \
  || bad "settings do not carry the runner's rules onto the builder"
import json, sys
got, src = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
b = sys.argv[3]
deny, allow = got["permissions"]["deny"], got["permissions"]["allow"]
assert "//srv/ah" not in json.dumps(got), "a //srv/ah rule is left"
assert f"Edit(/{b}/**/scripts/dev/**)" in deny, "the lane rule is not on the builder"
moved = [r.replace("//srv/ah/", "/" + b + "/") for r in src["permissions"]["deny"]]
assert all(r in deny for r in moved), "a deny rule of the runner went missing"
assert allow == [r.replace("//srv/ah/", "/" + b + "/") for r in src["permissions"]["allow"]], "the allow list changed"
assert got["hooks"] == src["hooks"] and "harness-guard.sh" in json.dumps(got["hooks"]["PreToolUse"]), "the hook"
assert got["model"] == src["model"], "the model pin"
PY
python3 - "$H/.claude/settings.json" "$HOME" <<'PY' \
  && ok "settings: absolute denies for the real HOME, tasks/private, settings.local.json, ssh and docker" \
  || bad "a deny rule for the real HOME or the private files is missing or not absolute"
import json, sys
deny, home = json.load(open(sys.argv[1]))["permissions"]["deny"], sys.argv[2]
for p in (".ssh", ".config/gh", ".claude", ".config/adminhelper", ".local/share/keyrings", ".gnupg"):
    for tool in ("Read", "Edit"):
        assert f"{tool}(/{home}/{p}/**)" in deny, (tool, p)
for p in ("**/tasks/private/**", "**/.claude/settings.local.json"):
    for tool in ("Read", "Edit"):
        assert f"{tool}(//{p})" in deny, (tool, p)
for tool in ("Read", "Edit"):
    assert f"{tool}(/{home}/.claude.json)" in deny, (tool, ".claude.json")
assert "Bash(ssh:*)" in deny and "Bash(docker:*)" in deny
assert home.startswith("/")
PY

# The wrapper: through it, python3 is the venv's; a symlink there would not be.
[ -f "$H/.local/bin/python3" ] && [ ! -L "$H/.local/bin/python3" ] \
  && [ "$("$H/.local/bin/python3" -c 'import sys; print(sys.prefix)')" = "$V" ] \
  && ok "python3 in the builder HOME is a wrapper, and sys.prefix is the venv" \
  || bad "wrapper: $(ls -l "$H/.local/bin/python3") prefix=$("$H/.local/bin/python3" -c 'import sys; print(sys.prefix)' 2>&1)"
grep -q '^pip install --quiet ruff==0.15.20 pytest pytest-cov pytest-httpx' "$FIXTURE_LOG" \
  && [ "$(readlink "$H/.local/bin/ruff")" = "$V/bin/ruff" ] \
  && ok "ruff pinned as in runner-setup.sh, linked onto PATH" || bad "pip: $(grep pip "$FIXTURE_LOG")"
grep -q -- "^createdb --maintenance-db=postgresql://ah@localhost/adminhelper_test adminhelper_builder PGPASSWORD=$PW_RAW$" "$FIXTURE_LOG" \
  && ok "createdb on the main checkout's server, the password in PGPASSWORD and not in an argument" \
  || bad "createdb: $(grep createdb "$FIXTURE_LOG")"
grep -qxF "export AH_TEST_DB=\"postgresql+psycopg://ah:$PW_URL@localhost/adminhelper_builder\"" "$H/.devenv.sh" \
  && ok ".devenv.sh names the builder's own database" || bad "devenv AH_TEST_DB is not the builder database"
grep -q 'still missing: the token' <<<"$OUT" && ok "setup names the missing token" || bad "no token hint: $OUT"
[ ! -e "$H/.config/adminhelper/oauth.env" ] && ok "and writes no oauth.env itself" || bad "setup wrote oauth.env"

echo "── setup, the second time: nothing that is right changes"
snap() { (cd "$B" && find . -path ./repo/.git -prune -o \( -type f -o -type l \) -printf '%p %m %l\n' | sort
          find . -path ./repo/.git -prune -o -type f -exec sha256sum {} + | sort; git -C repo rev-parse HEAD); }
BEFORE="$(snap)"
run setup; ALL_OUT+="$OUT"
[ $rc -eq 0 ] && [ "$(snap)" = "$BEFORE" ] && ok "a second setup leaves every file, mode and link as it was" \
  || bad "second setup: rc=$rc diff: $(diff <(echo "$BEFORE") <(snap) | head -5)"
! grep -q '^  wrote' <<<"$OUT" && ! grep -q '^createdb' "$FIXTURE_LOG" && ! grep -q 'claude install' "$FIXTURE_LOG" \
  && ok "and writes nothing, creates no database, installs no CLI" || bad "second setup did work: $OUT"

echo "── token"
printf 'pastedcode#browserstate\n' > "$WORK/in.bad"
: > "$FIXTURE_LOG"; OUT=$(cd "$MAIN" && bash "$BH" token < "$WORK/in.bad" 2>&1); rc=$?; ALL_OUT+="$OUT"
[ $rc -ne 0 ] && grep -q 'not a token of the form sk-ant-oat01-' <<<"$OUT" && [ ! -e "$H/.config/adminhelper/oauth.env" ] \
  && ok "a value with # (the browser code) is refused, nothing written" || bad "bad token: rc=$rc out=$OUT"
grep -q "claude setup-token HOME=$H" "$FIXTURE_LOG" && ok "token runs claude setup-token in the builder HOME" \
  || bad "setup-token: $(cat "$FIXTURE_LOG")"
run status
[ $rc -ne 0 ] && grep -q '^missing: the token' <<<"$OUT" && ok "status: the token is missing -> exit 1" || bad "status without token: rc=$rc out=$OUT"
# status asks runner-env.sh, the reader the loop uses: a token there in a shape
# it refuses is missing too, and one it takes with export and quotes is there.
printf 'CLAUDE_CODE_OAUTH_TOKEN=pastedcode#x\n' > "$H/.config/adminhelper/oauth.env"; chmod 600 "$H/.config/adminhelper/oauth.env"
run status; ALL_OUT+="$OUT"
[ $rc -ne 0 ] && grep -q '^missing: the token, as runner-env.sh takes it' <<<"$OUT" \
  && ok "status: a token runner-env.sh refuses counts as missing" || bad "status, bad token: rc=$rc out=$OUT"
printf 'export CLAUDE_CODE_OAUTH_TOKEN="%s"\n' "$TOK_OK" > "$H/.config/adminhelper/oauth.env"
run status; ALL_OUT+="$OUT"
[ $rc -eq 0 ] && ok "status: export and quotes, as runner-env.sh reads them" || bad "status, export form: rc=$rc out=$OUT"
[ -z "$(ls -A "$TMPDIR_STATUS" 2>/dev/null)" ] && ok "and status leaves no GH_CONFIG_DIR behind" || bad "status left: $(ls -A "$TMPDIR_STATUS")"
rm -f "$H/.config/adminhelper/oauth.env"
printf '%s\n' "$TOK_OK" > "$WORK/in.ok"
OUT=$(cd "$MAIN" && bash "$BH" token < "$WORK/in.ok" 2>&1); rc=$?; ALL_OUT+="$OUT"
[ $rc -eq 0 ] && [ "$(cat "$H/.config/adminhelper/oauth.env")" = "CLAUDE_CODE_OAUTH_TOKEN=$TOK_OK" ] \
  && [ "$(stat -c %a "$H/.config/adminhelper/oauth.env")" = 600 ] \
  && ok "a token of the right form lands in oauth.env, 0600" || bad "good token: rc=$rc out=$OUT"
run status; ALL_OUT+="$OUT"
[ $rc -eq 0 ] && grep -q 'complete' <<<"$OUT" && ok "status: complete -> exit 0" || bad "status: rc=$rc out=$OUT"
# What runner-env.sh refuses for another reason, it says, and status shows it.
printf 'AH_PVE_URL=https://pve.invalid:8006\n' > "$H/.config/adminhelper/pve.env"; chmod 644 "$H/.config/adminhelper/pve.env"
run status; ALL_OUT+="$OUT"
[ $rc -ne 0 ] && grep -q 'pve.env is mode 644' <<<"$OUT" && ok "status shows runner-env.sh's reason (pve.env 0644)" \
  || bad "status, pve.env 0644: rc=$rc out=$OUT"
rm -f "$H/.config/adminhelper/pve.env"
! grep -qF -e "$TOK_OK" -e "$PW_RAW" -e "$PW_URL" -e pastedcode <<<"$ALL_OUT" \
  && ok "no output of setup, token or status carries the token or the password" || bad "a secret was printed"

echo "── the builder HOME of the first measuring run"
# As the run left it: python3 a symlink, a token, a clone with its own config,
# loop state. setup brings it up to date without taking any of it away.
B2="$WORK/ah-builder"; H2="$B2/home"
mkdir -p "$H2/.config/adminhelper" "$H2/.local/bin" "$B2/loop/messlauf-1"
mkvenv "$H2/.local/share/ah-tools/venv"
ln -s "$H2/.local/share/ah-tools/venv/bin/python3" "$H2/.local/bin/python3"
printf 'CLAUDE_CODE_OAUTH_TOKEN=%s\n' "$TOK_OK" > "$H2/.config/adminhelper/oauth.env"; chmod 600 "$H2/.config/adminhelper/oauth.env"
printf 'state\n' > "$B2/loop/messlauf-1/state.json"
git clone -q "$ORIGIN" "$B2/repo" && git -C "$B2/repo" config ah.fixture kept
TOKSUM="$(sha256sum < "$H2/.config/adminhelper/oauth.env")"
: > "$FIXTURE_LOG"; OUT=$(cd "$MAIN" && AH_BUILDER_DIR="$B2" bash "$BH" setup 2>&1); rc=$?; ALL_OUT+="$OUT"
[ $rc -eq 0 ] && [ "$(sha256sum < "$H2/.config/adminhelper/oauth.env")" = "$TOKSUM" ] \
  && [ "$(cat "$B2/loop/messlauf-1/state.json")" = state ] && [ "$(git -C "$B2/repo" config ah.fixture)" = kept ] \
  && ok "the token, the loop state and the clone stay" || bad "measuring-run home: rc=$rc out=$OUT"
[ ! -L "$H2/.local/bin/python3" ] && [ "$("$H2/.local/bin/python3" -c 'import sys; print(sys.prefix)')" = "$H2/.local/share/ah-tools/venv" ] \
  && ok "and its python3 symlink becomes the wrapper" || bad "python3 there: $(ls -l "$H2/.local/bin/python3")"

echo "── setup refuses a clone with changes"
printf 'local\n' > "$B2/repo/stray.txt"
OUT=$(cd "$MAIN" && AH_BUILDER_DIR="$B2" bash "$BH" setup 2>&1); rc=$?; ALL_OUT+="$OUT"
[ $rc -eq 1 ] && grep -q 'has changes' <<<"$OUT" && [ -e "$B2/repo/stray.txt" ] \
  && ok "a dirty clone -> exit 1, its changes left alone" || bad "dirty clone: rc=$rc out=$OUT"

echo "── the database URL"
# Any postgres scheme gives up its password to PGPASSWORD; a user:password the
# pattern cannot take apart stops setup before a database program runs.
B3="$WORK/ah-builder-3"; mkvenv "$B3/home/.local/share/ah-tools/venv"
cp "$MAIN/.devenv.sh" "$WORK/devenv.keep"
printf 'export AH_TEST_DB="postgres://ah:%s@localhost/adminhelper_test"\n' "$PW_URL" > "$MAIN/.devenv.sh"
: > "$FIXTURE_LOG"; OUT=$(cd "$MAIN" && AH_BUILDER_DIR="$B3" bash "$BH" setup 2>&1); rc=$?; ALL_OUT+="$OUT"
pgargs="$(sed 's/ PGPASSWORD=.*$//' "$FIXTURE_LOG")"
[ $rc -eq 0 ] && grep -q "^psql -X --dbname=postgresql://ah@localhost/adminhelper_test .*PGPASSWORD=$PW_RAW$" "$FIXTURE_LOG" \
  && ! grep -qF -e "$PW_RAW" -e "$PW_URL" <<<"$pgargs" && ok "postgres:// too: the password in PGPASSWORD, not in an argument" \
  || bad "postgres scheme: rc=$rc log=$pgargs"
printf 'export AH_TEST_DB="postgresql+psycopg://:%s@localhost/adminhelper_test"\n' "$PW_URL" > "$MAIN/.devenv.sh"
: > "$FIXTURE_LOG"; OUT=$(cd "$MAIN" && AH_BUILDER_DIR="$B3" bash "$BH" setup 2>&1); rc=$?; ALL_OUT+="$OUT"
[ $rc -eq 1 ] && grep -q 'password cannot be taken out' <<<"$OUT" && ! grep -qE '^(psql|createdb) ' "$FIXTURE_LOG" \
  && ok "a password it cannot take out of the URL stops setup, no database program runs" || bad "fail closed: rc=$rc out=$OUT log=$(cat "$FIXTURE_LOG")"
cp "$WORK/devenv.keep" "$MAIN/.devenv.sh"
# With an XDG git config of the caller's and no .gitconfig in a fresh builder HOME
# yet, git config --global would write the caller's file; the identity still goes
# to the builder.
B4="$WORK/ah-builder-4"; mkvenv "$B4/home/.local/share/ah-tools/venv"
mkdir -p "$WORK/xdg/git"; printf '[core]\n\teditor = vi\n' > "$WORK/xdg/git/config"; cp "$WORK/xdg/git/config" "$WORK/xdg.keep"
OUT=$(cd "$MAIN" && AH_BUILDER_DIR="$B4" XDG_CONFIG_HOME="$WORK/xdg" bash "$BH" setup 2>&1); rc=$?; ALL_OUT+="$OUT"
[ $rc -eq 0 ] && [ "$(git config --file "$B4/home/.gitconfig" user.email)" = kevin@example.invalid ] \
  && cmp -s "$WORK/xdg/git/config" "$WORK/xdg.keep" \
  && ok "an XDG git config of the caller's stays as it was, the identity is in the builder's .gitconfig" \
  || bad "xdg: rc=$rc $(cat "$WORK/xdg/git/config")"
OUT=$(cd "$MAIN" && AH_BUILDER_DIR=relative/dir bash "$BH" status 2>&1); rc=$?
[ $rc -eq 2 ] && grep -q 'must be an absolute path' <<<"$OUT" && ok "a relative AH_BUILDER_DIR -> 2" || bad "relative dir: rc=$rc out=$OUT"
! grep -qF -e "$TOK_OK" -e "$PW_RAW" -e "$PW_URL" -e pastedcode <<<"$ALL_OUT" \
  && ok "and none of these outputs carries the token or the password" || bad "a secret was printed later on"

run frob
[ $rc -eq 2 ] && ok "an unknown verb -> 2" || bad "usage: rc=$rc"

# ══ the real repo ═════════════════════════════════════════════════════════════
echo "── repo wiring ──"
sed -n '/^AH_SCRIPT_TESTS_DEFAULT=/,/"$/p' "$REPO_ROOT/scripts/tests/run.sh" | grep -qw 'builder_home_test' \
  && ok "builder_home_test is registered in AH_SCRIPT_TESTS_DEFAULT" || bad "not registered"
grep -qxF 'scripts/dev/builder-home.sh' "$REPO_ROOT/scripts/dev/harness-paths.txt" \
  && grep -qxF 'scripts/tests/builder_home_test.sh' "$REPO_ROOT/scripts/dev/harness-paths.txt" \
  && ok "builder-home.sh and its test are harness paths (they write the builder's rules)" || bad "missing from harness-paths.txt"
# token writes what status (through runner-env.sh) takes: one class in both files.
cls() { grep -o "sk-ant-oat01-\[[^]]*\]+" "$1" | sort -u; }
[ -n "$(cls "$REPO_ROOT/scripts/dev/runner-env.sh")" ] \
  && [ "$(cls "$REPO_ROOT/scripts/dev/builder-home.sh")" = "$(cls "$REPO_ROOT/scripts/dev/runner-env.sh")" ] \
  && ok "the token class of builder-home.sh is runner-env.sh's" || bad "token class drifted from runner-env.sh"
# The ruff pin is runner-setup.sh's: two users linting one repo with two ruffs disagree.
pin_rs="$(sed -n 's/^VENV_PKGS="\(ruff==[^ ]*\).*/\1/p' "$REPO_ROOT/scripts/dev/runner-setup.sh")"
[ -n "$pin_rs" ] && grep -qF "VENV_PKGS=($pin_rs " "$REPO_ROOT/scripts/dev/builder-home.sh" \
  && ok "the ruff pin is the one of runner-setup.sh ($pin_rs)" || bad "ruff pin drifted from runner-setup.sh"
if command -v shellcheck >/dev/null 2>&1; then
  shellcheck --severity=warning "$REPO_ROOT/scripts/dev/builder-home.sh" \
    && ok "shellcheck: builder-home.sh is clean" || bad "shellcheck findings in builder-home.sh"
fi

echo ""
echo "builder_home_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
