#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# ledger_loop_test.sh — hermetic test for scripts/dev/ledger-loop.sh (stage 7a).
#
# A throwaway world: a bare origin, a seed repo that pushes main and the plan
# branches, and a clone of it as the runner's clone, with the real ledger-loop.sh,
# lane.sh, ledger.sh, runner-env.sh and harness list in it. Fakes stand in for what
# would cost or reach out: verify.sh (its exit code per component), claude (version
# and auth status), and a HOME with the token file. No real CLI, no network.
#
# Run: bash scripts/tests/ledger_loop_test.sh
# ok()/bad() never fail; `cond && ok || bad` assertions are deliberate.
# shellcheck disable=SC2015
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../.." && pwd)
PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
# A red case names how the last loop run ended too: a loop that stopped before it
# wrote state.json leaves result() and stopped() with the run before (R-0200).
bad() {
  echo "  FAIL $*"; FAIL=$((FAIL + 1))
  [ -z "${OUT+x}" ] || printf '       last loop: rc=%s, its output ends:\n%s\n' "${rc-?}" "$(tail -n 8 <<<"$OUT" | sed 's/^/       | /')"
}
command -v git >/dev/null 2>&1 || { echo "SKIP: git not available"; exit 75; }
command -v python3 >/dev/null 2>&1 || { echo "SKIP: python3 not available"; exit 75; }
command -v flock >/dev/null 2>&1 || { echo "SKIP: flock not available"; exit 75; }
# The suite runs this file from inside run.sh, which exports these for its own run.
unset AH_OUT_DIR AH_ARGS AH_ONLY AH_STRICT AH_REQUIRED AH_DEVENV AH_AUTONOMOUS CLAUDE_PROJECT_DIR
# And a loop's own overrides: an inherited AH_LOOP_REPO pointed every case at the real
# clone (R-0231); each case sets what it needs.
unset "${!AH_LOOP_@}"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
export TMPDIR="$WORK/tmp"; mkdir -p "$TMPDIR"
export GIT_CONFIG_NOSYSTEM=1 GIT_AUTHOR_NAME=Fixture GIT_AUTHOR_EMAIL=fixture@example.invalid \
  GIT_COMMITTER_NAME=Fixture GIT_COMMITTER_EMAIL=fixture@example.invalid

ORIGIN="$WORK/origin.git" SEED="$WORK/seed" CLONE="$WORK/srv/repo" LOOPD="$WORK/loop"
git init -q --bare -b main "$ORIGIN"
mkdir -p "$SEED/scripts/dev" "$SEED/scripts/vm" "$SEED/tasks" "$SEED/apps/x" "$SEED/docs"
for f in ledger-loop.sh lane.sh ledger.sh review.sh harness-paths.txt runner-env.sh runner-claude.version; do
  cp "$REPO_ROOT/scripts/dev/$f" "$SEED/scripts/dev/$f"
done
cp "$REPO_ROOT/scripts/vm/lib.sh" "$SEED/scripts/vm/lib.sh"
# The loop hands every build session the /build-task text of its clone.
mkdir -p "$SEED/.claude/skills/build-task"
cp "$REPO_ROOT/.claude/skills/build-task/SKILL.md" "$SEED/.claude/skills/build-task/SKILL.md"
# The fake suite: records its call, fails for a component FIXTURE_RED names, exits 2
# for one FIXTURE_UNKNOWN names, and with FIXTURE_DO writes into the lane it got
# (junk: an untracked file; body: a line into the ledger) — what a suite run could do.
cat > "$SEED/scripts/dev/verify.sh" <<'FAKE'
#!/usr/bin/env bash
echo "$*" >> "${FIXTURE_VLOG:?}"
tree=""; prev=""
for a in "$@"; do
  [ "$prev" = --tree ] && tree="$a"; prev="$a"
  [ "$a" = "${FIXTURE_RED:-none}" ] && exit 1
  [ "$a" = "${FIXTURE_UNKNOWN:-none}" ] && exit 2
done
# With FIXTURE_ENVLOG it records the NAMES of its environment, never a value.
[ -z "${FIXTURE_ENVLOG:-}" ] || compgen -e >> "$FIXTURE_ENVLOG.verify"
case "${FIXTURE_DO:-}" in
  junk) : > "$tree/junk.txt" ;;
  body) printf 'Änderung: from the suite\n' >> "$tree/tasks/${tree##*/AdminHelper-}.md" ;;
esac
exit 0
FAKE
# The fake close (the loop runs the lane's task-close.sh): it records its call and
# answers with the next exit code of FIXTURE_CSEQ (default 0). 0 commits the task's
# code with the ledger ticked, as the real one does; 3 leaves a verdict of the round.
cat > "$SEED/scripts/dev/task-close.sh" <<'FAKE'
#!/usr/bin/env bash
ledger="$1" id="$2"; shift 2
round="" msgf=""
while [ $# -gt 0 ]; do
  case "$1" in --round) round="$2"; shift ;; --message-file) msgf="$2"; shift ;; esac
  shift
done
echo "$ledger $id round=$round" >> "${FIXTURE_CLOG:?}"
[ -z "${FIXTURE_ENVLOG:-}" ] || compgen -e >> "$FIXTURE_ENVLOG.close"
rc=0
if [ -s "${FIXTURE_CSEQ:-}" ]; then rc="$(head -n 1 "$FIXTURE_CSEQ")"; sed -i 1d "$FIXTURE_CSEQ"; fi
slug="$(basename "$ledger" .md)"
# With FIXTURE_RCOST a reviewed round prints its cost as the real one does, after a
# line of the same shape from the suite (the last one counts).
rcost() { [ -z "${FIXTURE_RCOST:-}" ] || printf 'review cost_usd=0 round=%s\nreview cost_usd=%s round=%s\n' "$round" "$FIXTURE_RCOST" "$round"; }
case "$rc" in
  0|74a)
    files="$(awk -v id="$id" '$0 ~ "^###[ \t]+" id "([ \t]|$)" { t = 1; next } t && /^###/ { exit }
      t && /Dateien:/ { sub(/.*Dateien:[ \t]*/, ""); gsub(/,/, " "); print; exit }' "$ledger")"
    # shellcheck disable=SC2086
    git add -A -- $files || exit 74
    if [ "$rc" = 74a ]; then
      mkdir -p ".ah-out/review/$slug"; printf '{"verdict": "approve"}\n' > ".ah-out/review/$slug/$id.r$round.verdict.json"
      echo "task-close: git commit failed"; exit 74
    fi
    rcost
    bash scripts/dev/ledger.sh mark-done "$ledger" "$id" --evidence "stub run" > /dev/null || exit 74
    grep -q '^###.*\[ \]' "$ledger" || bash scripts/dev/ledger.sh status "$ledger" bereit > /dev/null
    git add -- "$ledger" && git commit -qm "$(cat "$msgf")" || exit 74 ;;
  3n) echo "task-close: verify-red (exit 1)"; exit 3 ;;
  3c) git commit -q --allow-empty -m "sneaked in by the suite"; echo "task-close: verify-red (exit 1)"; exit 3 ;;
  3)
    mkdir -p ".ah-out/review/$slug"
    printf '{"verdict": "request_changes", "findings": [{"severity": "blocker", "file": "apps/x/a.py", "claim": "stub blocker round %s"}]}\n' \
      "$round" > ".ah-out/review/$slug/$id.r$round.verdict.json"
    rcost; echo "task-close: round $round gave no usable approve"; exit 3 ;;
  4) echo "task-close: blocked — the diff leaves the task's scope"; exit 4 ;;
  74r) echo "task-close: the reviewer gave no usable verdict (review-run.sh exit 74)"; exit 74 ;;
  4x)
    # The real one refuses at the sec check after mark-done: [x] and the ledger staged.
    bash scripts/dev/ledger.sh mark-done "$ledger" "$id" --evidence "stub run" > /dev/null || exit 74
    git add -A -- apps "$ledger"; echo "task-close: blocked — review.sh sec found a secret"; exit 4 ;;
  *) echo "task-close: stub exit $rc"; exit "$rc" ;;
esac
FAKE
printf '.ah-out/\n.vm/\n' > "$SEED/.gitignore"
printf 'a = 1\n' > "$SEED/apps/x/a.py"
printf 'base\n' > "$SEED/apps/c.txt"
printf '# docs\n' > "$SEED/docs/x.md"
git -C "$SEED" init -q -b main && git -C "$SEED" add -A && git -C "$SEED" commit -qm base
git -C "$SEED" remote add origin "$ORIGIN" && git -C "$SEED" push -q origin main

# plan <branch> <slug> <head lines…> — a plan branch with one ledger, one open task.
plan() {
  local branch="$1" slug="$2"; shift 2
  git -C "$SEED" switch -q -c "$branch" main
  mkdir -p "$SEED/tasks"   # main has no ledger: git keeps no empty directory
  {
    printf '# %s — Task-Ledger\n' "$slug"
    printf '%s\n' "$@"
    printf '\n### T1 — eine Aufgabe  [ ]\nKomponente: %s · Dateien: %s\nÄnderung: x\n' "${COMP:-scripts}" "${FILES:-apps/x/a.py}"
    printf 'Verify: bash scripts/dev/verify.sh %s --strict\n' "${COMP:-scripts}"
  } > "$SEED/tasks/$slug.md"
  [ -z "${EXTRA:-}" ] || eval "$EXTRA"
  git -C "$SEED" add -A && git -C "$SEED" commit -qm "chore(plan): $slug"
  git -C "$SEED" push -q origin "$branch"
  git -C "$SEED" switch -q main
}
OKHEAD=("Status: freigegeben · Branch: feature/%s · Review: auto" "Freigabe: Kevin, 2026-10-04" "Spec: docs/x.md")
head_for() { local s="$1"; printf "${OKHEAD[0]}\n" "$s"; printf '%s\n' "${OKHEAD[@]:1}"; }
mapfile -t H < <(head_for good);    plan feature/good good "${H[@]}"
mapfile -t H < <(head_for nofreig); plan feature/nofreig nofreig "${H[0]}" "${H[2]}"
plan harness/hx hx "Status: freigegeben · Branch: harness/hx" "Freigabe: Kevin"
mapfile -t H < <(head_for hpath);   FILES="apps/x/a.py, scripts/dev/ledger.sh" plan feature/hpath hpath "${H[@]}"
mapfile -t H < <(head_for red);     COMP=server plan feature/red red "${H[@]}"
mapfile -t H < <(head_for conflict)
EXTRA='printf "branch\n" > "$SEED/apps/c.txt"' plan feature/conflict conflict "${H[@]}"
for x in junk body cont; do mapfile -t H < <(head_for "$x"); plan "feature/$x" "$x" "${H[@]}"; done
mapfile -t H < <(head_for unk);     COMP=apps/server plan feature/unk unk "${H[@]}"
for x in ok4 fix4 q33 after33 sc4 sc4x inf skp arch harn err bud oerr hang ahl mlk mta mtb bda bdb kqa kqb kqc mh ibud lim cred hskip skp2 rca rcb ng1 ng2 ng3 ng4 dlim envp if1 if2 if3 hoa oth apie nojs rvc hob refm stl r1q lng sig orp stall stall3 stale red3 r74 r74a left tcommit tclone tcli tfail; do mapfile -t H < <(head_for "$x"); plan "feature/$x" "$x" "${H[@]}"; done
# Heavy as the planner writes it, and the open kind.
mapfile -t H < <(head_for hvy); plan feature/hvy hvy "${H[@]}" "Heavy: linux-full"
mapfile -t H < <(head_for hvn); plan feature/hvn hvn "${H[@]}" "Heavy: none — nur Skripte"
# A ledger whose second task already carries a question.
mapfile -t H < <(head_for qend)
EXTRA='printf "\n### T2 — offen  [?] (eine Frage)\nKomponente: scripts · Dateien: apps/x/b.py\nÄnderung: x\n" >> "$SEED/tasks/qend.md"' plan feature/qend qend "${H[@]}"
mapfile -t H < <(head_for qhb)
EXTRA='printf "\n### T2 — offen  [?] (eine Frage)\nKomponente: scripts · Dateien: apps/x/b.py\nÄnderung: x\n" >> "$SEED/tasks/qhb.md"' plan feature/qhb qhb "${H[@]}"
# A lane whose ignore pattern for .ah-out also matches a link (no trailing slash).
mapfile -t H < <(head_for ahl2)
EXTRA='printf ".ah-out\n.vm/\n" > "$SEED/.gitignore"' plan feature/ahl2 ahl2 "${H[@]}"
# A Freigabe: line in a task's text is no approval of the ledger.
mapfile -t H < <(head_for bodyfreig)
EXTRA='printf "Freigabe: im Text einer Task\n" >> "$SEED/tasks/bodyfreig.md"' plan feature/bodyfreig bodyfreig "${H[0]}" "${H[2]}"

