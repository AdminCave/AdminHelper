#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# review_scripts_test.sh — hermetic test for scripts/dev/review.sh.
#
# sec and risk read a real git diff, so the fixture is a real repository:
# `git init` in a temp dir with review.sh copied into it (the script resolves its
# root from its own location). Nothing here touches the developer's checkout or
# its index — which matters, because sec decides whether a commit happens.
#
# Run: bash scripts/tests/review_scripts_test.sh

# ok()/bad() never fail; `cond && ok || bad` assertions are deliberate.
# shellcheck disable=SC2015
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../.." && pwd)

PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

command -v git >/dev/null 2>&1 || { echo "SKIP: git not available"; exit 75; }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
FIX="$WORK/repo"
REVIEW="$FIX/scripts/dev/review.sh"

# git tracks files, not directories, so `git clean -fd` removes every empty one:
# the skeleton is rebuilt after each reset instead of being assumed.
SKELETON=(scripts/dev scripts/tests apps/server/app apps/server/tests docs docs/features tasks/private .claude)
mkskel() { local d; for d in "${SKELETON[@]}"; do mkdir -p "$FIX/$d"; done; }
mkskel
cp "$REPO_ROOT/scripts/dev/review.sh" "$REVIEW"
cat > "$FIX/tasks/fix.md" <<'MD'
# Fixture — Task-Ledger
Status: aktiv · Branch: feature/fixture

### T1 — eine Aufgabe  [ ]
Komponente: scripts · Dateien: scripts/dev/tool.sh (neu, SPDX), scripts/dev/other.sh
Änderung: irgendwas
Verify: bash scripts/dev/verify.sh scripts --strict

### T2 — eine Server-Aufgabe  [ ]
Komponente: server · Dateien: apps/server/app/thing.py
Änderung: irgendwas
Verify: bash scripts/dev/verify.sh server --strict

### T3 — eine Agent-Aufgabe  [ ]
Komponente: agent · Dateien: apps/agent/cmd/root.go (neu, SPDX), apps/agent/cmd/other.go
Änderung: irgendwas
Verify: bash scripts/dev/verify.sh agent --strict
MD
printf 'tasks/private/\n' > "$FIX/.gitignore"
printf 'set -e\necho hello\n' > "$FIX/scripts/dev/tool.sh"
printf '# changelog\n' > "$FIX/CHANGELOG.md"

git -C "$FIX" init -q
git -C "$FIX" config user.email test@example.invalid
git -C "$FIX" config user.name "Fixture"
# A global core.autocrlf would change the bytes the checks read.
git -C "$FIX" config core.autocrlf false
git -C "$FIX" add -A
git -C "$FIX" commit -qm "fixture"

r() { OUT=$(bash "$REVIEW" "$@" 2>&1); rc=$?; }
stage() { git -C "$FIX" add -- "$@"; }
reset_index() { git -C "$FIX" reset -q --hard HEAD; git -C "$FIX" clean -qfd; mkskel; }

# ══ arguments ═════════════════════════════════════════════════════════════════
echo "── arguments ──"
r
[ $rc -eq 2 ] && grep -q "needs a verb" <<<"$OUT" && ok "no verb -> exit 2" || bad "bare: rc=$rc"
r schnupfen
[ $rc -eq 2 ] && ok "unknown verb -> exit 2" || bad "unknown verb: rc=$rc"
r sec --bogus
[ $rc -eq 2 ] && grep -q "unknown flag" <<<"$OUT" && ok "unknown flag -> exit 2" || bad "flag: rc=$rc"


# ══ sec ═══════════════════════════════════════════════════════════════════════
echo "── sec ──"
r sec --staged
[ $rc -eq 0 ] && ok "an empty index is clean" || bad "sec empty: rc=$rc out=$OUT"

# gitignored — but `git add -f` would take it, which is exactly the accident this
# verb exists for.
printf 'internal\n' > "$FIX/tasks/private/roadmap.md"
git -C "$FIX" add -f -- tasks/private/roadmap.md
r sec --staged
[ $rc -eq 4 ] && grep -q "tasks/private/roadmap.md" <<<"$OUT" \
  && ok "tasks/private/** staged -> exit 4" || bad "private: rc=$rc out=$OUT"
reset_index

printf 'finding\n' > "$FIX/tasks/sec-2026-09.md"
stage tasks/sec-2026-09.md
r sec --staged
[ $rc -eq 4 ] && ok "tasks/sec-*.md staged -> exit 4" || bad "sec ledger: rc=$rc out=$OUT"
reset_index

printf 'spec\n' > "$FIX/docs/features/sec-leak.md"
stage docs/features/sec-leak.md
r sec --staged
[ $rc -eq 4 ] && ok "docs/features/sec-*.md staged -> exit 4" || bad "sec spec: rc=$rc out=$OUT"
reset_index

# Assembled at run time: written out literally, this fixture line would make the
# test file itself unstageable — sec has no escape hatch, and that is the point.
printf 'Dedup-%s: sec:ssrf-resolver\n' Key >> "$FIX/docs/thing.md"
stage docs/thing.md
r sec --staged
[ $rc -eq 4 ] && grep -q "docs/thing.md:" <<<"$OUT" \
  && ok "a security finding's Dedup-Key in the diff -> exit 4, naming the line" || bad "dedup key: rc=$rc out=$OUT"
reset_index

# The regression that made this verb lie: `grep -q` left the pipeline at the
# first hit, git diff died of SIGPIPE, and pipefail turned the hit into "clean"
# for every diff bigger than the 64 KiB pipe buffer.
reset_index
{ printf 'Dedup-%s: sec:ssrf-resolver\n' Key; for i in $(seq 1 40000); do printf 'filler line %d\n' "$i"; done; } \
  > "$FIX/docs/big.md"
stage docs/big.md
r sec --staged
[ $rc -eq 4 ] && ok "the Dedup-Key is still caught in a diff far beyond the pipe buffer ($(wc -c < "$FIX/docs/big.md") bytes)" \
  || bad "big diff: rc=$rc out=$OUT"
reset_index

# The two gitignored files that really carry credentials on this box.
reset_index
printf 'export AH_TEST_DB=postgresql://u:secret@localhost/db\n' > "$FIX/.devenv.sh"
git -C "$FIX" add -f -- .devenv.sh
r sec --staged
[ $rc -eq 4 ] && grep -q "carries credentials" <<<"$OUT" \
  && ok ".devenv.sh staged -> exit 4 (it carries the database password)" || bad "devenv: rc=$rc out=$OUT"
reset_index
mkdir -p "$FIX/.claude"
printf '{"env":{"AH_PVE_TOKEN":"secret"}}\n' > "$FIX/.claude/settings.local.json"
git -C "$FIX" add -f -- .claude/settings.local.json
r sec --staged
[ $rc -eq 4 ] && ok ".claude/settings.local.json staged -> exit 4 (it carries the Proxmox token)" \
  || bad "settings.local: rc=$rc out=$OUT"
reset_index

# Token patterns (R-0183). Each is put together at run time — written out, it would stop
# this very file at sec — and the output names file:line, never the token.
T_GH="gh""p_$(printf 'Ab3%.0s' $(seq 1 12))"
T_PAT="github""_pat_$(printf 'b7Q%.0s' $(seq 1 27))x"
T_ANT="sk-""ant-api03-$(printf 'c4Z%.0s' $(seq 1 14))"
T_PVE="ah@pve!run=""12345678-90ab-cdef-1234-567890abcdef"
for tk in "$T_GH" "$T_PAT" "$T_ANT" "$T_PVE"; do
  reset_index
  printf 'note\nsee %s here\n' "$tk" > "$FIX/docs/tok.md"; stage docs/tok.md
  r sec --staged
  [ $rc -eq 4 ] && grep -q "docs/tok.md:2 (a token pattern)" <<<"$OUT" && ! grep -qF "$tk" <<<"$OUT" \
    && ok "a ${tk:0:7}… token in the diff -> exit 4 with file:line, never the token" || bad "token ${tk:0:7}: rc=$rc out=$OUT"
done
# What code, docs and tests write in their place passes: shorter than any real token.
reset_index
{ printf '%s\n' 'CLAUDE_CODE_OAUTH_TOKEN="sk-ant-oat-fixture"' 'Authorization: PVEAPIToken=user@pve!vm=<secret>'
  printf '%s\n' "PVEAPIToken=ah@pve!probe=TOKEN-0123" "gh""p_short and github""_pat_short"; } > "$FIX/docs/tok.md"
stage docs/tok.md
r sec --staged
[ $rc -eq 0 ] && ok "the placeholders of code, docs and tests are no token" || bad "placeholders: rc=$rc out=$OUT"
# A placeholder at full length, as docs write one: a body of at most two characters.
reset_index
{ printf 'gh%s\n' "p_$(printf 'x%.0s' $(seq 1 36))"; printf 'sk-%s\n' "ant-api03-$(printf 'x%.0s' $(seq 1 40))"
  printf 'root@pam!monitoring=%s\n' "00000000-0000-0000-0000-000000000000"; printf 'github%s\n' "_pat_$(printf 'xy%.0s' $(seq 1 41))"; } \
  > "$FIX/docs/tok.md"
stage docs/tok.md
r sec --staged
[ $rc -eq 0 ] && ok "a full-length placeholder (xxxx…, 0000-…) is no token" || bad "full placeholders: rc=$rc out=$OUT"
# More Proxmox forms (R-0196): the PBS colon form, the URL-encoded form and the secret
# alone behind a key name. Key name and UUID meet only at run time, as above.
U="12345678-90ab-cdef-1234-567890abcdef"; K="token_""secret"; Z="00000000-0000-0000-0000-000000000000"
for tk in "ah@pbs!run:$U" "ah%40pve%21run%3D$U" "ah%40pve%21run%3d$U" "api_$K = $U" "\"$K\": \"$U\"" "PVE_${K^^}=$U" "PVE_${K^^}=\${PVE_${K^^}:-$U}"; do
  reset_index
  printf 'note\nsee %s here\n' "$tk" > "$FIX/docs/tok.md"; stage docs/tok.md
  r sec --staged
  [ $rc -eq 4 ] && grep -q "docs/tok.md:2 (a token pattern)" <<<"$OUT" && ! grep -qF "$U" <<<"$OUT" \
    && ok "the form ${tk:0:12}… -> exit 4 with file:line, never the token" || bad "form ${tk:0:12}: rc=$rc out=$OUT"
done
# The same forms as placeholders, a bare UUID without a key name, and a key that only
# starts like one.
reset_index
printf '%s\n' "ah@pbs!run:$Z" "ah%40pve%21run%3D$Z" "api_$K = $Z" "id $U" "${K}_file = /etc/x" > "$FIX/docs/tok.md"
stage docs/tok.md
r sec --staged
[ $rc -eq 0 ] && ok "placeholders of the new forms, a bare UUID and a longer key name are no token" \
  || bad "new-form placeholders: rc=$rc out=$OUT"