git clone -q "$ORIGIN" "$CLONE"
# The runner's world: a HOME with its token file, a claude that answers version and auth.
FHOME="$WORK/home"; mkdir -p "$FHOME/.config/adminhelper" "$FHOME/.local/bin"
chmod 700 "$FHOME/.config/adminhelper"
printf 'CLAUDE_CODE_OAUTH_TOKEN=fixture-token\n' > "$FHOME/.config/adminhelper/oauth.env"
chmod 600 "$FHOME/.config/adminhelper/oauth.env"
# The runner's own hypervisor token, as runner-env.sh reads it (a fixture value).
printf 'AH_PVE_TOKEN_SECRET=fixture-pve\nAH_PVE_TOKEN_ID=fixture@pve!run\n' > "$FHOME/.config/adminhelper/pve.env"
chmod 600 "$FHOME/.config/adminhelper/pve.env"
# A build session (-p) does what the next line of FIXTURE_SEQ says (default skip), in
# the lane it runs in: build (a change and the commit message), harness (a change to
# a harness file too), skip, question, nothing, error (an error result, exit 1),
# budget and fail (other errors), files (widens Dateien:), hang (leaves work behind and
# sleeps past the task's time), filesn (a new Dateien: path each time), limit (the
# subscription's limit), credits (1M context needs credits), harnskip (a harness
# change and [~]), mlink (a scratch directory whose marker is a link), negcost and
# nancost (a cost below 0 or NaN), denylimit (the limit's text only in a denied command),
# othertask (changes the ledger's head), apierr (an API error), nojson (no JSON at all),
# refmove (a harness change and a ref origin/main that already holds it), linger (a
# child that outlives the loop with stdout and stderr closed, as git maintenance
# --detach does, then skip), wait (records its pid and sleeps: a session the loop dies
# under), orphan (leaves a sleeper with a session of its own behind, then skip).
export FIXTURE_PIN="$CLONE/scripts/dev/runner-claude.version" FIXTURE_CLONE="$CLONE"
cat > "$FHOME/.local/bin/claude" <<'FAKE'
#!/usr/bin/env bash
[ -z "${FIXTURE_CLILOG:-}" ] || echo "$1" >> "$FIXTURE_CLILOG"
[ -z "${FIXTURE_STDINLOG:-}" ] || echo "$1 $(readlink /proc/self/fd/0)" >> "$FIXTURE_STDINLOG"
case "$1" in
  --version) echo "${FIXTURE_CLAUDE_VERSION:-$(cat "$FIXTURE_PIN")} (Claude Code)"; exit 0 ;;
  auth) printf '{"loggedIn": true, "authMethod": "%s"}\n' "${FIXTURE_AUTH:-oauth_token}"; exit 0 ;;
  -p) ;;
  *) echo "stub: unknown call $*" >&2; exit 9 ;;
esac
[ -z "${FIXTURE_ENVLOG:-}" ] || compgen -e >> "$FIXTURE_ENVLOG.session"
# One line per session with its flags; the prompt (many lines) apart.
printf '%s\n' "${*:3}" >> "${FIXTURE_SLOG:?}"
printf '%s\n' "$2" >> "$FIXTURE_SLOG.prompts"
read -r ledger id rest < <(sed -n 's/^ARGUMENTS: //p' <<<"$2")
slug="$(basename "$ledger" .md)"
mode="${FIXTURE_SESSION:-skip}"
if [ -s "${FIXTURE_SEQ:-}" ]; then mode="$(head -n 1 "$FIXTURE_SEQ")"; sed -i 1d "$FIXTURE_SEQ"; fi
msg() { mkdir -p ".ah-out/loop/$slug" && printf 'feat(x): %s\n' "$id" > ".ah-out/loop/$slug/$id.commit-msg.txt"; }
case "$mode" in
  build) printf 'b = %s\n' "$RANDOM" >> apps/x/a.py; msg ;;
  extra) printf 'b = %s\n' "$RANDOM" >> apps/x/a.py; : > apps/x/new.py; msg ;;
  commit) printf 'c = 1\n' >> apps/x/a.py; git commit -qam "sneaked in"; bash scripts/dev/ledger.sh mark-skip "$ledger" "$id" "schon erledigt" > /dev/null ;;
  clone) printf '' > "$FIXTURE_CLONE/scripts/dev/harness-paths.txt"; printf 'b = 1\n' >> apps/x/a.py; msg ;;
  cli) printf 'b = 1\n' >> apps/x/a.py; msg; printf '# tampered\n' >> "$0" ;;
  harness) printf '# x\n' >> scripts/dev/ledger.sh; msg ;;
  skip) bash scripts/dev/ledger.sh mark-skip "$ledger" "$id" "schon erledigt" > /dev/null ;;
  question) bash scripts/dev/ledger.sh mark-question "$ledger" "$id" "welche Variante?" > /dev/null ;;
  nothing) ;;
  error) printf '{"type": "result", "subtype": "error_max_turns", "is_error": true, "total_cost_usd": 0.3, "num_turns": 80}\n'; exit 1 ;;
  budget) printf '{"type": "result", "subtype": "error_max_budget_usd", "is_error": true, "total_cost_usd": 12.1, "num_turns": 30}\n'; exit 1 ;;
  fail) printf '{"type": "result", "subtype": "error_during_execution", "is_error": true, "total_cost_usd": 0.1, "num_turns": 2}\n'; exit 1 ;;
  files) bash scripts/dev/ledger.sh set-files "$ledger" "$id" apps/x/w.py > /dev/null ;;
  hang)
    # Tracked and untracked work, a link out of the lane, a scratch directory and a
    # link in the scratch directory to a marked directory outside: then past the time.
    printf 'b = 1\n' >> apps/x/a.py; : > apps/x/new.py; ln -s "${FIXTURE_OUTSIDE:?}/keep.txt" apps/x/link
    mkdir -p .ah-out/scratch/s.1 && : > .ah-out/scratch/s.1/.ah-scratch; ln -s "$FIXTURE_OUTSIDE/marked" .ah-out/scratch/out
    exec sleep 30 ;;
  filesn) bash scripts/dev/ledger.sh set-files "$ledger" "$id" "apps/x/w$(date +%s%N).py" > /dev/null ;;
  limit)
    printf 'b = 1\n' >> apps/x/a.py; : > apps/x/new.py
    printf '{"type": "result", "subtype": "success", "is_error": true, "total_cost_usd": 0, "num_turns": 1, "result": "You\x27ve hit your session limit \xc2\xb7 resets 3:45pm"}\n'; exit 1 ;;
  credits)
    printf '{"type": "result", "subtype": "success", "is_error": true, "result": "API Error: Usage credits required for 1M context \xc2\xb7 run /usage-credits to turn them on"}\n'; exit 1 ;;
  harnskip) printf '# x\n' >> scripts/dev/ledger.sh; bash scripts/dev/ledger.sh mark-skip "$ledger" "$id" "schon erledigt" > /dev/null ;;
  negcost) printf 'b = 1\n' >> apps/x/a.py; msg; printf '{"type": "result", "subtype": "success", "is_error": false, "total_cost_usd": -100, "num_turns": 1}\n'; exit 0 ;;
  nancost) printf 'b = 1\n' >> apps/x/a.py; msg; printf '{"type": "result", "subtype": "success", "is_error": false, "total_cost_usd": NaN, "num_turns": 1}\n'; exit 0 ;;
  infcost) printf 'b = 1\n' >> apps/x/a.py; msg; printf '{"type": "result", "subtype": "success", "is_error": false, "total_cost_usd": Infinity, "num_turns": 1}\n'; exit 0 ;;
  denylimit)
    printf '{"type": "result", "subtype": "error_max_turns", "is_error": true, "permission_denials": [{"tool_name": "Bash", "tool_input": {"command": "echo You\x27ve hit your session limit \xc2\xb7 resets 9pm"}}]}\n'; exit 1 ;;
  othertask) bash scripts/dev/ledger.sh status "$ledger" erledigt > /dev/null; printf 'b = 1\n' >> apps/x/a.py; msg ;;
  apierr) printf 'b = 1\n' >> apps/x/a.py
    printf '{"type": "result", "subtype": "success", "is_error": true, "total_cost_usd": 0.1, "result": "API Error: 529 overloaded"}\n'; exit 1 ;;
  nojson) printf 'b = 1\n' >> apps/x/a.py; echo "not json"; exit 1 ;;
  refmove)
    printf '# x\n' >> scripts/dev/ledger.sh; msg
    git add -- scripts/dev/ledger.sh && c="$(git commit-tree "$(git write-tree)" -p HEAD -m moved)" \
      && git update-ref refs/remotes/origin/main "$c" && git reset -q ;;
  linger)
    # Without the session's mark, like the git maintenance a ledger commit of the loop
    # itself leaves behind: the loop does not end it, and its lock still must not stay.
    ( exec < /dev/null > /dev/null 2>&1; exec env -u AH_LOOP_SESSION sleep 30 ) & echo "$!" > "${FIXTURE_LINGER:?}"
    bash scripts/dev/ledger.sh mark-skip "$ledger" "$id" "schon erledigt" > /dev/null ;;
  wait) echo "$$" > "${FIXTURE_SPID:?}"; exec sleep 30 ;;
  orphan)
    setsid sleep 30 < /dev/null > /dev/null 2>&1 & echo "$!" > "${FIXTURE_ORPHAN:?}"
    bash scripts/dev/ledger.sh mark-skip "$ledger" "$id" "schon erledigt" > /dev/null ;;
  mlink)
    mkdir -p .ah-out/scratch/m.1 && ln -s "${FIXTURE_OUTSIDE:?}/keep.txt" .ah-out/scratch/m.1/.ah-scratch
    printf '{"type": "result", "subtype": "error_during_execution", "is_error": true}\n'; exit 1 ;;
  ahlink)
    # .ah-out itself swapped for a link to a directory with a marked scratch child.
    if [ -e .ah-out ]; then mv .ah-out .ah-out.old; fi; ln -s "${FIXTURE_OUTSIDE:?}/ah" .ah-out
    printf '{"type": "result", "subtype": "error_during_execution", "is_error": true}\n'; exit 1 ;;