# sec --message (R-0197): the message of the commit being made, as the commit-msg hook
# hands it over. With an editor (--editor) and commit -v, the diff below the scissors
# line is no part of it; a comment line is, since git keeps it in a commit made with -m.
MSG="$WORK/commit-msg.txt"
printf 'subject\n\nbody with %s in it\n' "$T_GH" > "$MSG"
r sec --message "$MSG"
[ $rc -eq 4 ] && grep -q "the commit message:3 (a token pattern)" <<<"$OUT" && ! grep -qF "$T_GH" <<<"$OUT" \
  && ok "sec --message: a token -> exit 4 with the line, never the token" || bad "message token: rc=$rc out=$OUT"
printf 'subject\n\nbody with gh%s only\n' "p_short" > "$MSG"
r sec --message "$MSG"
[ $rc -eq 0 ] && grep -qx "sec: clean" <<<"$OUT" && ok "sec --message: a placeholder is clean" || bad "message placeholder: rc=$rc out=$OUT"
printf 'subject\n# ------------------------ >8 ------------------------\ndiff --git a/f b/f\n-old %s\n' "$T_GH" > "$MSG"
r sec --message "$MSG" --editor
[ $rc -eq 0 ] && ok "sec --message: the diff below the scissors line does not count" \
  || bad "message scissors: rc=$rc out=$OUT"
printf 'subject\n# %s\n' "$T_GH" > "$MSG"
r sec --message "$MSG"
[ $rc -eq 4 ] && grep -q "the commit message:2 (a token pattern)" <<<"$OUT" \
  && ok "sec --message: a token on a comment line counts (git keeps it with -m)" || bad "message comment: rc=$rc out=$OUT"
printf 'subject %s\n' "$T_GH" > "$WORK/rel-msg.txt"
OUT=$(cd "$WORK" && bash "$REVIEW" sec --message rel-msg.txt 2>&1); rc=$?
[ $rc -eq 4 ] && grep -q "the commit message:1" <<<"$OUT" \
  && ok "sec --message resolves a relative path from where the caller stands" || bad "message relative: rc=$rc out=$OUT"
rm -f -- "$WORK/rel-msg.txt"
r sec --message "$WORK/no-such-message"
[ $rc -eq 2 ] && ok "sec --message on a missing file -> exit 2 (the hook fails closed)" || bad "message missing: rc=$rc out=$OUT"
r sec --staged --message "$MSG"
[ $rc -eq 2 ] && ok "sec --message stands alone (with --staged -> exit 2)" || bad "message with staged: rc=$rc out=$OUT"
r sec --message ""
[ $rc -eq 2 ] && grep -q "got an empty one" <<<"$OUT" && ! grep -q "sec: clean" <<<"$OUT" \
  && ok "sec --message with an empty name -> exit 2, no sec over the worktree" || bad "message empty: rc=$rc out=$OUT"
# R-0213: git truncates at the scissors line only with commit -v or with an editor
# and cleanup=scissors. Typed into -m, -F or an editor without -v, the line and
# what follows it stay in the commit — so they are read, with --editor up to the
# first diff header below the exact line.
CUT='# ------------------------ >8 ------------------------'
printf 'subject\n\n%s\nbelow %s\n' "$CUT" "$T_GH" > "$MSG"
r sec --message "$MSG"
[ $rc -eq 4 ] && grep -q "the commit message:4 (a token pattern)" <<<"$OUT" \
  && ok "sec --message: a token below a scissors line typed into -m counts (R-0213)" || bad "message typed scissors: rc=$rc out=$OUT"
r sec --message "$MSG" --editor
[ $rc -eq 4 ] && grep -q "the commit message:4 (a token pattern)" <<<"$OUT" \
  && ok "sec --message --editor: below the scissors line without a diff it counts" || bad "editor no diff: rc=$rc out=$OUT"
# Without --editor not even a diff header below the line ends the scan: only an
# editor's commit -v puts one there.
printf 'subject\n\n%s\ndiff --git a/f b/f\n+below %s\n' "$CUT" "$T_GH" > "$MSG"
r sec --message "$MSG"
[ $rc -eq 4 ] && grep -q "the commit message:5 (a token pattern)" <<<"$OUT" \
  && ok "sec --message without --editor: a diff header typed below the scissors line ends nothing" || bad "message typed diff: rc=$rc out=$OUT"
printf 'subject\n%s\n# Do not modify or remove the line above.\nnote %s\ndiff --git a/f b/f\n' "$CUT" "$T_GH" > "$MSG"
r sec --message "$MSG" --editor
[ $rc -eq 4 ] && grep -q "the commit message:4 (a token pattern)" <<<"$OUT" \
  && ok "sec --message --editor: between the scissors line and the diff it counts" || bad "editor above diff: rc=$rc out=$OUT"
printf 'subject\n\n# --- >8 ---\ndiff --git a/f b/f\n-old %s\n' "$T_GH" > "$MSG"
r sec --message "$MSG" --editor
[ $rc -eq 4 ] && grep -q "the commit message:5 (a token pattern)" <<<"$OUT" \
  && ok "sec --message --editor: only the exact scissors line cuts, not a shorter one" || bad "editor short line: rc=$rc out=$OUT"
r sec --editor
[ $rc -eq 2 ] && grep -q "editor goes with --message" <<<"$OUT" \
  && ok "sec --editor without --message -> exit 2" || bad "editor alone: rc=$rc out=$OUT"
rm -f -- "$MSG"
reset_index

printf 'ordinary docs\n' >> "$FIX/CHANGELOG.md"
stage CHANGELOG.md
r sec --staged
[ $rc -eq 0 ] && ok "an ordinary change is not blocked" || bad "false block: rc=$rc out=$OUT"

# ══ sec --range: what a push or a pull request takes along (R-0123) ═══════════
echo "── sec --range ──"
# A repository of its own: these cases commit and branch. Every commit of the span
# counts, not the net diff — a file added and removed again still leaves with a push.
RFIX="$WORK/range"; mkdir -p "$RFIX/scripts/dev" "$RFIX/tasks/private" "$RFIX/docs"
cp "$REPO_ROOT/scripts/dev/review.sh" "$RFIX/scripts/dev/review.sh"
printf 'tasks/private/\n' > "$RFIX/.gitignore"; printf 'one\n' > "$RFIX/docs/a.md"
rg() { git -C "$RFIX" -c user.name=Fixture -c user.email=t@example.invalid "$@"; }
rr() { OUT=$(bash "$RFIX/scripts/dev/review.sh" "$@" 2>&1); rc=$?; }
rg init -q -b main; rg add -A; rg commit -qm base; RBASE="$(rg rev-parse HEAD)"
printf 'internal\n' > "$RFIX/tasks/private/x.md"; rg add -f -- tasks/private/x.md; rg commit -qm "private"
rr sec --range "$RBASE..HEAD"
[ $rc -eq 4 ] && grep -q "tasks/private/x.md (commit " <<<"$OUT" \
  && ok "a private file in the span -> exit 4, with the commit" || bad "range private: rc=$rc out=$OUT"
rg rm -q -- tasks/private/x.md; rg commit -qm "gone again"
[ -z "$(rg diff --name-only "$RBASE" HEAD)" ] || bad "fixture: the net diff should be empty"
rr sec --range "$RBASE..HEAD"
[ $rc -eq 4 ] && grep -q "tasks/private/x.md" <<<"$OUT" \
  && ok "added and removed again inside the span -> still exit 4 (the net diff is empty)" || bad "range history: rc=$rc out=$OUT"
RCLEAN="$(rg rev-parse HEAD)"
printf 'two\n' >> "$RFIX/docs/a.md"; rg add -A; rg commit -qm "ordinary"
rr sec --range "$RCLEAN..HEAD"
[ $rc -eq 0 ] && grep -qx "sec: clean" <<<"$OUT" && ok "a clean span -> sec: clean" || bad "range clean: rc=$rc out=$OUT"
# A span without a commit has nothing to call clean (R-0174); exit 0 all the same.
for span in HEAD..HEAD HEAD...HEAD; do
  rr sec --range "$span"
  [ $rc -eq 0 ] && [ "$OUT" = "sec: empty span ($span) — nothing read" ] \
    && ok "an empty span ($span) -> 'nothing read', exit 0, not 'clean'" || bad "empty span $span: rc=$rc out=$OUT"
done
# The key is assembled at run time: written out, it would stop this very file at sec.
printf 'x\nDedup-%s: sec:%s\n' Key "server:leak.py:probe" >> "$RFIX/docs/a.md"; rg add -A; rg commit -qm "a finding"
rr sec --range "$RCLEAN..HEAD"
[ $rc -eq 4 ] && grep -q "docs/a.md:4 (commit " <<<"$OUT" && ! grep -q "leak.py" <<<"$OUT" \
  && ok "a security finding's Dedup-Key -> exit 4 with file:line, never the line" || bad "range key: rc=$rc out=$OUT"
printf 'gh %s\n' "$T_GH" > "$RFIX/docs/tok.md"; rg add -A; rg commit -qm "a token"
rr sec --range "HEAD~1..HEAD"
[ $rc -eq 4 ] && grep -q "docs/tok.md:1 (commit .*(a token pattern)" <<<"$OUT" && ! grep -qF "$T_GH" <<<"$OUT" \
  && ok "a token in a commit of the span -> exit 4 with file:line, never the token" || bad "range token: rc=$rc out=$OUT"
rg rm -q -- docs/tok.md; rg commit -qm "no token"
# The message leaves with the push as well (R-0183): it names the commit, never the token.
rg commit --allow-empty -qm "fix: call the API with $T_GH"
rr sec --range "HEAD~1..HEAD"
[ $rc -eq 4 ] && grep -q "the commit message:1 (commit .*(a token pattern)" <<<"$OUT" && ! grep -qF "$T_GH" <<<"$OUT" \
  && ok "a token in a commit message -> exit 4 naming the commit, never the token" || bad "message token: rc=$rc out=$OUT"
rr sec --staged --range "$RCLEAN..HEAD"
[ $rc -eq 2 ] && ok "--staged with --range -> usage error" || bad "staged+range: rc=$rc out=$OUT"
rr sec --range "$RCLEAN..nosuchref"
[ $rc -eq 2 ] && ok "a range git does not know -> usage error, not clean" || bad "bad range: rc=$rc out=$OUT"
rr sec --staged --not-on origin
[ $rc -eq 2 ] && ok "--not-on without --range -> usage error" || bad "not-on alone: rc=$rc out=$OUT"
# Merges: a branch that merges main brings main's lines — public already — along.
# Read by what the merge brings itself, against all its parents, they are no finding;
# what the merge adds on its own is.
rg reset -q --hard "$RCLEAN"; rg checkout -q -b feature
printf 'feature\n' > "$RFIX/docs/f.md"; rg add -A; rg commit -qm "feature"
rg checkout -q main
printf 'Dedup-%s: sec:%s\n' Key "old:main.md:line" > "$RFIX/docs/main.md"; rg add -A; rg commit -qm "main has a key line"
rg checkout -q feature; rg merge -q --no-edit main
rr sec --range "main...feature"
[ $rc -eq 0 ] && ok "a merge of main into the branch brings no finding of its own" || bad "merge of main: rc=$rc out=$OUT"
rg checkout -q -b feature2 "$RCLEAN"
printf 'feature two\n' > "$RFIX/docs/f2.md"; rg add -A; rg commit -qm "feature two"
rg merge -q --no-commit --no-ff main >/dev/null
mkdir -p "$RFIX/tasks/private"; printf 'internal\n' > "$RFIX/tasks/private/m.md"; rg add -f -- tasks/private/m.md
printf 'Dedup-%s: sec:%s\n' Key "evil:merge.md:line" > "$RFIX/docs/merge.md"; rg add -- docs/merge.md
rg commit -qm "a merge that adds a private file"
rr sec --range "main...feature2"
[ $rc -eq 4 ] && grep -q "tasks/private/m.md (merge " <<<"$OUT" && grep -q "docs/merge.md:1 (merge " <<<"$OUT" \
  && ok "a merge that adds a private file or a key line itself -> exit 4" || bad "evil merge: rc=$rc out=$OUT"