esac
printf '{"type": "result", "subtype": "success", "is_error": false, "total_cost_usd": 0.25, "num_turns": 4, "result": "ok", "permission_denials": [{"tool_name": "Bash"}]}\n'
FAKE
chmod +x "$FHOME/.local/bin/claude"
# As runner-setup.sh writes it: the runner's CLI is on PATH only through this file.
printf 'export PATH="$HOME/.local/bin:$PATH"\n' > "$FHOME/.devenv.sh"
# The checksum runner-setup.sh records, root's in real life.
sha256sum < "$FHOME/.local/bin/claude" | cut -d' ' -f1 > "$WORK/claude.sha256"
export FIXTURE_VLOG="$WORK/vlog" FIXTURE_SLOG="$WORK/slog" FIXTURE_CLOG="$WORK/clog" FIXTURE_SEQ="$WORK/seq" FIXTURE_CSEQ="$WORK/cseq"
# seq <session modes> -- <close exit codes> — what the next run's sessions and closes do.
seq_set() {
  : > "$FIXTURE_SEQ"; : > "$FIXTURE_CSEQ"; : > "$FIXTURE_SLOG"; : > "$FIXTURE_SLOG.prompts"; : > "$FIXTURE_CLOG"
  local into="$FIXTURE_SEQ" x
  for x in "$@"; do
    [ "$x" = -- ] && { into="$FIXTURE_CSEQ"; continue; }
    printf '%s\n' "$x" >> "$into"
  done
}
loop() {  # loop <args…> — the loop from the clone, as the runner would start it
  : > "$FIXTURE_VLOG"
  # The PATH tmux hands a session started by sudo: no ~/.local/bin of the runner.
  OUT=$(cd "$CLONE" && env HOME="$FHOME" PATH=/usr/bin:/bin AH_LOOP_DIR="$LOOPD" AH_LOOP_CLAUDE_SUM="$WORK/claude.sha256" \
    bash scripts/dev/ledger-loop.sh "$@" 2>&1); rc=$?
}
result() {  # result <slug> — "<result> — <reason>" from state.json
  python3 -c 'import json, sys; l = json.load(open(sys.argv[1]))["ledgers"].get(sys.argv[2], {}); print(l.get("result", "-"), "—", l.get("reason", ""))' \
    "$LOOPD/state.json" "$1" 2>/dev/null
}
stopped() { python3 -c 'import json, sys; s = json.load(open(sys.argv[1])); print(s.get("stop"), "—", s.get("stop_reason", ""))' "$LOOPD/state.json" 2>/dev/null; }
lane() { printf '%s/srv/AdminHelper-%s' "$WORK" "$1"; }

echo "── usage ──"
loop
[ $rc -eq 2 ] && ok "no --ledger -> 2" || bad "no ledger: rc=$rc out=$OUT"
loop --ledger tasks/Bad_Name.md
[ $rc -eq 2 ] && ok "a ledger that is no tasks/<lane slug>.md -> 2" || bad "bad ledger: rc=$rc out=$OUT"
loop --ledger tasks/good.md --max-hours soon
[ $rc -eq 2 ] && ok "a cap that is no number -> 2" || bad "bad cap: rc=$rc out=$OUT"
for cap in --task-minutes --task-turns --task-budget; do
  loop --ledger tasks/good.md "$cap" 0
  [ $rc -eq 2 ] && grep -q "needs a number above 0" <<<"$OUT" && ok "$cap 0 -> 2: a task cap of 0 would be none" || bad "$cap 0: rc=$rc out=$OUT"
done

echo "── preflight: stop: infra, exit 74 ──"
mv "$FHOME/.config/adminhelper/oauth.env" "$WORK/oauth.bak"
loop --ledger tasks/good.md
[ $rc -eq 74 ] && grep -q '^infra — runner-env.sh did not load' <<<"$(stopped)" && [ ! -e "$(lane good)" ] \
  && ok "no token -> 74, no lane" || bad "no token: rc=$rc $(stopped) out=$OUT"
mv "$WORK/oauth.bak" "$FHOME/.config/adminhelper/oauth.env"
FIXTURE_CLAUDE_VERSION=9.9.9 loop --ledger tasks/good.md
[ $rc -eq 74 ] && grep -q 'claude --version is .9.9.9' <<<"$(stopped)" && ok "a claude off the pin -> 74" || bad "version: rc=$rc $(stopped)"
FIXTURE_AUTH=claude.ai loop --ledger tasks/good.md
[ $rc -eq 74 ] && grep -q "authMethod 'claude.ai'" <<<"$(stopped)" && ok "another login than oauth_token -> 74" || bad "auth: rc=$rc $(stopped)"
: > "$CLONE/stray.txt"
loop --ledger tasks/good.md
[ $rc -eq 74 ] && grep -q 'not clean' <<<"$(stopped)" && ok "a clone that is not clean -> 74" || bad "dirty clone: rc=$rc $(stopped)"
rm -f "$CLONE/stray.txt"
# The holder becomes the sleep itself (exec): killing it releases the lock at once.
mkdir -p "$LOOPD"; ( exec 9>"$LOOPD/loop.lock"; flock -n 9 && exec sleep 5 ) & HOLDER=$!
sleep 0.5
loop --ledger tasks/good.md
[ $rc -eq 74 ] && grep -q 'another ledger-loop' <<<"$OUT" && ok "a second loop while one holds the lock -> 74" || bad "lock: rc=$rc out=$OUT"
kill "$HOLDER" 2>/dev/null; wait "$HOLDER" 2>/dev/null
# A child of the run that outlives it holds fd 9 (git commit leaves git maintenance
# behind): the next run starts all the same (R-0200).
export FIXTURE_LINGER="$WORK/linger.pid"
seq_set linger
loop --ledger tasks/lng.md
LPID="$(cat "$FIXTURE_LINGER" 2>/dev/null)"
grep -q '^bereit' <<<"$(result lng)" && [ -n "$(find "/proc/$LPID/fd" -lname "$LOOPD/loop.lock" 2>/dev/null)" ] \
  && ok "the session's child still holds the loop's lock file after the run" || bad "lng: $(result lng) pid=$LPID"
loop --ledger tasks/lng.md
[ $rc -eq 0 ] && ! grep -q 'another ledger-loop' <<<"$OUT" && grep -q '^übersprungen — Status: bereit in the lane' <<<"$(result lng)" \
  && ok "a child that outlives a run keeps no lock: the next run starts" || bad "lng again: rc=$rc $(result lng)"
kill "$LPID" 2>/dev/null
# A loop killed by a signal (tmux kill-session) leaves its session running under
# timeout: that session keeps the lock, and the next run stops instead of building
# beside it in the same lane.
export FIXTURE_SPID="$WORK/session.pid"
seq_set wait
( cd "$CLONE" && exec env HOME="$FHOME" PATH=/usr/bin:/bin AH_LOOP_DIR="$LOOPD" AH_LOOP_CLAUDE_SUM="$WORK/claude.sha256" \
    bash scripts/dev/ledger-loop.sh --ledger tasks/sig.md > "$WORK/sig.out" 2>&1 ) & SIGLOOP=$!
for _ in $(seq 1 300); do [ -s "$FIXTURE_SPID" ] && break; sleep 0.1; done
SPID="$(cat "$FIXTURE_SPID" 2>/dev/null)"
kill -HUP "$SIGLOOP" 2>/dev/null; wait "$SIGLOOP" 2>/dev/null
loop --ledger tasks/sig.md
[ -n "$SPID" ] && kill -0 "$SPID" 2>/dev/null && [ $rc -eq 74 ] && grep -q 'another ledger-loop' <<<"$OUT" \
  && ok "a loop killed under a running session leaves it the lock: the next run stops" || bad "sig: rc=$rc session=${SPID:-none}"
kill "$SPID" 2>/dev/null
flock -w 30 "$LOOPD/loop.lock" true || bad "the session of sig still holds the lock 30 s after it was killed"
# R-0226: a process the session leaves behind with a session (and a process group) of
# its own outlives timeout's kill; the loop ends it before it goes on and names it.
# A process of the same user without the session's mark stays.
export FIXTURE_ORPHAN="$WORK/orphan.pid"
( cd "$CLONE" && exec sleep 30 ) & KEEP=$!
seq_set orphan
loop --ledger tasks/orp.md
OPID="$(cat "$FIXTURE_ORPHAN" 2>/dev/null)"
[ -n "$OPID" ] && ! kill -0 "$OPID" 2>/dev/null && grep -q "a process left behind, ended: $OPID " "$LOOPD/loop.log" \
  && ok "a process the session left with a session of its own is ended and named in the log" \
  || bad "orphan: pid=${OPID:-none} $(kill -0 "$OPID" 2>/dev/null && echo alive) $(tail -n 2 "$LOOPD/loop.log")"
kill -0 "$KEEP" 2>/dev/null && ok "a process of the same user without the session's mark stays" || bad "the unmarked process was ended"
kill "$OPID" "$KEEP" 2>/dev/null; wait "$KEEP" 2>/dev/null