rg checkout -q -b feature3 "$RCLEAN"
printf 'feature three\n' > "$RFIX/docs/f3.md"; rg add -A; rg commit -qm "feature three"
rg merge -q --no-commit --no-ff main >/dev/null
printf 'pve %s\n' "$T_PVE" > "$RFIX/docs/mtok.md"; rg add -- docs/mtok.md
rg commit -qm "a merge that adds a token line"
rr sec --range "main...feature3"
[ $rc -eq 4 ] && grep -q "docs/mtok.md:1 (merge .*(a token pattern)" <<<"$OUT" && ! grep -qF "$T_PVE" <<<"$OUT" \
  && ok "a merge that adds a token line itself -> exit 4, never the token" || bad "token merge: rc=$rc out=$OUT"
rg checkout -q -b feature4 "$RCLEAN"
printf 'feature four\n' > "$RFIX/docs/f4.md"; rg add -A; rg commit -qm "feature four"
rg merge -q --no-ff -m "Merge remote-tracking branch 'origin/main' into feature4" main
rr sec --range "main...feature4"
[ $rc -eq 0 ] && ok "a merge message 'Merge remote-tracking branch …' is no finding" || bad "merge message: rc=$rc out=$OUT"
# "\ No newline at end of file" counts no line (R-0194): a finding after it keeps its
# number, in a commit and in a merge. A repository of its own, to leave the span above alone.
NFIX="$WORK/nonl"; mkdir -p "$NFIX/scripts/dev" "$NFIX/docs"
cp "$REPO_ROOT/scripts/dev/review.sh" "$NFIX/scripts/dev/review.sh"
ng() { git -C "$NFIX" -c user.name=Fixture -c user.email=t@example.invalid "$@"; }
nr() { OUT=$(bash "$NFIX/scripts/dev/review.sh" "$@" 2>&1); rc=$?; }
printf 'a' > "$NFIX/docs/nl.md"; ng init -q -b main; ng add -A; ng commit -qm base; NBASE="$(ng rev-parse HEAD)"
printf 'a\nb\nsee %s\n' "$T_PVE" > "$NFIX/docs/nl.md"; ng add -A; ng commit -qm "a token after the old last line"
nr sec --range "$NBASE..HEAD"
[ $rc -eq 4 ] && grep -q "docs/nl.md:3 (commit " <<<"$OUT" \
  && ok "a finding after \"No newline\" names its own line (3), not the next" || bad "nonl commit: rc=$rc out=$OUT"
# Both parents of the merge carry the old last line again, so the merge alone brings the token.
printf 'a' > "$NFIX/docs/nl.md"; ng add -A; ng commit -qm "back to the old last line"; NBACK="$(ng rev-parse HEAD)"
ng checkout -q -b side "$NBACK"; printf 'side\n' > "$NFIX/docs/side.md"; ng add -A; ng commit -qm side
ng checkout -q main; printf 'main\n' > "$NFIX/docs/main.md"; ng add -A; ng commit -qm main
ng checkout -q side; ng merge -q --no-commit --no-ff main >/dev/null
printf 'a\nb\nsee %s\n' "$T_PVE" > "$NFIX/docs/nl.md"; ng add -- docs/nl.md; ng commit -qm "a merge that edits it"
nr sec --range "main...side"
[ $rc -eq 4 ] && grep -q "docs/nl.md:3 (merge " <<<"$OUT" \
  && ok "in a merge (git prints no marker in --cc) the finding names line 3 as well" || bad "nonl merge: rc=$rc out=$OUT"
rg checkout -q feature2
# A push: commits the remote has already are no part of what leaves.
rg update-ref refs/remotes/origin/main main
rr sec --range "$RCLEAN..feature"
[ $rc -eq 4 ] && grep -q "docs/main.md" <<<"$OUT" && ok "without --not-on main's commits in the span count" || bad "no not-on: rc=$rc out=$OUT"
rr sec --range "$RCLEAN..feature" --not-on origin
[ $rc -eq 0 ] && ok "--not-on origin leaves out what origin already has" || bad "not-on: rc=$rc out=$OUT"
# A path with `"` or `\` comes out of --name-only C-quoted, and a quoted path matched
# no pattern: read NUL-separated, it is blocked like any other.
rg checkout -q main
mkdir -p "$RFIX/tasks/private"; printf 'q\n' > "$RFIX/tasks/private/a\"b.md"
rg add -f -- "tasks/private/a\"b.md"; rg commit -qm "a quoted private path"
rr sec --range "HEAD~1..HEAD"
[ $rc -eq 4 ] && grep -qF 'tasks/private/a"b.md (commit ' <<<"$OUT" \
  && ok "a private path with a quote in its name -> exit 4 (range)" || bad "quoted range: rc=$rc out=$OUT"
rg rm -q --cached -- "tasks/private/a\"b.md"; rg commit -qm "untracked again"
rg add -f -- "tasks/private/a\"b.md"
rr sec --staged
[ $rc -eq 4 ] && grep -qF 'tasks/private/a"b.md' <<<"$OUT" \
  && ok "... and staged -> exit 4" || bad "quoted staged: rc=$rc out=$OUT"
rg reset -q -- "tasks/private/a\"b.md"; rm -f "$RFIX/tasks/private/a\"b.md"
rg checkout -q feature2   # the job cases below read the evil merge of this branch
# A git that cannot read a commit of the span is no clean span.
BROKEN="$WORK/broken"; git init -q -b main "$BROKEN"; mkdir -p "$BROKEN/scripts/dev"
cp "$REPO_ROOT/scripts/dev/review.sh" "$BROKEN/scripts/dev/review.sh"
git -C "$BROKEN" add -A; git -C "$BROKEN" -c user.name=F -c user.email=f@example.invalid commit -qm base
printf 'lost\n' > "$BROKEN/lost.md"; git -C "$BROKEN" add lost.md
git -C "$BROKEN" -c user.name=F -c user.email=f@example.invalid commit -qm "a blob that goes missing"
BLOB="$(git -C "$BROKEN" rev-parse HEAD:lost.md)"
rm -f "$BROKEN/.git/objects/${BLOB:0:2}/${BLOB:2}"
OUT=$(bash "$BROKEN/scripts/dev/review.sh" sec --range "HEAD~1..HEAD" 2>&1); rc=$?
[ $rc -ne 0 ] && [ $rc -ne 4 ] && ! grep -q "sec: clean" <<<"$OUT" \
  && ok "a commit git cannot read -> an error, not 'sec: clean'" || bad "missing object: rc=$rc out=$OUT"

# ══ ci.yml: the public repo guard (R-0123) ════════════════════════════════════
echo "── ci.yml: Public repo guard (review.sh sec) ──"
CI="$REPO_ROOT/.github/workflows/ci.yml"
JOB="$(awk '/^  public-repo-guard:/ { f = 1; print; next } f && /^  [A-Za-z0-9_-]+:/ { exit } f' "$CI")"
grep -qx '    name: Public repo guard (review.sh sec)' <<<"$JOB" \
  && ok "the job carries the name the ruleset requires" || bad "no job named 'Public repo guard (review.sh sec)'"
grep -q 'fetch-depth: 0' <<<"$JOB" && grep -qF 'bash "$1" sec --range "$range"' <<<"$JOB" \
  && grep -qx ' *guard scripts/dev/review.sh' <<<"$JOB" \
  && ok "it fetches the whole history and runs review.sh sec --range" || bad "job steps: $JOB"
! grep -q 'secrets\.' <<<"$JOB" && ok "it uses no secret (it runs for fork pull requests too)" || bad "the job reads a secret"
EXPR="$(grep -F '${{' <<<"$JOB" | grep -vE '^ +[A-Z_]+: \$\{\{ github\.[a-z_.]+ \}\}$')"
[ -z "$EXPR" ] && ok "event values reach the script as environment only" || bad "an expression outside env: $EXPR"
# Two logics (R-0174): the base's review.sh, from a worktree of the base, then this
# change's — both on a span that names $SHA, since HEAD in the worktree is the base.
grep -qx ' *guard "$base_sh"' <<<"$JOB" && grep -qF 'git worktree add --quiet --detach "$RUNNER_TEMP/base" "$base"' <<<"$JOB" \
  && grep -qF 'range="$base...$SHA"' <<<"$JOB" && grep -qF '::error::the base' <<<"$JOB" \
  && ok "it reads with the base's review.sh (a worktree, \$SHA in the span) and fails closed without one" \
  || bad "no base-logic step: $JOB"
# A push run reads before..sha and nothing else does: it is never cancelled, and a
# group per commit keeps a later push from pushing it out while pending (R-0174).
CONC="$(awk '/^concurrency:$/ { f = 1; next } f && /^  / { print; next } f { exit }' "$CI")"
[ "$CONC" = "  group: \${{ github.event_name == 'push' && format('ci-push-{0}', github.sha) || format('ci-{0}', github.ref) }}
  cancel-in-progress: \${{ github.event_name == 'pull_request' }}" ] \
  && ok "a push to main runs in a group of its own and is never cancelled; pull requests still are" \
  || bad "workflow concurrency: $CONC"
# The job's script itself, run here as GitHub runs it (bash -e): a pull request with
# a finding is red, a push without a usable 'before' is red, not a scan of nothing.
JOBSH="$(awk '/^        run: \|$/ { f = 1; next } f && /^ {10}/ { print substr($0, 11); next } f { exit }' <<<"$JOB")"
[ -n "$JOBSH" ] || bad "no run script found in the job"
job() {  # job <repo> <VAR=value…> — the job's script with a fresh RUNNER_TEMP
  local repo="$1" tmp
  shift
  tmp="$(mktemp -d -p "$WORK")"
  OUT=$(cd "$repo" && env RUNNER_TEMP="$tmp" "$@" bash -e -c "$JOBSH" 2>&1); rc=$?
}
job "$RFIX" EVENT=pull_request BASE_REF=main BEFORE='' SHA="$(rg rev-parse HEAD)"
[ $rc -eq 4 ] && grep -q "tasks/private/m.md (merge " <<<"$OUT" && grep -q "── base logic (origin/main)" <<<"$OUT" \
  && ok "the job's script: a pull request that brings a private file is red" || bad "job pr: rc=$rc out=$OUT"
job "$RFIX" EVENT=push BASE_REF='' BEFORE=0000000000000000000000000000000000000000 SHA="$(rg rev-parse HEAD)"
[ $rc -ne 0 ] && grep -q "without a usable 'before'" <<<"$OUT" \
  && ok "the job's script: a push with an all-zero 'before' fails closed" || bad "job push zero: rc=$rc out=$OUT"
job "$RFIX" EVENT=push BASE_REF='' BEFORE="$RCLEAN" SHA="$(rg rev-parse feature)"
[ $rc -eq 4 ] && grep -q "docs/main.md" <<<"$OUT" && grep -q "── base logic ($RCLEAN)" <<<"$OUT" \
  && ok "the job's script: a push is read from 'before' to the pushed commit, with the logic before it" || bad "job push: rc=$rc out=$OUT"
# A dispatch on main: origin/main...origin/main holds no commit — a notice from each
# logic, not "clean" (R-0174).
job "$RFIX" EVENT=workflow_dispatch BASE_REF='' BEFORE='' SHA="$(rg rev-parse origin/main)"
[ $rc -eq 0 ] && [ "$(grep -c '^::notice::sec: empty span (origin/main\.\.\.[0-9a-f]*) — nothing read$' <<<"$OUT")" = 2 ] \
  && ! grep -q "sec: clean" <<<"$OUT" \
  && ok "the job's script: an empty span is a notice from both logics, not 'clean'" || bad "job empty: rc=$rc out=$OUT"
# A pull request that takes the block out of its own review.sh and adds a private
# file: its own logic passes it, the base's does not — and the base's decides.
EFIX="$WORK/evil"; mkdir -p "$EFIX/scripts/dev"
cp "$REPO_ROOT/scripts/dev/review.sh" "$EFIX/scripts/dev/review.sh"; printf 'tasks/private/\n' > "$EFIX/.gitignore"
eg() { git -C "$EFIX" -c user.name=Fixture -c user.email=t@example.invalid "$@"; }
eg init -q -b main; eg add -A; eg commit -qm base; eg update-ref refs/remotes/origin/main HEAD
sed -i 's#tasks/private/\*|##' "$EFIX/scripts/dev/review.sh"
mkdir -p "$EFIX/tasks/private"; printf 'internal\n' > "$EFIX/tasks/private/x.md"
eg add -A; eg add -f -- tasks/private/x.md; eg commit -qm "loosen sec and bring a private file"
OUT=$(bash "$EFIX/scripts/dev/review.sh" sec --range "origin/main...HEAD" 2>&1); rc=$?
[ $rc -eq 0 ] && ok "fixture: the pull request's own logic lets the private file pass" || bad "fixture own logic: rc=$rc out=$OUT"
job "$EFIX" EVENT=pull_request BASE_REF=main BEFORE='' SHA="$(eg rev-parse HEAD)"
[ $rc -eq 4 ] && grep -q "── base logic" <<<"$OUT" && grep -q "tasks/private/x.md (commit " <<<"$OUT" \
  && ok "the job: the base's logic refuses what the change loosened its own for" || bad "job evil pr: rc=$rc out=$OUT"
# A base whose review.sh cannot read a range is no gate: fail closed.
OFIX="$WORK/oldbase"; mkdir -p "$OFIX/scripts/dev"; printf '#!/bin/sh\necho old\n' > "$OFIX/scripts/dev/review.sh"
og() { git -C "$OFIX" -c user.name=Fixture -c user.email=t@example.invalid "$@"; }
og init -q -b main; og add -A; og commit -qm base; og update-ref refs/remotes/origin/main HEAD
cp "$REPO_ROOT/scripts/dev/review.sh" "$OFIX/scripts/dev/review.sh"; og add -A; og commit -qm "a review.sh that can"
job "$OFIX" EVENT=pull_request BASE_REF=main BEFORE='' SHA="$(og rev-parse HEAD)"
[ $rc -eq 1 ] && grep -q "::error::the base (origin/main) has no review.sh that reads a range" <<<"$OUT" \
  && ok "the job: a base without sec --range fails closed" || bad "job old base: rc=$rc out=$OUT"

# ══ the pre-push hook (R-0123) ════════════════════════════════════════════════
echo "── pre-push hook ──"
# The push is the step from which on it is public. A fixture with the pre-push hook
# alone (the commit hooks would stop the private commits these cases need) and a
# bare repository as its remote.
PFIX="$WORK/pushing"; PREMOTE="$WORK/remote.git"
mkdir -p "$PFIX/scripts/dev/hooks" "$PFIX/tasks/private" "$PFIX/docs"
cp "$REPO_ROOT/scripts/dev/review.sh" "$PFIX/scripts/dev/review.sh"
cp "$REPO_ROOT/scripts/dev/hooks/pre-push" "$PFIX/scripts/dev/hooks/pre-push"
chmod 755 "$PFIX/scripts/dev/hooks/pre-push"
printf 'tasks/private/\n' > "$PFIX/.gitignore"; printf 'plain\n' > "$PFIX/docs/note.md"
pg() { git -C "$PFIX" -c user.name=Fixture -c user.email=t@example.invalid "$@"; }
pp() { OUT=$(cd "$PFIX" && git push -q "$@" 2>&1); rc=$?; }
rhead() { git -C "$PREMOTE" rev-parse -q --verify "refs/heads/$1" || echo none; }
pg init -q -b main; pg add -A; pg commit -qm fixture
git init -q --bare -b main "$PREMOTE"; pg remote add origin "$PREMOTE"
pg config core.hooksPath scripts/dev/hooks
pp origin main
[ $rc -eq 0 ] && [ "$(rhead main)" = "$(pg rev-parse main)" ] \
  && ok "a clean new branch is pushed" || bad "clean push: rc=$rc out=$OUT"
R0="$(rhead main)"
printf 'internal\n' > "$PFIX/tasks/private/x.md"; pg add -f -- tasks/private/x.md; pg commit -qm private
pp origin main
[ $rc -ne 0 ] && [ "$(rhead main)" = "$R0" ] && grep -q "tasks/private/x.md (commit " <<<"$OUT" \
  && grep -q "pre-push: refs/heads/main -> origin refs/heads/main refused" <<<"$OUT" \
  && ok "a private file: the push is refused, the remote unchanged, the path named" || bad "private push: rc=$rc out=$OUT"
pg rm -q -- tasks/private/x.md; pg commit -qm "gone again"
pp origin main
[ $rc -ne 0 ] && [ "$(rhead main)" = "$R0" ] && grep -q "tasks/private/x.md" <<<"$OUT" \
  && ok "added and removed again before the push: still refused" || bad "net-zero push: rc=$rc out=$OUT"
printf 'x\nDedup-%s: sec:%s\n' Key "server:leak.py:probe" >> "$PFIX/docs/note.md"; pg commit -qam key
pp origin main
[ $rc -ne 0 ] && grep -q "docs/note.md:3 (commit " <<<"$OUT" && ! grep -q "leak.py" <<<"$OUT" \
  && ok "a finding's key: refused with file:line, never the line" || bad "key push: rc=$rc out=$OUT"
pg reset -q --hard "$R0"
# main on the remote carries a key line already (pushed from a clone without the
# hook); a branch that merges it brings no finding of its own.
OTHER="$WORK/other"; git clone -q --no-local "$PREMOTE" "$OTHER"
printf 'Dedup-%s: sec:%s\n' Key "old:main.md:line" > "$OTHER/docs/main.md"
git -C "$OTHER" add -A; git -C "$OTHER" -c user.name=O -c user.email=o@example.invalid commit -qm "main has a key line"
git -C "$OTHER" push -q origin main
pg checkout -q -b feature; printf 'feature\n' > "$PFIX/docs/f.md"; pg add -A; pg commit -qm feature
pg fetch -q origin; pg merge -q --no-edit origin/main
pg cat-file -e HEAD:docs/main.md 2>/dev/null || bad "fixture: main's key line did not reach the branch"
pp origin feature
[ $rc -eq 0 ] && [ "$(rhead feature)" = "$(pg rev-parse feature)" ] \
  && ok "a branch that merged main is pushed: main's commits are the remote's already" || bad "merge push: rc=$rc out=$OUT"
pg tag -a -m release v0.0.1
pp origin v0.0.1
[ $rc -eq 0 ] && git -C "$PREMOTE" rev-parse -q --verify refs/tags/v0.0.1 >/dev/null \
  && ok "an annotated tag on clean commits is pushed" || bad "tag push: rc=$rc out=$OUT"
pp origin --delete feature
[ $rc -eq 0 ] && [ "$(rhead feature)" = none ] && ok "a deletion is pushed" || bad "delete push: rc=$rc out=$OUT"
# A remote never fetched: nothing is known to be there, the whole history is read —
# and the hook says why.
git init -q --bare -b main "$WORK/mirror.git"; pg remote add mirror "$WORK/mirror.git"
pp mirror main
[ $rc -eq 0 ] && grep -q "pre-push: no tracking refs for 'mirror'" <<<"$OUT" \
  && ok "a push to a remote without tracking refs says the whole history is read" || bad "mirror push: rc=$rc out=$OUT"

# ══ the pre-commit hook ═══════════════════════════════════════════════════════
echo "── pre-commit hook ──"
# R-0102: sec ran only inside task-close.sh, so the plan commit at the gate and
# every commit by hand were unchecked. A fixture of its own: the hook is armed
# per clone, and the cases above must keep committing without it.
HFIX="$WORK/hooked"
mkdir -p "$HFIX/scripts/dev/hooks" "$HFIX/tasks" "$HFIX/docs"
cp "$REPO_ROOT/scripts/dev/review.sh" "$HFIX/scripts/dev/review.sh"
for h in pre-commit prepare-commit-msg commit-msg pre-merge-commit pre-applypatch; do
  cp "$REPO_ROOT/scripts/dev/hooks/$h" "$HFIX/scripts/dev/hooks/$h"
  chmod 755 "$HFIX/scripts/dev/hooks/$h"
done
printf 'plain\n' > "$HFIX/docs/note.md"
# Tracked before the hook was armed, so `commit -a` has a blocked path to carry.
printf '# sec\n' > "$HFIX/tasks/sec-old.md"
# Likewise a token, so that commit -v below has a diff that removes one (R-0213).
printf 'old %s\n' "$T_GH" > "$HFIX/docs/old-token.md"
git -C "$HFIX" init -q
git -C "$HFIX" config user.email test@example.invalid
git -C "$HFIX" config user.name "Fixture"
git -C "$HFIX" add -A
git -C "$HFIX" commit -qm "fixture"
hc() { OUT=$(cd "$HFIX" && git commit -q "$@" 2>&1); rc=$?; }
heads() { git -C "$HFIX" rev-list --count HEAD; }

# Without the hook — the state R-0102 found — the sec ledger goes through.
printf 'finding\n' > "$HFIX/tasks/sec-x.md"; git -C "$HFIX" add -- tasks/sec-x.md
hc -m "unhooked"
[ $rc -eq 0 ] && ok "without core.hooksPath a sec ledger is committed (the gap)" || bad "unhooked: rc=$rc out=$OUT"
git -C "$HFIX" reset -q --hard HEAD^

git -C "$HFIX" config core.hooksPath scripts/dev/hooks
H0=$(heads)
printf 'finding\n' > "$HFIX/tasks/sec-x.md"; git -C "$HFIX" add -- tasks/sec-x.md
hc -m "a sec ledger"
[ $rc -ne 0 ] && [ "$(heads)" = "$H0" ] && grep -q 'tasks/sec-x.md' <<<"$OUT" \
  && ok "armed: a blocked path in the index is refused" || bad "index path: rc=$rc out=$OUT"
git -C "$HFIX" rm -q --cached -- tasks/sec-x.md; rm -f "$HFIX/tasks/sec-x.md"
# The key is assembled at run time: written out, it would stop this very file at sec.
printf 'x\nDedup-Key: %s\n' "sec:server:a.py:f" > "$HFIX/docs/leak.md"; git -C "$HFIX" add -- docs/leak.md
hc -m "a finding's key"
[ $rc -ne 0 ] && [ "$(heads)" = "$H0" ] && grep -q 'Dedup-Key' <<<"$OUT" \
  && ok "armed: a sec dedup key in the index is refused" || bad "index key: rc=$rc out=$OUT"
git -C "$HFIX" rm -q --cached -- docs/leak.md; rm -f "$HFIX/docs/leak.md"
# commit -a stages into a temporary index that git hands the hook through
# GIT_INDEX_FILE; a hook that read the real index would see nothing staged.
printf 'more\n' >> "$HFIX/tasks/sec-old.md"
hc -a -m "commit -a, blocked path"
[ $rc -ne 0 ] && [ "$(heads)" = "$H0" ] && grep -q 'tasks/sec-old.md' <<<"$OUT" \
  && ok "armed: commit -a with a blocked path is refused" || bad "commit -a path: rc=$rc out=$OUT"
git -C "$HFIX" checkout -q -- tasks/sec-old.md
printf 'Dedup-Key: %s\n' "sec:server:b.py:g" >> "$HFIX/docs/note.md"
hc -a -m "commit -a, key"
[ $rc -ne 0 ] && [ "$(heads)" = "$H0" ] && grep -q 'Dedup-Key' <<<"$OUT" \
  && ok "armed: commit -a with a sec dedup key is refused" || bad "commit -a key: rc=$rc out=$OUT"
git -C "$HFIX" checkout -q -- docs/note.md
printf 'clean line\n' >> "$HFIX/docs/note.md"
hc -a -m "a clean change"
[ $rc -eq 0 ] && [ "$(heads)" = "$((H0 + 1))" ] && ok "armed: a clean change is committed" || bad "clean: rc=$rc out=$OUT"
# commit-msg (R-0197): a token in the message stops the commit itself, not only the
# push. The merge commits further down pass this hook with git's own message.
H0=$(heads)
hc --allow-empty -m "subject $T_GH"
[ $rc -ne 0 ] && [ "$(heads)" = "$H0" ] && grep -q "the commit message:1 (a token pattern)" <<<"$OUT" \
  && ! grep -qF "$T_GH" <<<"$OUT" && ok "armed: a token in -m is refused, never echoed" || bad "msg token: rc=$rc out=$OUT"
hc --allow-empty -m "subject with gh""p_short only"
[ $rc -eq 0 ] && [ "$(heads)" = "$((H0 + 1))" ] && ok "armed: a placeholder in -m is committed" || bad "msg placeholder: rc=$rc out=$OUT"
# R-0213: a scissors line typed into -m or -F hides nothing; git keeps what follows
# it. git runs the hook with GIT_EDITOR=: there, even when the caller set an editor.
CUT='# ------------------------ >8 ------------------------'
H0=$(heads)
hc --allow-empty -m "subject"$'\n\n'"$CUT"$'\n'"below $T_GH"
[ $rc -ne 0 ] && [ "$(heads)" = "$H0" ] && grep -q "the commit message:4 (a token pattern)" <<<"$OUT" \
  && ok "armed: a token below a scissors line typed into -m is refused (R-0213)" || bad "msg scissors -m: rc=$rc out=$OUT"
printf 'subject\n\n%s\nbelow %s\n' "$CUT" "$T_GH" > "$WORK/scissors-msg.txt"
hc --allow-empty -F "$WORK/scissors-msg.txt"
[ $rc -ne 0 ] && [ "$(heads)" = "$H0" ] && grep -q "the commit message:4 (a token pattern)" <<<"$OUT" \
  && ok "armed: ... and in -F" || bad "msg scissors -F: rc=$rc out=$OUT"
rm -f -- "$WORK/scissors-msg.txt"
# An editor that keeps the template git wrote and types a subject above it.
printf '#!/bin/sh\n{ echo "typed subject"; cat "$1"; } > "$1.new" && mv "$1.new" "$1"\n' > "$WORK/ed-keep.sh"
chmod 755 "$WORK/ed-keep.sh"
GIT_EDITOR="$WORK/ed-keep.sh" hc --allow-empty -m "subject"$'\n\n'"$CUT"$'\n'"below $T_GH"
[ $rc -ne 0 ] && [ "$(heads)" = "$H0" ] && grep -q "the commit message:4 (a token pattern)" <<<"$OUT" \
  && ok "armed: ... and in -m with GIT_EDITOR set (git hands the hook GIT_EDITOR=:)" || bad "msg scissors -m editor set: rc=$rc out=$OUT"
# The same with a diff header typed below the line: without an editor the hook
# says nothing of one, so review.sh reads on.
TYPED="subject"$'\n\n'"$CUT"$'\n'"diff --git a/f b/f"$'\n'"+below $T_GH"
hc --allow-empty -m "$TYPED"
[ $rc -ne 0 ] && [ "$(heads)" = "$H0" ] && grep -q "the commit message:5 (a token pattern)" <<<"$OUT" \
  && ok "armed: a diff header typed below the scissors line in -m hides nothing" || bad "msg typed diff -m: rc=$rc out=$OUT"
printf '%s\n' "$TYPED" > "$WORK/typed-diff-msg.txt"
hc --allow-empty -F "$WORK/typed-diff-msg.txt"
[ $rc -ne 0 ] && [ "$(heads)" = "$H0" ] && grep -q "the commit message:5 (a token pattern)" <<<"$OUT" \
  && ok "armed: ... nor in -F" || bad "msg typed diff -F: rc=$rc out=$OUT"
rm -f -- "$WORK/typed-diff-msg.txt"
GIT_EDITOR="$WORK/ed-keep.sh" hc --allow-empty -m "$TYPED"
[ $rc -ne 0 ] && [ "$(heads)" = "$H0" ] && grep -q "the commit message:5 (a token pattern)" <<<"$OUT" \
  && ok "armed: ... nor in -m with GIT_EDITOR set" || bad "msg typed diff -m editor set: rc=$rc out=$OUT"
# commit -v with an editor: git puts the diff below its scissors line and drops it,
# so a diff that removes a token line commits.
printf 'clean\n' > "$HFIX/docs/old-token.md"; git -C "$HFIX" add -- docs/old-token.md
GIT_EDITOR="$WORK/ed-keep.sh" hc -v
[ $rc -eq 0 ] && [ "$(heads)" = "$((H0 + 1))" ] && [ "$(git -C "$HFIX" log -1 --format=%s)" = "typed subject" ] \
  && ok "armed: commit -v with an editor, whose diff removes a token line, is committed" || bad "msg commit -v: rc=$rc out=$OUT"
rm -f -- "$WORK/ed-keep.sh"

# The relative core.hooksPath is resolved per worktree: a lane runs the hook of
# ITS branch. Here that branch carries a hook that only leaves a marker behind.
git -C "$HFIX" switch -q -c other
printf '#!/bin/sh\necho other > hook-ran.txt\n' > "$HFIX/scripts/dev/hooks/pre-commit"
# Committed without hooks: the armed hook of this checkout is already the
# marker one, and its marker here would spoil the check below.
git -C "$HFIX" -c core.hooksPath=/dev/null commit -qam "other hook" >/dev/null 2>&1
git -C "$HFIX" switch -q -
git -C "$HFIX" worktree add -q "$WORK/hooked-wt" other 2>/dev/null
printf 'x\n' >> "$WORK/hooked-wt/docs/note.md"
( cd "$WORK/hooked-wt" && git commit -qam "in the worktree" >/dev/null 2>&1 )
[ -f "$WORK/hooked-wt/hook-ran.txt" ] && [ ! -f "$HFIX/hook-ran.txt" ] \
  && ok "a worktree runs the hook of its own branch" || bad "worktree hook: $(ls "$WORK/hooked-wt" "$HFIX")"

# R-0110: cherry-pick, revert, rebase and a merge commit never run pre-commit.
# prepare-commit-msg runs for all of them — for the sequencer undocumented,
# measured on git 2.47.3 — and pre-merge-commit for a merge; both run the same
# check. A git that stops calling them there turns these cases red.
MAIN=$(git -C "$HFIX" branch --show-current)
git -C "$HFIX" switch -q -c side
printf 'finding\n' > "$HFIX/tasks/sec-side.md"; git -C "$HFIX" add -- tasks/sec-side.md
git -C "$HFIX" -c core.hooksPath=/dev/null commit -qm "side" >/dev/null 2>&1
git -C "$HFIX" switch -q "$MAIN"
H1=$(heads)
OUT=$(git -C "$HFIX" cherry-pick side 2>&1); rc=$?
[ $rc -ne 0 ] && [ "$(heads)" = "$H1" ] && grep -q 'tasks/sec-side.md' <<<"$OUT" \
  && ok "cherry-pick of a sec ledger is refused, HEAD stays" || bad "cherry-pick: rc=$rc heads=$(heads) out=$OUT"
git -C "$HFIX" cherry-pick --abort >/dev/null 2>&1
OUT=$(git -C "$HFIX" merge --no-ff --no-edit side 2>&1); rc=$?
[ $rc -ne 0 ] && [ "$(heads)" = "$H1" ] && grep -q 'tasks/sec-side.md' <<<"$OUT" \
  && ok "a merge commit that brings a sec ledger is refused, no merge commit" || bad "merge: rc=$rc heads=$(heads) out=$OUT"
git -C "$HFIX" merge --abort >/dev/null 2>&1
[ ! -e "$HFIX/tasks/sec-side.md" ] && [ -z "$(git -C "$HFIX" status --porcelain)" ] \
  && ok "... and both leave nothing behind after --abort" || bad "left behind: $(git -C "$HFIX" status --porcelain)"
# pre-merge-commit on its own: with prepare-commit-msg not executable, the merge
# is still refused — the documented hook carries it.
chmod 644 "$HFIX/scripts/dev/hooks/prepare-commit-msg"
OUT=$(git -C "$HFIX" merge --no-ff --no-edit side 2>&1); rc=$?
[ $rc -ne 0 ] && [ "$(heads)" = "$H1" ] && grep -q 'tasks/sec-side.md' <<<"$OUT" \
  && ok "pre-merge-commit alone refuses the merge commit" || bad "pre-merge-commit alone: rc=$rc heads=$(heads) out=$OUT"
git -C "$HFIX" merge --abort >/dev/null 2>&1
chmod 755 "$HFIX/scripts/dev/hooks/prepare-commit-msg"
# What is clean still goes through, as a cherry-pick and as a merge commit.
for b in pick-clean merge-clean; do
  git -C "$HFIX" switch -q -c "$b" "$MAIN"
  printf '%s\n' "$b" > "$HFIX/docs/$b.md"; git -C "$HFIX" add -- "docs/$b.md"
  git -C "$HFIX" commit -qm "$b" >/dev/null 2>&1
  git -C "$HFIX" switch -q "$MAIN"
done
OUT=$(git -C "$HFIX" cherry-pick pick-clean 2>&1); rc=$?
[ $rc -eq 0 ] && [ "$(heads)" = "$((H1 + 1))" ] && ok "a clean cherry-pick goes through" || bad "clean cherry-pick: rc=$rc out=$OUT"
OUT=$(git -C "$HFIX" merge --no-ff --no-edit merge-clean 2>&1); rc=$?
[ $rc -eq 0 ] && [ -n "$(git -C "$HFIX" rev-parse -q --verify HEAD^2)" ] \
  && ok "a clean merge commit goes through" || bad "clean merge: rc=$rc out=$OUT"
# Rebasing side onto the moved main replays the sec commit: the rebase stops.
SIDE=$(git -C "$HFIX" rev-parse side)
OUT=$(git -C "$HFIX" rebase "$MAIN" side 2>&1); rc=$?
[ $rc -ne 0 ] && grep -q 'tasks/sec-side.md' <<<"$OUT" \
  && ok "a rebase over a sec commit stops with the sec message" || bad "rebase: rc=$rc out=$OUT"
git -C "$HFIX" rebase --abort >/dev/null 2>&1
[ "$(git -C "$HFIX" rev-parse side)" = "$SIDE" ] && ok "... and side is untouched after --abort" || bad "rebase moved side"
git -C "$HFIX" switch -q "$MAIN"
# A revert whose commit touches a sec path: the same refusal.
printf 'finding\n' > "$HFIX/tasks/sec-rev.md"; git -C "$HFIX" add -- tasks/sec-rev.md
git -C "$HFIX" -c core.hooksPath=/dev/null commit -qm "sec on main" >/dev/null 2>&1
H2=$(heads)
OUT=$(git -C "$HFIX" revert --no-edit HEAD 2>&1); rc=$?
[ $rc -ne 0 ] && [ "$(heads)" = "$H2" ] && grep -q 'tasks/sec-rev.md' <<<"$OUT" \
  && ok "a revert that touches a sec ledger is refused, HEAD stays" || bad "revert: rc=$rc heads=$(heads) out=$OUT"
# A refused revert of one commit leaves its change staged and writes no
# REVERT_HEAD, so --abort has nothing to abort (git 2.47.3); DEVELOPMENT.md
# names reset --merge as the way back, and this holds it.
git -C "$HFIX" reset -q --merge
[ -z "$(git -C "$HFIX" status --porcelain)" ] && [ -f "$HFIX/tasks/sec-rev.md" ] \
  && ok "... and git reset --merge takes the refused revert back" || bad "reset --merge: $(git -C "$HFIX" status --porcelain)"
# git am and rebase --apply run none of those hooks, only the applypatch ones:
# pre-applypatch runs after the patch is applied, before the commit (T7).
git -C "$HFIX" format-patch -1 --stdout side > "$WORK/side.patch" 2>/dev/null
H3=$(heads)
OUT=$(git -C "$HFIX" am "$WORK/side.patch" 2>&1); rc=$?
[ $rc -ne 0 ] && [ "$(heads)" = "$H3" ] && grep -q 'tasks/sec-side.md' <<<"$OUT" \
  && ok "git am of a sec ledger is refused, HEAD stays" || bad "git am: rc=$rc heads=$(heads) out=$OUT"
git -C "$HFIX" am --abort >/dev/null 2>&1
[ ! -e "$HFIX/tasks/sec-side.md" ] && [ -z "$(git -C "$HFIX" status --porcelain)" ] \
  && ok "... and git am --abort leaves nothing behind" || bad "am left behind: $(git -C "$HFIX" status --porcelain)"
git -C "$HFIX" switch -q -c am-clean "$MAIN"
printf 'am\n' > "$HFIX/docs/am-clean.md"; git -C "$HFIX" add -- docs/am-clean.md
git -C "$HFIX" commit -qm "am-clean" >/dev/null 2>&1
git -C "$HFIX" format-patch -1 --stdout am-clean > "$WORK/clean.patch" 2>/dev/null
git -C "$HFIX" switch -q "$MAIN"
OUT=$(git -C "$HFIX" am "$WORK/clean.patch" 2>&1); rc=$?
[ $rc -eq 0 ] && [ "$(heads)" = "$((H3 + 1))" ] && ok "a clean git am goes through" || bad "clean am: rc=$rc out=$OUT"
SIDE=$(git -C "$HFIX" rev-parse side)
OUT=$(git -C "$HFIX" rebase --apply "$MAIN" side 2>&1); rc=$?
[ $rc -ne 0 ] && grep -q 'tasks/sec-side.md' <<<"$OUT" \
  && ok "a rebase --apply over a sec commit stops with the sec message" || bad "rebase --apply: rc=$rc out=$OUT"
git -C "$HFIX" rebase --abort >/dev/null 2>&1
[ "$(git -C "$HFIX" rev-parse side)" = "$SIDE" ] && ok "... and side is untouched after --abort" || bad "rebase --apply moved side"
git -C "$HFIX" switch -q "$MAIN"

# The files themselves: git ignores a hook without the execute bit, and the
# lint step of run.sh only covers *.sh.
# A tree without a working .git (a box's synced worktree, a tarball) cannot say
# what git recorded; there the bit on disk is what git would run.
# --show-toplevel, not --git-dir: a tarball unpacked inside another repository
# would find that one.
HOOK_SKIPPED=0
for h in pre-commit prepare-commit-msg commit-msg pre-merge-commit pre-applypatch; do
  if [ "$(git -C "$REPO_ROOT" rev-parse --show-toplevel 2>/dev/null)" = "$(cd "$REPO_ROOT" && pwd -P)" ]; then
    mode=$(git -C "$REPO_ROOT" ls-files -s -- "scripts/dev/hooks/$h" | cut -d' ' -f1)
    [ "$mode" = 100755 ] && ok "$h is tracked with mode 100755" || bad "$h mode: '${mode:-untracked}'"
  else
    [ -x "$REPO_ROOT/scripts/dev/hooks/$h" ] \
      && ok "$h is executable (no git here to read the recorded mode)" || bad "$h is not executable"
  fi
  if command -v shellcheck >/dev/null 2>&1; then
    shellcheck --severity=warning "$REPO_ROOT/scripts/dev/hooks/$h" \
      && ok "shellcheck: $h is clean" || bad "shellcheck findings in $h"
  else
    echo "  SKIP: shellcheck not available — $h is not linted"
    HOOK_SKIPPED=1
  fi
done

# ══ risk (stage 6a) ═══════════════════════════════════════════════════════════
echo "── risk ──"
# The real list, committed into the fixture: risk reads it from HEAD as well, so
# a diff cannot strike its own line out of it.
cp "$REPO_ROOT/scripts/dev/review-risk.txt" "$FIX/scripts/dev/review-risk.txt"
git -C "$FIX" add scripts/dev/review-risk.txt && git -C "$FIX" commit -qm "risk list"
rreset() { reset_index; }
# put <path>… — a changed file at each path, staged.
put() { local f; for f in "$@"; do mkdir -p "$(dirname "$FIX/$f")"; echo "x $RANDOM" >> "$FIX/$f"; stage "$f"; done; }
rreset; put apps/monitoring/app/alerter.py; r risk --staged
[ $rc -eq 0 ] && [ "$(head -1 <<<"$OUT")" = xhigh ] && grep -qx '  apps/monitoring/app/alerter.py' <<<"$OUT" \
  && ok "alerter.py -> xhigh, the path named" || bad "alerter: rc=$rc out=$OUT"
rreset; put docs/admin/benutzer.html; r risk --staged
[ $rc -eq 0 ] && [ "$OUT" = standard ] && ok "a docs page alone -> standard" || bad "docs: rc=$rc out=$OUT"
rreset; put scripts/dev/task-close.sh; r risk --staged
[ $rc -eq 0 ] && [ "$(head -1 <<<"$OUT")" = xhigh ] && grep -qx '  scripts/dev/task-close.sh' <<<"$OUT" \
  && ok "a harness path -> xhigh (the list's harness section counts)" || bad "harness path: rc=$rc out=$OUT"
rreset; put "docs/a b.html" apps/server/alembic/versions/0042_x.py; r risk --staged
[ $rc -eq 0 ] && [ "$(head -1 <<<"$OUT")" = xhigh ] && grep -qx '  apps/server/alembic/versions/0042_x.py' <<<"$OUT" \
  && ! grep -q 'a b' <<<"$OUT" && ok "a path with a space breaks nothing" || bad "space: rc=$rc out=$OUT"
rreset; put "docs/a b.html"; r risk --staged
[ $rc -eq 0 ] && [ "$OUT" = standard ] && ok "a path with a space alone -> standard" || bad "space alone: rc=$rc out=$OUT"
rreset; put apps/agent/internal/httpclient/httpclient.go; r risk --staged
[ $rc -eq 0 ] && grep -qx '  apps/agent/internal/httpclient/httpclient.go' <<<"$OUT" \
  && ok "the agent's cert pinning is a risk path" || bad "httpclient: rc=$rc out=$OUT"
rreset; echo 'apps/agent/internal/newdir/' >> "$FIX/scripts/dev/review-risk.txt"; put apps/agent/internal/newdir/x.go
r risk --staged
[ $rc -eq 0 ] && grep -qx '  apps/agent/internal/newdir/x.go' <<<"$OUT" \
  && ok "an entry ending in / is a directory prefix" || bad "dir entry: rc=$rc out=$OUT"
rreset; put apps/server/app/modules/hosts/schemas.py apps/server/app/modules/hosts/router.py; r risk --staged
[ $rc -eq 0 ] && [ "$(sed -n '2,$p' <<<"$OUT")" = '  apps/server/app/modules/hosts/schemas.py' ] \
  && ok "only the risky one of two paths is named" || bad "two paths: rc=$rc out=$OUT"
# Without a flag, risk sees everything not committed yet: staged, unstaged and
# untracked — at the review step nothing is staged, and a new migration is a
# risk path before anyone stages it. --staged sees the index alone.
rreset; put apps/monitoring/app/alerter.py; r risk
[ $rc -eq 0 ] && [ "$(head -1 <<<"$OUT")" = xhigh ] && grep -qx '  apps/monitoring/app/alerter.py' <<<"$OUT" \
  && ok "without a flag a staged risk path counts" \
  || bad "staged, no flag: rc=$rc out=$OUT"
rreset; mkdir -p "$FIX/apps/server/alembic/versions"; echo "rev" > "$FIX/apps/server/alembic/versions/0099_new.py"
r risk
[ $rc -eq 0 ] && [ "$(head -1 <<<"$OUT")" = xhigh ] && grep -qx '  apps/server/alembic/versions/0099_new.py' <<<"$OUT" \
  && ok "without a flag an untracked file under a risk path -> xhigh" || bad "untracked: rc=$rc out=$OUT"
r risk --staged
[ $rc -eq 0 ] && [ "$OUT" = standard ] && ok "--staged does not see the untracked file" || bad "untracked staged: rc=$rc out=$OUT"
rreset; put apps/monitoring/app/alerter.py; git -C "$FIX" commit -qm "alerter" >/dev/null
echo "edit" >> "$FIX/apps/monitoring/app/alerter.py"; r risk
[ $rc -eq 0 ] && [ "$(head -1 <<<"$OUT")" = xhigh ] && grep -qx '  apps/monitoring/app/alerter.py' <<<"$OUT" \
  && ok "without a flag an unstaged edit of a tracked risk file -> xhigh" || bad "unstaged edit: rc=$rc out=$OUT"
r risk --staged
[ $rc -eq 0 ] && [ "$OUT" = standard ] && ok "--staged does not see the unstaged edit" || bad "unstaged staged: rc=$rc out=$OUT"
git -C "$FIX" reset -q --hard HEAD~1
# A move out of a risk path counts by where it came from.
rreset; put apps/server/app/core/auth.py; git -C "$FIX" commit -qm "auth" >/dev/null
mkdir -p "$FIX/apps/server/app/hosts"
git -C "$FIX" mv apps/server/app/core/auth.py apps/server/app/hosts/login.py
echo "edit" >> "$FIX/apps/server/app/hosts/login.py"; stage apps/server/app/hosts/login.py
r risk --staged
[ $rc -eq 0 ] && [ "$(head -1 <<<"$OUT")" = xhigh ] && grep -qx '  apps/server/app/core/auth.py' <<<"$OUT" \
  && ok "a move out of a risk path -> xhigh, the old path named" || bad "rename: rc=$rc out=$OUT"
git -C "$FIX" reset -q --hard HEAD~1
# The list is judged as HEAD has it too: a diff that strikes its own line from
# it, or the whole list, does not judge itself by that.
rreset; put scripts/dev/task-close.sh
grep -vxF 'scripts/dev/*' "$FIX/scripts/dev/review-risk.txt" > "$WORK/hp" \
  && cat "$WORK/hp" > "$FIX/scripts/dev/review-risk.txt"; stage scripts/dev/review-risk.txt
r risk --staged
[ $rc -eq 0 ] && grep -qx '  scripts/dev/task-close.sh' <<<"$OUT" \
  && ok "a line struck in the same diff still counts" || bad "struck line: rc=$rc out=$OUT"
rreset; put scripts/dev/task-close.sh; git -C "$FIX" rm -q scripts/dev/review-risk.txt
r risk --staged
[ $rc -eq 0 ] && grep -qx '  scripts/dev/task-close.sh' <<<"$OUT" \
  && ok "the list removed in the same diff still counts" || bad "removed list: rc=$rc out=$OUT"
rreset; put scripts/dev/task-close.sh
grep -vxF 'scripts/dev/*' "$FIX/scripts/dev/review-risk.txt" > "$WORK/hp" \
  && cat "$WORK/hp" > "$FIX/scripts/dev/review-risk.txt"
r risk --staged
[ $rc -eq 0 ] && grep -qx '  scripts/dev/task-close.sh' <<<"$OUT" \
  && ok "an unstaged edit of the list does not take a line away" || bad "unstaged list edit: rc=$rc out=$OUT"
# A name git would quote is still a name.
rreset; put 'apps/server/alembic/versions/0042_"x".py'; r risk --staged
[ $rc -eq 0 ] && grep -qxF '  apps/server/alembic/versions/0042_"x".py' <<<"$OUT" \
  && ok "a name git quotes is matched as it is" || bad "quoted name: rc=$rc out=$OUT"
rreset; put apps/gateway/nginx.conf; git -C "$FIX" commit -qm "gateway" >/dev/null
r risk --range HEAD~1..HEAD
[ $rc -eq 0 ] && [ "$(head -1 <<<"$OUT")" = xhigh ] && ok "--range reads a commit range" || bad "range: rc=$rc out=$OUT"
git -C "$FIX" reset -q --hard HEAD~1
rreset
# A range judges by the list its start had: a commit that strikes its own line
# from review-risk.txt does not read as standard.
rreset; put scripts/dev/task-close.sh
grep -vxF 'scripts/dev/*' "$FIX/scripts/dev/review-risk.txt" > "$WORK/hp" \
  && cat "$WORK/hp" > "$FIX/scripts/dev/review-risk.txt"; stage scripts/dev/review-risk.txt
git -C "$FIX" commit -qm "strike" >/dev/null
r risk --range HEAD~1..HEAD
[ $rc -eq 0 ] && grep -qx '  scripts/dev/task-close.sh' <<<"$OUT" \
  && ok "a range judges by the list of its start" || bad "range list: rc=$rc out=$OUT"
git -C "$FIX" reset -q --hard HEAD~1
rreset
r risk --range HEAD
[ $rc -eq 2 ] && ok "a range without .. -> 2" || bad "range without ..: rc=$rc out=$OUT"
r risk --range nosuch..HEAD
[ $rc -eq 2 ] && ok "a range git cannot read -> 2" || bad "bad range: rc=$rc out=$OUT"
r risk --staged --range HEAD~1..HEAD
[ $rc -eq 2 ] && ok "--staged and --range together -> 2" || bad "staged+range: rc=$rc out=$OUT"
r risk --range --staged
[ $rc -eq 2 ] && ok "a range that is a flag -> 2" || bad "flag as range: rc=$rc out=$OUT"
r risk extra
[ $rc -eq 2 ] && ok "risk takes no operand -> 2" || bad "operand: rc=$rc out=$OUT"
r pr-body --range HEAD~1..HEAD
[ $rc -eq 2 ] && ok "--range belongs to risk and sec -> 2" || bad "range on pr-body: rc=$rc out=$OUT"
# The list in the real repo: every line matches something that exists, so a
# rename cannot quietly drop a risk path out of it.
while IFS= read -r pat; do
  case "$pat" in ''|'#'*) continue ;; esac
  # shellcheck disable=SC2086  # the pattern IS a glob
  compgen -G "$REPO_ROOT/$pat" >/dev/null && ok "risk path exists: $pat" || bad "risk path matches nothing: $pat"