echo "── per ledger ──"
FIXTURE_RED=server loop --ledger tasks/good.md --ledger tasks/nofreig.md --ledger tasks/hx.md --ledger tasks/hpath.md --ledger tasks/red.md
[ $rc -eq 0 ] && ok "a run over five ledgers ends with 0" || bad "five ledgers: rc=$rc out=$OUT"
L="$(lane good)"
[ "$(git -C "$L" symbolic-ref --short HEAD 2>/dev/null)" = feature/good ] \
  && [ "$(git -C "$L" log -3 --format=%s | tr '\n' '|')" = "chore(ledger): good bereit|chore(ledger): good T1 [~]|chore(ledger): good aktiv|" ] \
  && [ -z "$(git -C "$L" status --porcelain)" ] && grep -q '^bereit' <<<"$(result good)" \
  && ok "an approved ledger: lane, aktiv, its task [~] by the session, then bereit — each a ledger commit" \
  || bad "good: $(result good) $(git -C "$L" log --oneline -4 2>&1)"
grep -qx "scripts --tree $L --strict" "$FIXTURE_VLOG" && ok "the foundation: verify.sh of the open tasks' component against the lane" \
  || bad "foundation call: $(cat "$FIXTURE_VLOG")"
grep -q '^übersprungen — no Freigabe' <<<"$(result nofreig)" && [ ! -e "$(lane nofreig)" ] \
  && ok "a ledger without Freigabe: is skipped, no lane" || bad "nofreig: $(result nofreig)"
grep -q '^blockiert (harness)' <<<"$(result hx)" && [ ! -e "$(lane hx)" ] \
  && ok "a plan on a harness/ branch -> blockiert (harness), no lane" || bad "hx: $(result hx)"
grep -q '^blockiert (harness) — Dateien: names the harness path scripts/dev/ledger.sh' <<<"$(result hpath)" && [ ! -e "$(lane hpath)" ] \
  && ok "a harness path in Dateien: -> blockiert (harness), no lane" || bad "hpath: $(result hpath)"
grep -q '^blockiert (Fundament rot)' <<<"$(result red)" && ok "a red foundation -> blockiert (Fundament rot)" || bad "red: $(result red)"

N=$(git -C "$L" rev-list --count HEAD)
loop --ledger tasks/good.md
[ $rc -eq 0 ] && grep -q '^übersprungen — Status: bereit in the lane' <<<"$(result good)" && [ "$(git -C "$L" rev-list --count HEAD)" = "$N" ] \
  && ok "a clean lane is read again: a bereit ledger is not built twice" || bad "continue: rc=$rc $(result good)"
printf 'half done\n' > "$L/apps/x/new.py"
loop --ledger tasks/good.md
[ $rc -eq 0 ] && grep -q '^blockiert (Lane schmutzig)' <<<"$(result good)" && [ -z "$(git -C "$CLONE" stash list)" ] \
  && [ "$(cat "$L/apps/x/new.py")" = "half done" ] \
  && ok "a dirty lane -> blockiert (Lane schmutzig), nothing stashed, the file untouched" || bad "dirty lane: rc=$rc $(result good)"
rm -f "$L/apps/x/new.py"
# Continuing reads the lane's own ledger: what the loop set there (blockiert after
# D) never reached origin, where the head still says freigegeben.
FIXTURE_SESSION=nothing loop --ledger tasks/cont.md
LCO="$(lane cont)"
grep -q '^Status: blockiert' "$LCO/tasks/cont.md" || { sed -i 's/^Status: aktiv/Status: blockiert/' "$LCO/tasks/cont.md" && git -C "$LCO" commit -qam "chore(ledger): cont blockiert"; }
N=$(git -C "$LCO" rev-list --count HEAD)
loop --ledger tasks/cont.md
[ $rc -eq 0 ] && grep -q '^übersprungen — Status: blockiert in the lane' <<<"$(result cont)" && [ "$(git -C "$LCO" rev-list --count HEAD)" = "$N" ] \
  && ok "a lane whose ledger says blockiert is not set back to aktiv" || bad "blocked lane: rc=$rc $(result cont)"
loop --ledger tasks/bodyfreig.md
grep -q '^übersprungen — no Freigabe' <<<"$(result bodyfreig)" && ok "a Freigabe: in a task's text is no approval" || bad "body Freigabe: $(result bodyfreig)"
FIXTURE_UNKNOWN=apps/server loop --ledger tasks/unk.md
[ $rc -eq 0 ] && grep -q '^blockiert (Fundament) — verify.sh apps/server exit 2' <<<"$(result unk)" \
  && ok "a component verify.sh cannot run blocks that ledger, not the run" || bad "unknown component: rc=$rc $(result unk)"

echo "── the loop's ledger commit carries the ledger's head and markers only ──"
FIXTURE_DO=junk loop --ledger tasks/junk.md
[ $rc -eq 74 ] && grep -q 'would carry more than tasks/junk.md' <<<"$(stopped)" \
  && ok "a lane with another change -> no ledger commit, stop: infra" || bad "junk: rc=$rc $(stopped)"
FIXTURE_DO=body loop --ledger tasks/body.md
[ $rc -eq 74 ] && grep -q 'goes past head and markers' <<<"$(stopped)" \
  && ok "a ledger change beyond head and markers -> no ledger commit, stop: infra" || bad "body: rc=$rc $(stopped)"

echo "── the task iteration ──"
box() { sed -n 's/^### T1 .*\[\(.\)\].*/\1/p' "$(lane "$1")/tasks/$1.md"; }
subjects() { git -C "$(lane "$1")" log -"${2:-3}" --format=%s | tr '\n' '|'; }
cost() { python3 -c 'import json, sys; s = json.load(open(sys.argv[1])); t = s.get("tasks", {}).get(sys.argv[2], {}); print(t.get("sessions"), t.get("denials"), t.get("cost_usd"))' "$LOOPD/state.json" "$1"; }

seq_set build -- 0
loop --ledger tasks/ok4.md
L4="$(lane ok4)"
[ $rc -eq 0 ] && [ "$(box ok4)" = x ] && grep -q '^Status: bereit' "$L4/tasks/ok4.md" && [ "$(git -C "$L4" log -1 --format=%s)" = "feat(x): T1" ] \
  && git -C "$L4" show --name-only --format= HEAD | grep -qx apps/x/a.py && git -C "$L4" show --name-only --format= HEAD | grep -qx tasks/ok4.md \
  && grep -q '^bereit' <<<"$(result ok4)" && grep -qx 'tasks/ok4.md T1 round=1' "$FIXTURE_CLOG" \
  && ok "approve -> one commit with the code and the ticked ledger, the ledger bereit" || bad "ok4: rc=$rc $(result ok4) $(subjects ok4)"
grep -q -- '--setting-sources user --permission-mode dontAsk --permission-prompts none --max-turns 80 --max-budget-usd 12' "$FIXTURE_SLOG" \
  && grep -q '^ARGUMENTS: tasks/ok4.md T1$' "$FIXTURE_SLOG.prompts" && grep -q 'Du baust \*\*eine\*\* Task' "$FIXTURE_SLOG.prompts" \
  && ! grep -q -- '--bare' "$FIXTURE_SLOG" && ! grep -q '^name: build-task' "$FIXTURE_SLOG.prompts" \
  && ok "the session: the clone's /build-task text, only user settings, dontAsk, the task caps, never --bare" || bad "session call: $(head -c 400 "$FIXTURE_SLOG")"
[ "$(cost ok4/T1)" = "1 1 0.25" ] && ok "cost, sessions and denials of the task are in state.json" || bad "state per task: $(cost ok4/T1)"

seq_set build build -- 3 0
loop --ledger tasks/fix4.md
[ $rc -eq 0 ] && [ "$(box fix4)" = x ] && [ "$(grep -c . "$FIXTURE_SLOG")" = 2 ] && grep -q '^ARGUMENTS: tasks/fix4.md T1 --fix .ah-out/loop/fix4/T1.close.log .*T1.r1.verdict.json$' "$FIXTURE_SLOG.prompts" \
  && [ "$(tr '\n' '|' < "$FIXTURE_CLOG")" = "tasks/fix4.md T1 round=1|tasks/fix4.md T1 round=2|" ] \
  && ok "3 then 0 -> a second session with --fix, closed in round 2" || bad "fix4: rc=$rc $(result fix4) $(cat "$FIXTURE_CLOG")"

seq_set build build build -- 3 3 0
loop --ledger tasks/q33.md --ledger tasks/after33.md
LQ="$(lane q33)"
[ $rc -eq 0 ] && [ "$(box q33)" = "?" ] && grep -q '^Status: blockiert' "$LQ/tasks/q33.md" \
  && [ "$(git -C "$LQ" log -1 --format=%s)" = "chore(ledger): q33 T1 [?], blockiert" ] \
  && grep -q 'blocker in apps/x/a.py after round 2, the finding is in .*/q33/T1.r2.verdict.json' "$LQ/tasks/q33.md" \
  && ! grep -q 'stub blocker' <<<"$(git -C "$LQ" log -p -- tasks/q33.md)" && grep -q 'stub blocker round 2' "$LOOPD/q33/T1.r2.verdict.json" \
  && [ -z "$(git -C "$LQ" status --porcelain)" ] && [ "$(git -C "$LQ" show HEAD:apps/x/a.py)" = "a = 1" ] \
  && ok "3 and 3 -> [?] with the first blocker of round 2, blockiert, the code taken back" || bad "q33: $(result q33) $(git -C "$LQ" status --short)"
[ "$(box after33)" = x ] && grep -q '^bereit' <<<"$(result after33)" && ok "and the next ledger of the list runs" || bad "after33: $(result after33)"
[ -s "$LOOPD/q33/T1.aborted.diff" ] && grep -q '^+b = ' "$LOOPD/q33/T1.aborted.diff" \
  && ok "what was taken back is kept in aborted.diff" || bad "aborted.diff: $(ls "$LOOPD/q33")"

seq_set build -- 4
loop --ledger tasks/sc4.md
[ "$(box sc4)" = "?" ] && grep -q 'blocked by task-close (exit 4, scope or sec), see .*/sc4/T1.close' "$(lane sc4)/tasks/sc4.md" \
  && ! grep -q 'leaves the task' "$(lane sc4)/tasks/sc4.md" && grep -q '^blockiert' <<<"$(result sc4)" \
  && ok "4 -> [?] with task-close's reason, blockiert" || bad "sc4: $(result sc4)"

seq_set build -- 4x
loop --ledger tasks/sc4x.md
LX="$(lane sc4x)"
[ $rc -eq 0 ] && [ "$(box sc4x)" = "?" ] && grep -q '^blockiert' <<<"$(result sc4x)" && [ -z "$(git -C "$LX" status --porcelain)" ] \
  && [ "$(git -C "$LX" log -1 --format=%s)" = "chore(ledger): sc4x T1 [?], blockiert" ] && ! grep -q 'stub run' "$LX/tasks/sc4x.md" \
  && [ "$(git -C "$LX" show HEAD:apps/x/a.py)" = "a = 1" ] \
  && ok "4 after mark-done with the ledger staged -> [x] and its lines taken back, [?], blockiert, the lane clean" \
  || bad "sc4x: rc=$rc $(result sc4x) $(stopped) $(git -C "$LX" status --short)"

seq_set build build -- 74 74
loop --ledger tasks/inf.md
LI="$(lane inf)"
[ $rc -eq 74 ] && [ "$(box inf)" = " " ] && [ -z "$(git -C "$LI" status --porcelain)" ] && grep -q 'could not run twice' <<<"$(stopped)" \
  && [ "$(grep -c . "$FIXTURE_SLOG")" = 1 ] && [ "$(grep -c . "$FIXTURE_CLOG")" = 2 ] \
  && ok "74 and 74 -> the close alone retried, then stop: infra, the task left open, the lane clean" || bad "inf: rc=$rc $(stopped) $(git -C "$LI" status --short)"
# Continuing an aktiv lane: no second aktiv commit, the open task is built.
N=$(git -C "$LI" rev-list --count HEAD)
seq_set build -- 0
loop --ledger tasks/inf.md
[ $rc -eq 0 ] && [ "$(box inf)" = x ] && [ "$(git -C "$LI" rev-list --count HEAD)" = $((N + 1)) ] \
  && ok "an aktiv lane is continued: no second aktiv commit, its open task built" || bad "continue inf: rc=$rc $(subjects inf 3)"

seq_set skip
loop --ledger tasks/skp.md
[ "$(box skp)" = "~" ] && [ "$(subjects skp 2)" = "chore(ledger): skp bereit|chore(ledger): skp T1 [~]|" ] \
  && [ "$(git -C "$(lane skp)" show --name-only --format= HEAD~1)" = tasks/skp.md ] \
  && ok "[~] set by the session -> a commit of the ledger alone" || bad "skp: $(subjects skp 3)"

# R-0170: review files of an earlier run of the same task do not decide this one.
git -C "$CLONE" branch -q feature/arch origin/feature/arch && (cd "$CLONE" && bash scripts/dev/lane.sh new arch) > /dev/null 2>&1
LA="$(lane arch)"; mkdir -p "$LA/.ah-out/review/arch"
printf '{"verdict": "approve"}\n' > "$LA/.ah-out/review/arch/T1.r1.verdict.json"; : > "$LA/.ah-out/review/arch/T1.r1.staged"
printf '{"verdict": "request_changes"}\n' > "$LA/.ah-out/review/arch/T1.r2.verdict.json"
seq_set build -- 0
loop --ledger tasks/arch.md
OLDD="$(find "$LA/.ah-out/review/arch" -maxdepth 1 -name 'old-*' -type d | head -n 1)"
[ "$(box arch)" = x ] && grep -qx 'tasks/arch.md T1 round=1' "$FIXTURE_CLOG" && [ -n "$OLDD" ] && [ -f "$OLDD/T1.r1.verdict.json" ] \
  && [ -f "$OLDD/T1.r2.verdict.json" ] && [ ! -e "$LA/.ah-out/review/arch/T1.r1.verdict.json" ] \
  && ok "old review files of the task go aside, the task starts in round 1" || bad "arch: $(result arch) $(cat "$FIXTURE_CLOG") $(ls "$LA/.ah-out/review/arch")"

seq_set harness -- 0
loop --ledger tasks/harn.md
[ $rc -eq 74 ] && grep -q '^harness-modified — harn T1: the session changed the harness path scripts/dev/ledger.sh' <<<"$(stopped)" \
  && [ -z "$(git -C "$(lane harn)" status --porcelain)" ] && [ ! -s "$FIXTURE_CLOG" ] \
  && ok "a session that changes a harness path -> stop: harness-modified, no close, the lane clean" || bad "harn: rc=$rc $(stopped)"

seq_set error
loop --ledger tasks/err.md
[ "$(box err)" = "?" ] && grep -q '\[?\] (turns: the build session used up its 80 turns (rc 1, ' "$(lane err)/tasks/err.md" && grep -q '^blockiert' <<<"$(result err)" \
  && ok "error_max_turns -> [?] turns, blockiert" || bad "err: $(result err)"
seq_set budget
loop --ledger tasks/bud.md
[ "$(box bud)" = "?" ] && grep -q '\[?\] (budget: the build session used up its \$12 (rc 1, ' "$(lane bud)/tasks/bud.md" && grep -q '^blockiert' <<<"$(result bud)" \
  && ok "error_max_budget_usd -> [?] budget, blockiert" || bad "bud: $(result bud)"
seq_set fail
loop --ledger tasks/oerr.md
[ "$(box oerr)" = "?" ] && grep -q '\[?\] (error: the build session ended with error_during_execution (rc 1, ' "$(lane oerr)/tasks/oerr.md" \
  && ok "any other error -> [?] error with its kind" || bad "oerr: $(result oerr)"

# The task's time: in the test a fraction of a minute.
export FIXTURE_OUTSIDE="$WORK/outside"; mkdir -p "$FIXTURE_OUTSIDE/marked"
printf 'keep\n' > "$FIXTURE_OUTSIDE/keep.txt"; : > "$FIXTURE_OUTSIDE/marked/.ah-scratch"
seq_set hang
t0=$SECONDS
loop --ledger tasks/hang.md --task-minutes 0.02
LH="$(lane hang)"
[ $rc -eq 0 ] && [ $((SECONDS - t0)) -lt 25 ] && [ "$(box hang)" = "?" ] && grep -q '\[?\] (timeout: the build session ran past its 0.02 min (rc 124, ' "$LH/tasks/hang.md" \
  && grep -q '^blockiert' <<<"$(result hang)" && ok "a session past its time -> killed, [?] timeout, blockiert" || bad "hang: rc=$rc $(result hang) $(stopped)"
[ "$(cost hang/T1)" = "1 0 12.0" ] && ok "a session without JSON counts with its budget (12 \$), not 0" || bad "hang cost: $(cost hang/T1)"
[ -z "$(git -C "$LH" status --porcelain)" ] && [ ! -e "$LH/apps/x/new.py" ] && [ ! -L "$LH/apps/x/link" ] && [ ! -e "$LH/.ah-out/scratch/s.1" ] \
  && [ "$(git -C "$LH" show HEAD:apps/x/a.py)" = "a = 1" ] \
  && ok "the lane is clean: the change restored, the new file, the link and the scratch directory gone" || bad "hang lane: $(git -C "$LH" status --short) $(ls -A "$LH/.ah-out/scratch" 2>&1)"
grep -q '^+b = 1' "$LOOPD/hang/T1.aborted.diff" && grep -qx 'apps/x/new.py' "$LOOPD/hang/T1.aborted.diff" \
  && ok "aborted.diff keeps the change and names the new file" || bad "hang diff: $(cat "$LOOPD/hang/T1.aborted.diff" 2>&1)"
[ "$(cat "$FIXTURE_OUTSIDE/keep.txt")" = keep ] && [ -f "$FIXTURE_OUTSIDE/marked/.ah-scratch" ] \
  && ok "nothing outside the lane is touched: not through a link, not a marked directory linked into scratch" || bad "outside: $(ls -la "$FIXTURE_OUTSIDE" 2>&1)"
mkdir -p "$FIXTURE_OUTSIDE/ah/scratch/x.1"; : > "$FIXTURE_OUTSIDE/ah/scratch/x.1/.ah-scratch"
seq_set ahlink
loop --ledger tasks/ahl.md
[ "$(box ahl)" = "?" ] && [ -f "$FIXTURE_OUTSIDE/ah/scratch/x.1/.ah-scratch" ] && [ ! -L "$(lane ahl)/.ah-out" ] \
  && ok "a .ah-out swapped for a link out of the lane: the link goes, the marked directory behind it stays" || bad "ahl: $(result ahl) $(ls -la "$FIXTURE_OUTSIDE/ah/scratch" 2>&1)"
# Where the ignore pattern hides the link from git, only the check on .ah-out itself holds.
seq_set ahlink
loop --ledger tasks/ahl2.md
[ "$(box ahl2)" = "?" ] && [ -L "$(lane ahl2)/.ah-out" ] && [ -f "$FIXTURE_OUTSIDE/ah/scratch/x.1/.ah-scratch" ] \
  && ok "a linked .ah-out that git ignores: the scratch step does not follow it" || bad "ahl2: $(result ahl2) $(ls -la "$FIXTURE_OUTSIDE/ah/scratch" 2>&1)"
seq_set mlink
loop --ledger tasks/mlk.md
[ "$(box mlk)" = "?" ] && [ -d "$(lane mlk)/.ah-out/scratch/m.1" ] && [ "$(cat "$FIXTURE_OUTSIDE/keep.txt")" = keep ] \
  && ok "a scratch directory whose marker is a link is not one of scratch.sh's: it stays" || bad "mlk: $(result mlk) $(ls -la "$(lane mlk)/.ah-out/scratch" 2>&1)"

seq_set nothing nothing
loop --ledger tasks/stall.md
[ "$(box stall)" = "?" ] && grep -q 'stall: two iterations without progress, the ledger unchanged' "$(lane stall)/tasks/stall.md" && [ "$(grep -c . "$FIXTURE_SLOG")" = 2 ] \
  && ok "two sessions without progress -> [?] stall" || bad "stall: $(result stall)"
# The ledger decides: a session that only widened Dateien: changed it, the next two compare.
seq_set nothing files nothing
loop --ledger tasks/stall3.md
[ "$(box stall3)" = "?" ] && [ "$(grep -c . "$FIXTURE_SLOG")" = 3 ] && grep -q 'stall: ' "$(lane stall3)/tasks/stall3.md" \
  && ! grep -q 'apps/x/w.py' "$(lane stall3)/tasks/stall3.md" && [ -z "$(git -C "$(lane stall3)" status --porcelain)" ] \
  && ok "a ledger changed in between -> no stall yet; the stall after the third, the widened Dateien: taken back" || bad "stall3: $(result stall3) sessions=$(grep -c . "$FIXTURE_SLOG")"
# A message a close refused with 2 is not the next session's word.
seq_set build nothing -- 2
loop --ledger tasks/stale.md
[ "$(box stale)" = "?" ] && [ "$(grep -c . "$FIXTURE_CLOG")" = 1 ] && [ "$(grep -c . "$FIXTURE_SLOG")" = 2 ] && grep -q 'stall: ' "$(lane stale)/tasks/stale.md" \
  && ok "2, then a session without a message -> no second close, [?] stall" || bad "stale: $(result stale) closes=$(grep -c . "$FIXTURE_CLOG")"

seq_set build build -- 3n 0
loop --ledger tasks/red3.md
[ "$(box red3)" = x ] && [ "$(tr '\n' '|' < "$FIXTURE_CLOG")" = "tasks/red3.md T1 round=1|tasks/red3.md T1 round=1|" ] \
  && grep -q '^ARGUMENTS: tasks/red3.md T1 --fix .ah-out/loop/red3/T1.close.log$' "$FIXTURE_SLOG.prompts" \
  && [ -s "$(lane red3)/.ah-out/loop/red3/T1.close.log" ] && grep -q '^Read CLAUDE.md of this checkout first' "$FIXTURE_SLOG.prompts" \
  && ok "a 3 before the review (red suite) -> a --fix session, the round stays 1, closed" || bad "red3: $(result red3) $(cat "$FIXTURE_CLOG")"