done < "$REPO_ROOT/scripts/dev/review-risk.txt"
grep -qxF 'scripts/dev/*' "$REPO_ROOT/scripts/dev/review-risk.txt" \
  && ok "the risk list holds the harness scripts (and itself)" || bad "scripts/dev/* is missing from review-risk.txt"


# ══ pr-body (stage 6a) ════════════════════════════════════════════════════════
echo "── pr-body ──"
reset_index
cat > "$WORK/pr.md" <<'MD'
# Fixture-Vorhaben — Task-Ledger
Status: bereit · Branch: harness/fixture · Review: pro Task
Spec: docs/features/fixture.md (Roadmap R-0999)
Heavy: none — nur Skripte
### T1 — die erste Aufgabe  [x]
Komponente: scripts · Dateien: scripts/dev/tool.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @abc1234 2026-10-02T10:00:00+02:00 on 192.168.10.20
Review: approve (opus) — probe on pve1.lan, VMID 3012
Änderung: irgendwas
### T2 — die zweite Aufgabe  [x]
Komponente: scripts · Dateien: scripts/dev/tool.sh
Review: approve (sonnet)
### T3 — die dritte Aufgabe  [?] (soll das so bleiben?)
Komponente: scripts · Dateien: scripts/dev/tool.sh
### T4 — die vierte Aufgabe  [~] (schon erledigt in T1)
Komponente: scripts · Dateien: scripts/dev/tool.sh
### T5 — die fünfte Aufgabe  [x]
Komponente: scripts · Dateien: scripts/dev/tool.sh
Evidenz: run.sh[quick] scripts: 7 passed, 0 failed, 11 skipped @def5678 2026-10-02T11:00:00+02:00
Review: approve (opus)
### T6 — die sechste Aufgabe  [x] **verifiziert** (auf der Box)
Evidenz: run.sh[quick] scripts: 9 passed, 0 failed, 0 skipped via fd12:3456:789a::10 and [fe80::1]:22, Template **3901**, pve.home.arpa, nas.fritz.box, net 192.168.1.x and 10.0.0.*, VM-ID 3013, Template 3904 und 3905, net 172.16.x.x.
Review: approve (sonnet) — reads .claude/settings.local.json on 127.0.0.1, IP:10.250.0.12, dns:2001:db8::1, auf box.lan. VMs 3902
### T7 — die siebte Aufgabe
### Ergebnis des Laufs
Evidenz: run.sh[quick] scripts: 99 passed, 0 failed, 0 skipped
MD
r pr-body "$WORK/pr.md"
[ $rc -eq 0 ] && ok "pr-body -> 0" || bad "pr-body: rc=$rc out=$OUT"
grep -q 'docs/features/fixture.md' <<<"$OUT" && grep -q 'R-0999' <<<"$OUT" && grep -qF '**Heavy:** none' <<<"$OUT" \
  && ok "the head: spec, roadmap id, heavy line" || bad "head: $OUT"