seq_set build -- 74 0
loop --ledger tasks/r74.md
[ "$(box r74)" = x ] && [ "$(grep -c . "$FIXTURE_SLOG")" = 1 ] && [ "$(grep -c . "$FIXTURE_CLOG")" = 2 ] \
  && ok "74 then 0 -> the close alone is retried, no second session" || bad "r74: $(result r74) slog=$(grep -c . "$FIXTURE_SLOG")"
seq_set build -- 74a 0
loop --ledger tasks/r74a.md
LR="$(lane r74a)"
[ "$(box r74a)" = x ] && [ -n "$(find "$LR/.ah-out/review/r74a" -maxdepth 2 -path '*old-*' -name 'T1.r1.verdict.json')" ] \
  && ok "a 74 after the round's verdict -> that verdict goes aside, the retry reviews afresh" || bad "r74a: $(result r74a) $(ls -R "$LR/.ah-out/review/r74a" 2>&1 | head -5)"
seq_set extra -- 0
loop --ledger tasks/left.md
[ "$(box left)" = x ] && grep -q '^blockiert — T1 closed, but left files outside its Dateien:' <<<"$(result left)" \
  && [ ! -e "$(lane left)/apps/x/new.py" ] && [ -z "$(git -C "$(lane left)" status --porcelain)" ] \
  && ok "a close that leaves undeclared files behind -> they are taken back, the ledger blockiert" || bad "left: $(result left)"

echo "── sessions get only the environment they need ──"
EL="$WORK/envlog"; rm -f -- "${EL:?}".*
seq_set build -- 0
FIXTURE_ENVLOG="$EL" loop --ledger tasks/envp.md
[ $rc -eq 0 ] && [ "$(box envp)" = x ] && [ -s "$EL.session" ] && [ -s "$EL.close" ] && [ -s "$EL.verify" ] \
  && ! grep -q '^AH_PVE_' "$EL.session" "$EL.close" "$EL.verify" \
  && grep -qx 'CLAUDE_CODE_OAUTH_TOKEN' "$EL.session" && grep -qx 'CLAUDE_CODE_OAUTH_TOKEN' "$EL.close" \
  && ok "the build session, task-close and the foundation run without AH_PVE_*, with the subscription token" \
  || bad "envp: rc=$rc $(result envp) pve in: $(grep -l '^AH_PVE_' "$EL".* 2>/dev/null | tr '\n' ' ')"

echo "── the ledger's end: PR text and bundle ──"
seq_set build build -- 0 0
loop --ledger tasks/hvy.md --ledger tasks/hvn.md
LY="$(lane hvy)"
[ $rc -eq 0 ] && [ "$(box hvy)" = x ] && grep -qF -- '- [x] **T1 — eine Aufgabe**' "$LOOPD/hvy/pr-body.md" \
  && grep -qF -- '- **Heavy:** linux-full' "$LOOPD/hvy/pr-body.md" && grep -qxF '**Heavy offen — fährt die Aufsicht.**' "$LOOPD/hvy/pr-body.md" \
  && ok "bereit -> pr-body.md from review.sh pr-body, Heavy: linux-full with the note for the supervisor" || bad "hvy: rc=$rc $(result hvy) $(cat "$LOOPD/hvy/pr-body.md" 2>&1)"
[ -s "$LOOPD/hvn/pr-body.md" ] && ! grep -q 'Heavy offen' "$LOOPD/hvn/pr-body.md" \
  && ok "Heavy: none -> no note" || bad "hvn: $(cat "$LOOPD/hvn/pr-body.md" 2>&1)"
# Kevin's checkout: a clone of origin, and the branch from the bundle, nothing else.
KEV="$WORK/kevin"; git clone -q "$ORIGIN" "$KEV"
git -C "$KEV" fetch -q "$LOOPD/hvy.bundle" feature/hvy:feature/hvy 2>"$WORK/fetch.err"
[ "$(git -C "$KEV" rev-parse feature/hvy 2>/dev/null)" = "$(git -C "$LY" rev-parse HEAD)" ] \
  && [ "$(git -C "$KEV" log --format=%H origin/main..feature/hvy)" = "$(git -C "$LY" log --format=%H origin/main..HEAD)" ] \
  && grep -q '^bereit — PR text .*hvy/pr-body.md, branch in .*hvy.bundle$' <<<"$(result hvy)" \
  && ok "the bundle is verified, and a second repo fetches feature/hvy from it with the same commits" || bad "bundle: $(cat "$WORK/fetch.err") $(cat "$LOOPD/hvy/bundle.log" 2>&1)"
! grep -q '^- \*\*Heavy:' "$LOOPD/ok4/pr-body.md" && grep -qxF '**Heavy offen — fährt die Aufsicht.**' "$LOOPD/ok4/pr-body.md" \
  && ok "a ledger without a Heavy: line -> the note too" || bad "no Heavy line: $(cat "$LOOPD/ok4/pr-body.md" 2>&1)"
# bereit is committed before the handover: a bundle that cannot be written stops the
# run, and the next run makes the handover up instead of skipping the ledger.
mkdir -p "$LOOPD/hoa.bundle"
seq_set build -- 0
loop --ledger tasks/hoa.md
first=$rc; firststop="$(stopped)"
rmdir "$LOOPD/hoa.bundle"
seq_set
loop --ledger tasks/hoa.md
git -C "$KEV" fetch -q "$LOOPD/hoa.bundle" feature/hoa:feature/hoa 2>"$WORK/fetch.err"
[ "$first" -eq 74 ] && grep -q '^infra — git bundle of feature/hoa failed' <<<"$firststop" && [ $rc -eq 0 ] \
  && grep -q '^bereit — handover made up' <<<"$(result hoa)" && [ ! -s "$FIXTURE_SLOG" ] \
  && [ "$(git -C "$KEV" rev-parse feature/hoa 2>/dev/null)" = "$(git -C "$(lane hoa)" rev-parse HEAD)" ] \
  && ok "a handover that broke off after bereit is made up by the next run, no session" || bad "hoa: first=$first $firststop / rc=$rc $(result hoa) $(cat "$WORK/fetch.err")"

echo "── the run's caps and stop classes ──"
# summary_line — the last line of the newest summary.
summary_line() { local f; f="$(ls -t "$LOOPD"/summary-*.md 2>/dev/null | head -n 1)"; [ -n "$f" ] && tail -n 1 "$f"; }
rm -f -- "${LOOPD:?}"/summary-*.md
seq_set build -- 0
loop --ledger tasks/mta.md --ledger tasks/mtb.md --max-tasks 1
[ $rc -eq 0 ] && [ "$(box mta)" = x ] && [ ! -e "$(lane mtb)" ] && grep -q '^max-tasks — 1 tasks done' <<<"$(stopped)" \
  && [ "$(summary_line)" = 'ledger-loop: 1 tasks, 1 ready, 0 blocked, $0.25 total, stop: max-tasks' ] \
  && ok "--max-tasks 1 -> stop: max-tasks at the boundary, the next ledger untouched, the summary's last line" \
  || bad "max-tasks: rc=$rc $(stopped) | $(summary_line)"
# The cap is reached inside the first session; it ends the run only after the task.
seq_set build -- 0
loop --ledger tasks/bda.md --ledger tasks/bdb.md --max-budget-usd 0.2
[ $rc -eq 0 ] && [ "$(box bda)" = x ] && [ ! -e "$(lane bdb)" ] && grep -q '^max-budget — the run spent \$0.2500 of the run.s \$0.2' <<<"$(stopped)" \
  && ok "--max-budget-usd below one session's cost -> that session closes its task, then stop: max-budget" || bad "max-budget: rc=$rc $(stopped)"
seq_set build build -- 0 0
loop --ledger tasks/kqa.md --ledger tasks/kqb.md --ledger tasks/kqc.md --max-ready 2
[ $rc -eq 0 ] && [ "$(box kqa)" = x ] && [ "$(box kqb)" = x ] && [ ! -e "$(lane kqc)" ] && grep -q '^kevin-queue — 2 ledgers bereit' <<<"$(stopped)" \
  && ok "--max-ready 2 -> two ledgers bereit, stop: kevin-queue before the third" || bad "kevin-queue: rc=$rc $(stopped)"
# Two reviewed rounds at 0.5 $ and two sessions at 0.25 $: 1.5 $, over a cap of 1.4 $.
seq_set build build -- 3 0
FIXTURE_RCOST=0.5 loop --ledger tasks/rca.md --ledger tasks/rcb.md --max-budget-usd 1.4
[ $rc -eq 0 ] && [ "$(box rca)" = x ] && [ ! -e "$(lane rcb)" ] && grep -q '^max-budget — the run spent \$1.5000' <<<"$(stopped)" \
  && grep -q '^ledger-loop: 1 tasks, 1 ready, 0 blocked, \$1.50 total, stop: max-budget$' <<<"$(summary_line)" \
  && [ "$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["tasks"]["rca/T1"]["review_usd"])' "$LOOPD/state.json")" = 1.0 ] \
  && ok "two reviewer rounds count into the run's budget: 1.5 \$, stop: max-budget" || bad "rca: rc=$rc $(stopped) | $(summary_line)"
# A cost below 0 or NaN is no known cost: it counts with the session's cap.
seq_set negcost nancost -- 0 0
loop --ledger tasks/ng1.md --ledger tasks/ng2.md --ledger tasks/ng3.md --task-budget 1 --max-budget-usd 1.5 --max-ready 9
[ $rc -eq 0 ] && [ "$(box ng2)" = x ] && [ ! -e "$(lane ng3)" ] && grep -q '^max-budget — the run spent \$2.0000' <<<"$(stopped)" \
  && ok "a session cost below 0 or NaN counts with --task-budget, the cap holds" || bad "ng: rc=$rc $(stopped)"
# Whatever awk makes of them, state.json carries the cap instead.
seq_set infcost nancost negcost -- 0 0 0
loop --ledger tasks/if1.md --ledger tasks/if2.md --ledger tasks/if3.md --task-budget 1 --max-ready 9
python3 - "$LOOPD/state.json" <<'PY' && ok "Infinity, NaN and -100 count as the task budget in state.json, per task and in the sum" || bad "if: $(cat "$LOOPD/state.json")"
import json, math, sys
s = json.load(open(sys.argv[1]))
costs = [s["tasks"]["%s/T1" % k]["cost_usd"] for k in ("if1", "if2", "if3")]
sys.exit(0 if s["cost_usd"] == 3 and all(math.isfinite(c) and c == 1 for c in costs) else 1)
PY
# The limit's text in a command the session was denied is no limit of the run.
seq_set denylimit
loop --ledger tasks/dlim.md
[ $rc -eq 0 ] && [ "$(box dlim)" = "?" ] && grep -q '\[?\] (turns: ' "$(lane dlim)/tasks/dlim.md" && ! grep -q 'usage-limit' <<<"$(stopped)" \
  && ok "a limit text inside a denied command of the JSON -> [?] turns, no stop: usage-limit" || bad "dlim: rc=$rc $(stopped) $(result dlim)"