grep -q 'T1 — die erste Aufgabe' <<<"$OUT" && grep -q 'run.sh\[quick\] scripts: 6 passed' <<<"$OUT" \
  && ok "a task with its evidence line" || bad "evidence: $OUT"
t2="$(grep 'T2 — ' <<<"$OUT")"
grep -q 'unverifiziert' <<<"$t2" && ! grep -qi 'approve' <<<"$(sed -n '/T2 — /,/T[3-9] — /p' <<<"$OUT")" \
  && ok "a task without evidence reads unverifiziert, never approve" || bad "T2: $OUT"
grep -q 'Review: approve (opus)' <<<"$(sed -n '/T5 — /,/T6 — /p' <<<"$OUT")" \
  && ok "a task's Review: line goes along" || bad "review line: $OUT"
grep -q '^### Offene Fragen' <<<"$OUT" && grep -q 'T3 — die dritte Aufgabe.*soll das so bleiben' <<<"$OUT" \
  && ok "a [?] task stands in its own section, with the question" || bad "[?]: $OUT"
grep -q '^### Übersprungen' <<<"$OUT" && grep -q 'T4 — die vierte Aufgabe.*schon erledigt' <<<"$OUT" \
  && ok "a [~] task stands in its own section, with the reason" || bad "[~]: $OUT"