seq_set build -- 0
loop --ledger tasks/mh.md --max-hours 0
[ $rc -eq 0 ] && [ ! -e "$(lane mh)" ] && [ ! -s "$FIXTURE_SLOG" ] && grep -q '^max-hours' <<<"$(stopped)" \
  && ok "--max-hours 0 -> stop: max-hours before the first ledger, no session" || bad "max-hours: rc=$rc $(stopped)"
# R-0230: the preflight calls of the CLI read /dev/null, not the loop's stdin (from a
# tmux terminal, timeout's child was stopped there).
printf 'not a terminal, but not /dev/null either\n' > "$WORK/stdin.txt"
FIXTURE_STDINLOG="$WORK/stdin.log" loop --ledger tasks/mh.md --max-hours 0 < "$WORK/stdin.txt"
[ "$(grep -c . "$WORK/stdin.log" 2>/dev/null)" = 2 ] && [ "$(grep -c ' /dev/null$' "$WORK/stdin.log")" = 2 ] \
  && grep -q '^--version ' "$WORK/stdin.log" && grep -q '^auth ' "$WORK/stdin.log" \
  && ok "the preflight's claude --version and auth status read /dev/null" || bad "preflight stdin: $(cat "$WORK/stdin.log" 2>&1)"
# A session that changes the ledger every time never stalls: the run's budget ends it
# between two iterations of the same task, and the task stays open.
seq_set filesn filesn filesn filesn filesn
loop --ledger tasks/ibud.md --max-budget-usd 0.6
LB="$(lane ibud)"
[ $rc -eq 0 ] && [ "$(grep -c . "$FIXTURE_SLOG")" = 3 ] && [ "$(box ibud)" = " " ] && grep -q '^max-budget — .* ibud T1 stays open' <<<"$(stopped)" \
  && [ -z "$(git -C "$LB" status --porcelain)" ] && ! grep -q 'apps/x/w' "$LB/tasks/ibud.md" \
  && ok "a ledger changed in every iteration -> stop: max-budget inside the task after 3 sessions, the task open, the lane clean" \
  || bad "ibud: rc=$rc sessions=$(grep -c . "$FIXTURE_SLOG") $(stopped) $(git -C "$LB" status --short)"
seq_set limit
loop --ledger tasks/lim.md
LL="$(lane lim)"
[ $rc -eq 0 ] && [ "$(box lim)" = " " ] && grep -q '^usage-limit — lim T1: the subscription.s limit, resets 3:45pm' <<<"$(stopped)" \
  && [ "$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1])).get("reset"))' "$LOOPD/state.json")" = 3:45pm ] \
  && [ -z "$(git -C "$LL" status --porcelain)" ] && [ ! -e "$LL/apps/x/new.py" ] && grep -q '^Reset: 3:45pm' "$(ls -t "$LOOPD"/summary-*.md | head -n 1)" \
  && ok "the subscription's limit -> stop: usage-limit with the reset time, the task open, the lane clean" || bad "lim: rc=$rc $(stopped)"
[ "$(python3 -c 'import json, sys; t = json.load(open(sys.argv[1]))["task"]; print(t["id"], t["of"])' "$LOOPD/state.json")" = "T1 1" ] \
  && ok "state.json names the task and how many the ledger has" || bad "task in state: $(cat "$LOOPD/state.json")"
seq_set credits
loop --ledger tasks/cred.md
[ $rc -eq 74 ] && [ "$(box cred)" = " " ] && grep -q '^infra — cred T1: the CLI asks for usage credits for 1M context' <<<"$(stopped)" \
  && ok "1M context without credits -> stop: infra, not a blocked task" || bad "cred: rc=$rc $(stopped)"
seq_set harnskip
loop --ledger tasks/hskip.md
[ $rc -eq 74 ] && grep -q '^harness-modified — hskip T1: the session changed the harness path scripts/dev/ledger.sh' <<<"$(stopped)" \
  && [ -z "$(git -C "$(lane hskip)" status --porcelain)" ] && [ "$(box hskip)" = " " ] \
  && grep -q 'stop: harness-modified$' <<<"$(summary_line)" \
  && ok "a harness change with [~] -> stop: harness-modified, not a skip; the summary too" || bad "hskip: rc=$rc $(stopped)"
seq_set skip
loop --ledger tasks/skp2.md
grep -q 'stop: ledger-leer$' <<<"$(summary_line)" && ok "the end of the list -> summary with stop: ledger-leer" || bad "ledger-leer summary: $(summary_line)"

echo "── from the branch review ──"
# The CLI's checksum comes before its first call: a CLI off the record never runs.
cp "$WORK/claude.sha256" "$WORK/claude.sha256.ok"; printf '0000\n' > "$WORK/claude.sha256"
CL="$WORK/clilog"; : > "$CL"
seq_set build -- 0
FIXTURE_CLILOG="$CL" loop --ledger tasks/good.md
cp "$WORK/claude.sha256.ok" "$WORK/claude.sha256"
[ $rc -eq 74 ] && grep -q 'is not the one runner-setup.sh recorded' <<<"$(stopped)" && [ ! -s "$CL" ] \
  && ok "a CLI that is not the recorded one -> stop: infra before it ran once (no --version, no auth)" || bad "cli order: rc=$rc $(stopped) calls=$(tr '\n' ' ' < "$CL")"
# A session may change its own task only.
seq_set othertask -- 0
loop --ledger tasks/oth.md
[ $rc -eq 0 ] && [ "$(box oth)" = "?" ] && grep -q 'changed the ledger outside its own task' "$(lane oth)/tasks/oth.md" \
  && grep -q '^Status: blockiert' "$(lane oth)/tasks/oth.md" && [ ! -s "$FIXTURE_CLOG" ] && [ -z "$(git -C "$(lane oth)" status --porcelain)" ] \
  && ok "a session that changes the ledger's head -> [?], blockiert, no close" || bad "oth: rc=$rc $(result oth)"
grep -q '^+b = 1' "$LOOPD/oth/T1.aborted.diff" && grep -q '^+Status: erledigt' "$LOOPD/oth/T1.aborted.diff" \
  && ok "and aborted.diff keeps the code and the ledger change it took back (two cleanups, nothing lost)" \
  || bad "oth aborted.diff: $(cat "$LOOPD/oth/T1.aborted.diff" 2>&1)"
# No task open, but a [?]: blockiert, no handover.
seq_set build -- 0
loop --ledger tasks/qend.md
[ $rc -eq 0 ] && grep -q '^blockiert — no task open, but a \[?\] is' <<<"$(result qend)" && grep -q '^Status: blockiert' "$(lane qend)/tasks/qend.md" \
  && [ ! -e "$LOOPD/qend.bundle" ] && ok "a ledger left with a [?] -> blockiert, never bereit" || bad "qend: rc=$rc $(result qend)"
# An outage is no fault of the task: stop: infra, the task open, the lane clean.
for m in "apie apierr an API error" "nojs nojson no JSON"; do
  read -r sl mode what <<<"$m"
  seq_set "$mode"
  loop --ledger "tasks/$sl.md"
  [ $rc -eq 74 ] && grep -q "^infra — $sl T1: the build session .*$what.* — the task stays open" <<<"$(stopped)" && [ "$(box "$sl")" = " " ] \
    && [ -z "$(git -C "$(lane "$sl")" status --porcelain)" ] && ok "$what -> stop: infra, the task open, the lane clean" || bad "$sl: rc=$rc $(stopped)"
done
# A reviewer run that printed no cost counts with review-run's larger budget.
seq_set build -- 74r 74r
loop --ledger tasks/rvc.md
[ $rc -eq 74 ] && [ "$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["cost_usd"])' "$LOOPD/state.json")" = 30.25 ] \
  && ok "two reviewer runs without a cost line count 2 x 15 \$ into the run" || bad "rvc: rc=$rc $(cat "$LOOPD/state.json")"
[ "$(sed -n 's/^REVIEW_BUDGET_MAX=//p' "$REPO_ROOT/scripts/dev/ledger-loop.sh")" = \
  "$(sed -n 's/.*BUDGET=\([0-9][0-9.]*\).*/\1/p' "$REPO_ROOT/scripts/dev/review-run.sh" | sort -n | tail -n 1)" ] \
  && ok "REVIEW_BUDGET_MAX is the larger budget of review-run.sh" || bad "REVIEW_BUDGET_MAX and review-run.sh disagree"
# A ref origin/main that a session moves: the loop compares with the main it fetched.
seq_set refmove -- 0
loop --ledger tasks/refm.md
[ $rc -eq 74 ] && grep -q '^harness-modified — refm T1: the session changed the harness path scripts/dev/ledger.sh' <<<"$(stopped)" \
  && [ ! -s "$FIXTURE_CLOG" ] && ok "a moved origin/main ref hides no harness change" || bad "refm: rc=$rc $(stopped)"
# A harness-modified stop shuts the ledger until Kevin removes the marker.
[ -s "$LOOPD/refm/harness-modified" ] || bad "no marker after the refm stop"
seq_set build -- 0
loop --ledger tasks/refm.md
grep -q '^blockiert (harness-modified)' <<<"$(result refm)" && [ ! -s "$FIXTURE_SLOG" ] \
  && ok "the next run does not build a ledger with the marker" || bad "refm again: $(result refm)"
# The made-up handover looks at what the branch changed too.
seq_set build -- 0
loop --ledger tasks/hob.md
LO="$(lane hob)"
printf '# y\n' >> "$LO/scripts/dev/ledger.sh"; git -C "$LO" commit -qam "a harness path on the branch"
rm -f -- "${LOOPD:?}/hob.bundle"
seq_set
loop --ledger tasks/hob.md
[ $rc -eq 74 ] && grep -q "^harness-modified — hob: the lane's branch carries the harness path scripts/dev/ledger.sh" <<<"$(stopped)" \
  && [ ! -e "$LOOPD/hob.bundle" ] && [ -s "$LOOPD/hob/harness-modified" ] \
  && ok "a lane on bereit whose branch carries a harness path gets no made-up handover" || bad "hob: rc=$rc $(stopped)"
# A lane left on bereit beside a [?] (a run that broke off after task-close's commit).
seq_set build -- 0
loop --ledger tasks/qhb.md
LB2="$(lane qhb)"
bash "$CLONE/scripts/dev/ledger.sh" status "$LB2/tasks/qhb.md" bereit > /dev/null && git -C "$LB2" commit -qam "bereit, as task-close leaves it"
rm -f -- "${LOOPD:?}/qhb.bundle" "${LOOPD:?}/qhb/pr-body.md"
seq_set
loop --ledger tasks/qhb.md
[ $rc -eq 0 ] && grep -q '^blockiert — no task open, but a \[?\] is' <<<"$(result qhb)" && [ ! -e "$LOOPD/qhb.bundle" ] \
  && grep -q '^Status: blockiert' "$LB2/tasks/qhb.md" && ok "no made-up handover beside a [?]: blockiert" || bad "qhb: rc=$rc $(result qhb)"
# The question names only this round's verdict, and the round it came from.
mkdir -p "$LOOPD/stl"
printf '{"verdict": "request_changes", "findings": [{"severity": "blocker", "file": "old.py", "claim": "stale"}]}\n' > "$LOOPD/stl/T1.r2.verdict.json"
seq_set build build -- 3 3n
loop --ledger tasks/stl.md
[ "$(box stl)" = "?" ] && grep -q 'task-close refused twice, see ' "$(lane stl)/tasks/stl.md" && ! grep -q 'old.py' "$(lane stl)/tasks/stl.md" \
  && ok "a round without a verdict names the close log, never a verdict file left from before" || bad "stl: $(result stl)"
seq_set build build -- 3n 3
loop --ledger tasks/r1q.md
grep -q 'blocker in apps/x/a.py after round 1, the finding is in .*/r1q/T1.r1.verdict.json' "$(lane r1q)/tasks/r1q.md" \
  && ok "a second close that was round 1 says so" || bad "r1q: $(result r1q)"

echo "── what a session's code could do behind the loop ──"
seq_set commit
loop --ledger tasks/tcommit.md
[ $rc -eq 74 ] && grep -q '^harness-modified — tcommit T1: HEAD of the lane moved' <<<"$(stopped)" \
  && ok "a commit in the lane during a session -> stop: harness-modified" || bad "tcommit: rc=$rc $(stopped)"
seq_set clone -- 0
loop --ledger tasks/tclone.md
[ $rc -eq 74 ] && grep -q '^harness-modified — the clone .* changed during the run' <<<"$(stopped)" && [ ! -s "$FIXTURE_CLOG" ] \
  && ok "a change to the clone during a session -> stop before the close" || bad "tclone: rc=$rc $(stopped)"
git -C "$CLONE" checkout -q -- scripts/dev/harness-paths.txt
# The reviewer's case: the suite of a failing close commits — the loop must see it.
seq_set build -- 3c
loop --ledger tasks/tfail.md
[ $rc -eq 74 ] && grep -q '^harness-modified — tfail T1: HEAD of the lane moved during a close that ended with 3' <<<"$(stopped)" \
  && [ "$(grep -c . "$FIXTURE_SLOG")" = 1 ] \
  && ok "a commit made during a failing close -> stop: harness-modified, no fix session" || bad "tfail: rc=$rc $(stopped)"
cp "$FHOME/.local/bin/claude" "$WORK/claude.pristine"
seq_set cli -- 0
loop --ledger tasks/tcli.md
[ $rc -eq 74 ] && grep -q "^infra — the claude CLI .* is not the one runner-setup.sh recorded" <<<"$(stopped)" && [ ! -s "$FIXTURE_CLOG" ] \
  && ok "a changed claude CLI -> stop: infra before the close" || bad "tcli: rc=$rc $(stopped)"
cp "$WORK/claude.pristine" "$FHOME/.local/bin/claude"

echo "── origin/main moved ──"
# A plain change on main: the clone fast-forwards. It also makes the conflict plan
# collide with main.
printf 'main\n' > "$SEED/apps/c.txt"; git -C "$SEED" commit -qam "docs: main moves" && git -C "$SEED" push -q origin main
loop --ledger tasks/conflict.md
[ $rc -eq 0 ] && [ "$(git -C "$CLONE" rev-parse main)" = "$(git -C "$SEED" rev-parse main)" ] \
  && ok "behind origin/main without a harness change -> fast-forwarded" || bad "ff: rc=$rc out=$OUT"
LC="$(lane conflict)"
grep -q '^blockiert (merge)' <<<"$(result conflict)" && [ -z "$(git -C "$LC" status --porcelain)" ] \
  && [ ! -e "$(git -C "$LC" rev-parse --git-path MERGE_HEAD)" ] \
  && ok "a merge conflict -> merge aborted, blockiert (merge), the lane clean" || bad "conflict: $(result conflict) $(git -C "$LC" status --short 2>&1)"
OLD=$(git -C "$CLONE" rev-parse main)
# A harness file moved to a name the list does not know counts by its old path.
git -C "$SEED" mv scripts/dev/runner-claude.version docs/pin.txt && git -C "$SEED" commit -qm "refactor: move the pin" \
  && git -C "$SEED" push -q origin main
loop --ledger tasks/good.md
[ $rc -eq 74 ] && grep -q 'Harness auf main geändert (scripts/dev/runner-claude.version)' <<<"$(stopped)" \
  && [ "$(git -C "$CLONE" rev-parse main)" = "$OLD" ] \
  && ok "a harness file renamed on main -> 74, no pull" || bad "harness rename: rc=$rc $(stopped)"
printf '# changed\n' >> "$SEED/scripts/dev/ledger.sh"; git -C "$SEED" commit -qam "fix(scripts): a harness change" && git -C "$SEED" push -q origin main
loop --ledger tasks/good.md
[ $rc -eq 74 ] && grep -q 'Harness auf main geändert' <<<"$(stopped)" && [ "$(git -C "$CLONE" rev-parse main)" = "$OLD" ] \
  && ok "behind origin/main with a harness change -> 74, no pull" || bad "harness on main: rc=$rc $(stopped)"

echo "── status ──"
printf '{"run": {"started": "2026-10-04T01:12:00+02:00"}, "stop": "infra\\u001b[31m", "stop_reason": "x\\u0007y", "ledgers": {"evil\\u001b]0;t\\u0007": {"result": "aktiv"}}}' > "$WORK/s.json"
OUT=$(bash "$CLONE/scripts/dev/ledger-loop.sh" status --state "$WORK/s.json" 2>&1); rc=$?
[ $rc -eq 0 ] && ! grep -q $'\e\|\a' <<<"$OUT" && grep -q 'stop: infra\[31m' <<<"$OUT" && grep -q 'evil\]0;t' <<<"$OUT" \
  && ok "status prints state.json with its control characters cleaned" || bad "status: rc=$rc $(cat -v <<<"$OUT")"
printf '{"run": [1], "stop": "infra"}' > "$WORK/s.json"
OUT=$(bash "$CLONE/scripts/dev/ledger-loop.sh" status --state "$WORK/s.json" 2>&1); rc=$?
[ $rc -eq 0 ] && grep -q 'Worker: stop: infra' <<<"$OUT" && ! grep -q Traceback <<<"$OUT" && ok "a run field of the wrong type is no traceback" || bad "run list: $OUT"
printf 'not json' > "$WORK/s.json"
OUT=$(bash "$CLONE/scripts/dev/ledger-loop.sh" status --state "$WORK/s.json" 2>&1); rc=$?
[ $rc -eq 0 ] && grep -q 'Worker: ? (state.json unlesbar)' <<<"$OUT" && ok "a broken state.json is named, not a crash" || bad "broken state: rc=$rc $OUT"
OUT=$(bash "$CLONE/scripts/dev/ledger-loop.sh" status --state "$WORK/none.json" 2>&1); rc=$?
[ $rc -eq 0 ] && [ "$OUT" = "Worker: —" ] && ok "no state file -> Worker: —" || bad "no state: $OUT"
SD="$WORK/sdir"; mkdir -p "$SD"
printf '{"run": {"started": "2026-10-04T01:12:00+02:00"}, "stop": null, "cost_usd": 4.1, "task": {"ledger": "tasks/x.md", "id": "T3", "of": 8}}' > "$SD/state.json"
printf '# old\n\nStop: max-tasks\n\nledger-loop: 9 tasks, 0 ready, 0 blocked, $1.00 total, stop: max-tasks\n' > "$SD/summary-2026-10-03-230000.md"
printf '# new\n\nStop: ledger-leer\n\nledger-loop: 2 tasks, 1 ready, 1 blocked, $3.20 total, stop: ledger-leer\n' > "$SD/summary-2026-10-04-064000.md"
OUT=$(bash "$CLONE/scripts/dev/ledger-loop.sh" status --state "$SD/state.json" 2>&1)
[ "$(head -n 1 <<<"$OUT")" = 'Worker: läuft T3/8 tasks/x.md · 4,10 $ · seit 01:12' ] \
  && grep -qx '    ledger-loop: 2 tasks, 1 ready, 1 blocked, \$3.20 total, stop: ledger-leer' <<<"$OUT" && ! grep -q '9 tasks' <<<"$OUT" \
  && ok "status: the worker's line first, then the last lines of the newest summary" || bad "status lines: $OUT"
printf '{"run": {"started": "2026-10-04T01:12:00+02:00"}, "stop": null, "cost_usd": 1e300}' > "$SD/state.json"
{ printf '# big\n\nStop: x\n'; for i in $(seq 1 40); do printf 'line %s\n' "$i"; done; } > "$SD/summary-2026-10-05-000000.md"
OUT=$(bash "$CLONE/scripts/dev/ledger-loop.sh" status --state "$SD/state.json" 2>&1)
[ "$(head -n 1 <<<"$OUT")" = 'Worker: läuft · ? $ · seit 01:12' ] && [ "$(grep -c '^    ' <<<"$OUT")" = 10 ] \
  && ok "status: a cost out of range reads ?, and at most ten summary lines" || bad "status caps: $OUT"

echo "── repo wiring ──"
for p in scripts/dev/ledger-loop.sh scripts/tests/ledger_loop_test.sh; do
  grep -qxF "$p" "$REPO_ROOT/scripts/dev/harness-paths.txt" && ok "$p is a harness path" || bad "$p is missing from harness-paths.txt"
done
sed -n '/^AH_SCRIPT_TESTS_DEFAULT=/,/"$/p' "$REPO_ROOT/scripts/tests/run.sh" | grep -qw 'ledger_loop_test' \
  && ok "ledger_loop_test is registered in AH_SCRIPT_TESTS_DEFAULT" || bad "not registered"
if command -v shellcheck >/dev/null 2>&1; then
  shellcheck --severity=warning "$REPO_ROOT/scripts/dev/ledger-loop.sh" && ok "shellcheck: ledger-loop.sh is clean" || bad "shellcheck findings in ledger-loop.sh"
fi

echo ""
echo "ledger_loop_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