! grep -qE '192\.168|pve1\.lan|3012|fd12:|fe80|3901|10\.250|2001:db8|box\.lan|3902|home\.arpa|fritz\.box|10\.0\.0|3013|3904|3905|172\.16' <<<"$OUT" \
  && ok "no address (v4, v6 compressed or bracketed, behind a word:), host name (also at a sentence end) or VMID" \
  || bad "leak: $OUT"
grep -qF '.claude/settings.local.json on 127.0.0.1' <<<"$OUT" \
  && ok "a file name with .local and the loopback address stay" || bad "over-scrub: $OUT"
t6="$(sed -n '/T6 — /,/^- /p' <<<"$OUT")"
grep -q '9 passed' <<<"$t6" && ! grep -q '99 passed' <<<"$OUT" && ! grep -q '9 passed' <<<"$(sed -n '/T5 — /,/T6 — /p' <<<"$OUT" | sed '$d')" \
  && ok "every ### heading ends a task: a note after the box is read, a section's lines belong to none" || bad "sections: $OUT"
grep -q 'T7 — die siebte Aufgabe.*unlesbar' <<<"$OUT" && ok "a task heading without a box reads unlesbar" || bad "no box: $OUT"
r pr-body "$WORK/pr.md" --verdicts "$WORK"
[ $rc -eq 2 ] && grep -q 'unknown flag' <<<"$OUT" && ok "--verdicts is gone -> 2" || bad "--verdicts: rc=$rc out=$OUT"
r pr-body "$WORK/nosuch.md"
[ $rc -eq 2 ] && ok "a missing ledger -> 2" || bad "missing ledger: rc=$rc out=$OUT"
r pr-body
[ $rc -eq 2 ] && grep -q 'pr-body needs' <<<"$OUT" && ok "no ledger -> 2" || bad "no ledger: rc=$rc out=$OUT"


# ══ final: the closing check of a branch ══════════════════════════════════════
echo "── final ──"
reset_index
cat > "$FIX/tasks/fin.md" <<'MD'
# Abschluss-Fixture — Task-Ledger
Status: bereit · Branch: feature/fin · Review: pro Task
Spec: docs/features/fin.md (Roadmap R-0998)
### T1 — eins  [x]
Evidenz: run.sh[quick] scripts: 1 passed, 0 failed, 0 skipped
### T2 — zwei  [~] (entfaellt)
MD
fcommit() { git -C "$FIX" add -A -- "$@" && git -C "$FIX" commit --quiet --message "$CMSG"; }
CMSG="plan fin" fcommit tasks/fin.md
# fin_verdict [<python statements on v>] — the reviewer's branch verdict on HEAD.
fin_verdict() {
  mkdir -p "$FIX/.ah-out/review/fin"
  python3 - "$FIX/.ah-out/review/fin/branch.verdict.json" "$(git -C "$FIX" rev-parse HEAD)" "${1-}" <<'PY'
import json, sys
path, head, patch = sys.argv[1:4]
v = {"mode": "branch", "verdict": "approve", "head": head,
     "code": {"verdict": "approve", "checked": ["1", "2", "3", "4", "5", "6", "7"],
              "evidence": ["git diff main... read in full", "bash -n scripts/dev/tool.sh"],
              "findings": [{"severity": "nit", "file": "scripts/dev/tool.sh", "line": 2, "what": "printf over echo"}]},
     "tests": {"verdict": "approve", "coverage": [{"file": "scripts/dev/tool.sh", "tests": ["scripts/tests/tool_test.sh"]}],
               "probes": [{"test": "tests/test_tool.py::test_echo", "result": "red", "evidence": "rc=1 without the fix on 10.0.0.7"}],
               "evidence": ["verify.sh scripts --strict -- tool_test: 1 passed"], "findings": []}}
exec(patch)
json.dump(v, open(path, "w"))
PY
}
fin() { r final "$FIX/tasks/fin.md"; }
fin
[ $rc -eq 3 ] && grep -q 'no branch verdict at .ah-out/review/fin/branch.verdict.json' <<<"$OUT" \
  && ok "no branch verdict -> 3" || bad "none: rc=$rc out=$OUT"
fin_verdict; fin
[ $rc -eq 0 ] && ok "a current approve for code and tests -> 0" || bad "approve: rc=$rc out=$OUT"
grep -q '^### Abschlussprüfung (reviewer, Branch)' <<<"$OUT" && grep -q "geprüft auf \`$(git -C "$FIX" rev-parse --short=8 HEAD)\`" <<<"$OUT" \
  && ok "the PR section names the judged commit" || bad "section: $OUT"
grep -qF -- '- **Code:** approve (Kriterien 1, 2, 3, 4, 5, 6, 7) — Evidenz: git diff main... read in full' <<<"$OUT" \
  && grep -qF -- '- **Tests:** approve — Abdeckung: 1 Dateien — Evidenz: verify.sh scripts' <<<"$OUT" \
  && ok "code and tests each with their evidence" || bad "parts: $OUT"
grep -qF 'Gegenprobe `tests/test_tool.py::test_echo`: rot ohne den Fix' <<<"$OUT" && ! grep -q '10\.0\.0\.7' <<<"$OUT" \
  && ok "the probe, its address cut out" || bad "probe: $OUT"
grep -qF '[code] nit `scripts/dev/tool.sh:2` — printf over echo' <<<"$OUT" && ok "the nits go along" || bad "nits: $OUT"
fin_verdict 'v["tests"]["probes"] = []'; fin
[ $rc -eq 0 ] && grep -q 'keine Gegenprobe' <<<"$OUT" && ok "no probe is allowed and said" || bad "no probe: rc=$rc out=$OUT"
for c in 'v["verdict"] = "request_changes"|the verdict is .request_changes., not approve' \
         'v["tests"]["verdict"] = "request_changes"|tests: the verdict is' \
         'del v["tests"]|no tests part' \
         'v["code"]["evidence"] = [" "]|code: no evidence' \
         'v["code"]["findings"].append({"severity": "blocker", "file": "x", "line": 1, "what": "y"})|code: approve beside a blocker' \
         'v["tests"]["probes"] = [{"test": "t%d" % i, "result": "red"} for i in range(4)]|tests: 4 probes, at most three' \
         'v["tests"]["probes"][0]["result"] = "passed"|a result other than red' \
         'del v["tests"]["coverage"]|tests: no coverage list' \
         'del v["tests"]["probes"]|tests: no probes list' \
         'del v["head"]|names no head commit' \
         'v["head"] = "0123456789abcdef0123456789abcdef01234567"|is not in the history of HEAD'; do
  fin_verdict "${c%%|*}"; fin
  [ $rc -eq 3 ] && grep -q -- "${c#*|}" <<<"$OUT" && ok "${c%%|*} -> 3" || bad "${c%%|*}: rc=$rc out=$OUT"
done
fin_verdict 'v["verdict"] = "request_changes"; v["code"]["evidence"] = []'; fin
[ "$(grep -c '^  - ' <<<"$OUT")" = 2 ] && ok "every reason at once" || bad "reasons: $OUT"
printf '{"verdict": ' > "$FIX/.ah-out/review/fin/branch.verdict.json"; fin
[ $rc -eq 3 ] && grep -q 'unreadable' <<<"$OUT" && ok "a broken verdict file -> 3" || bad "broken: rc=$rc out=$OUT"

# After the verdict: the ledger alone and merges keep it current, anything else does not.
fin_verdict
printf 'Status: erledigt\n' >> "$FIX/tasks/fin.md"; CMSG="chore(ledger): fin erledigt" fcommit tasks/fin.md
fin
[ $rc -eq 0 ] && ok "a ledger commit after the verdict keeps it current" || bad "ledger commit: rc=$rc out=$OUT"
JUDGED="$(git -C "$FIX" rev-parse HEAD)"
printf 'echo main\n' >> "$FIX/scripts/dev/tool.sh"; CMSG="main moved on" fcommit scripts/dev/tool.sh
SIDE_TIP="$(git -C "$FIX" rev-parse HEAD)"
git -C "$FIX" reset -q --hard "$JUDGED"
fin_verdict
git -C "$FIX" merge -q --no-ff -m "Merge main" "$SIDE_TIP"
fin
[ $rc -eq 0 ] && ok "a merge of main after the verdict keeps it current" || bad "merge: rc=$rc out=$OUT"
# A merge that resolves a conflict brings code no parent had.
JUDGED="$(git -C "$FIX" rev-parse HEAD)"
printf 'echo side\n' >> "$FIX/scripts/dev/tool.sh"; CMSG="side change" fcommit scripts/dev/tool.sh
SIDE_TIP="$(git -C "$FIX" rev-parse HEAD)"
git -C "$FIX" reset -q --hard "$JUDGED"
printf 'echo ours\n' >> "$FIX/scripts/dev/tool.sh"; CMSG="our change" fcommit scripts/dev/tool.sh
printf '## [Unreleased]\n- ours\n' >> "$FIX/CHANGELOG.md"; CMSG="our changelog" fcommit CHANGELOG.md
fin_verdict
git -C "$FIX" merge -q --no-ff -m "Merge side" "$SIDE_TIP" >/dev/null 2>&1
printf 'set -e\necho hello\necho main\necho resolved\n' > "$FIX/scripts/dev/tool.sh"
CMSG="Merge side" fcommit scripts/dev/tool.sh
fin
[ $rc -eq 3 ] && grep -q "merges after the verdict head that change files beyond both parents.*scripts/dev/tool.sh" <<<"$OUT" \
  && ok "a merge that resolves a conflict after the verdict -> 3, named" || bad "evil merge: rc=$rc out=$OUT"
git -C "$FIX" reset -q --hard "$JUDGED"; fin_verdict
printf 'echo fix\n' >> "$FIX/scripts/dev/tool.sh"; CMSG="fix: late change" fcommit scripts/dev/tool.sh
fin
[ $rc -eq 3 ] && grep -q 'commits after the verdict head that change more than the ledger.*fix: late change' <<<"$OUT" \
  && ok "a code commit after the verdict -> 3, named" || bad "stale: rc=$rc out=$OUT"
fin_verdict
sed -i 's/^### T1 — eins  \[x\]/### T1 — eins  [ ]/' "$FIX/tasks/fin.md"; fin
[ $rc -eq 3 ] && grep -q 'task T1 is still open' <<<"$OUT" && ok "an open task -> 3" || bad "open: rc=$rc out=$OUT"
sed -i 's/^### T1 — eins  \[ \]/### T1 — eins  [?] (welche Farbe?)/' "$FIX/tasks/fin.md"; fin
[ $rc -eq 3 ] && grep -q 'task T1 is a question' <<<"$OUT" && ok "a [?] task -> 3" || bad "question: rc=$rc out=$OUT"
git -C "$FIX" checkout -q -- tasks/fin.md
r final; [ $rc -eq 2 ] && grep -q 'final needs <ledger>' <<<"$OUT" && ok "no ledger -> 2" || bad "bare final: rc=$rc"
r final "$WORK/nosuch.md"; [ $rc -eq 2 ] && ok "a missing ledger -> 2" || bad "missing: rc=$rc"

# ══ the real repo ═════════════════════════════════════════════════════════════
echo "── repo wiring ──"
sed -n '/^AH_SCRIPT_TESTS_DEFAULT=/,/"$/p' "$REPO_ROOT/scripts/tests/run.sh" | grep -qw 'review_scripts_test' \
  && ok "review_scripts_test is registered in AH_SCRIPT_TESTS_DEFAULT" || bad "not registered"

# R-0287: a local clone copies or links the objects directory file by file, and
# a file a parallel git process adds or removes there breaks it (R-0262); over
# the transport (--no-local) it cannot.
plain="$(grep -nE '^[^#]*git( -C [^ ]+)? clone ' "$HERE/review_scripts_test.sh" | grep -v -- '--no-local')"
[ -z "$plain" ] && ok "every git clone of a fixture here uses --no-local" || bad "a local clone without --no-local: $plain"

echo ""
echo "review_scripts_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
# A skipped lint is not a verified one.
[ "$HOOK_SKIPPED" = 0 ] || exit 75
