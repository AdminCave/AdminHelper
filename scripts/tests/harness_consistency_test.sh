#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# harness_consistency_test.sh — do the rules, skills, agents, settings and the
# scripts they name still describe one process?
#
# The harness is text in five places (CLAUDE.md, .claude/agents, .claude/skills,
# .claude/rules, tasks/README.md) plus the scripts that enforce it. Each piece
# can drift on its own: an agent that is gone but still called, a model value the
# CLI does not take, a section number that moved, a verdict field the closing
# check wants and no reviewer is told to write. Read-only over the real tree.
# (Script paths named by the rules are checked in gitignore_test.sh.)
#
# Run: bash scripts/tests/harness_consistency_test.sh

# ok()/bad() never fail; `cond && ok || bad` assertions are deliberate.
# shellcheck disable=SC2015
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)

PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

command -v python3 >/dev/null 2>&1 || { echo "SKIP: python3 not available"; exit 75; }

# The text that tells a session or an agent what to do.
HARNESS=(CLAUDE.md .claude/agents .claude/skills .claude/rules tasks/README.md tasks/templates)

echo "── agents ──"
# Every agent file: name = file name, a model and an effort the CLI takes
# (code.claude.com/docs/en/sub-agents: model sonnet|opus|haiku|fable|inherit|claude-*,
# effort low|medium|high|xhigh|max), and the tools it may use.
OUT="$(python3 - "$ROOT/.claude/agents" <<'PY'
import os, re, sys
d = sys.argv[1]
names = []
for f in sorted(os.listdir(d)):
    if not f.endswith(".md"):
        continue
    text = open(os.path.join(d, f), encoding="utf-8").read()
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if not m:
        print("BAD %s: no frontmatter" % f); continue
    fm = dict(l.split(":", 1) for l in m.group(1).split("\n") if ":" in l)
    fm = {k.strip(): v.strip() for k, v in fm.items()}
    name = fm.get("name", "")
    names.append(name)
    if name != f[:-3]:
        print("BAD %s: name %r is not the file name" % (f, name))
    if not re.fullmatch(r"sonnet|opus|haiku|fable|inherit|claude-[a-z0-9-]+", fm.get("model", "")):
        print("BAD %s: model %r" % (f, fm.get("model")))
    if not re.fullmatch(r"low|medium|high|xhigh|max", fm.get("effort", "")):
        print("BAD %s: effort %r (set it: the session effort is not the reviewer's)" % (f, fm.get("effort")))
    if not fm.get("tools") or not fm.get("description"):
        print("BAD %s: tools or description missing" % f)
print("NAMES " + " ".join(names))
PY
)"
grep '^BAD ' <<<"$OUT" | sed 's/^BAD /  /' | while IFS= read -r l; do echo "$l"; done
[ -z "$(grep '^BAD ' <<<"$OUT")" ] && ok "every agent file: name, model, effort, tools, description" || bad "agent frontmatter"
AGENTS="$(sed -n 's/^NAMES //p' <<<"$OUT")"
[ -n "$AGENTS" ] && ok "agents: $AGENTS" || bad "no agent found — the scan is broken"

# The roles table of CLAUDE.md §6 and the agent files are the same set.
ROLES="$(sed -n '/^## 6\./,/^## 7\./p' "$ROOT/CLAUDE.md" | sed -n 's/^| `\([a-z-]*\)` |.*/\1/p' | sort | tr '\n' ' ')"
[ "$ROLES" = "$(tr ' ' '\n' <<<"$AGENTS" | grep . | sort | tr '\n' ' ')" ] \
  && ok "CLAUDE.md §6 lists exactly the agent files" || bad "§6 roles '$ROLES' vs agents '$AGENTS'"

# No text calls an agent that is gone. A role is called as `name` next to an
# agent word, as subagent_type, or by its verdict file.
GONE=""
for a in builder tester; do
  [ -f "$ROOT/.claude/agents/$a.md" ] && continue
  hits="$(cd "$ROOT" && grep -rnE "subagent_type:? *\`?$a\b|\`$a\`|<code>$a</code>|@agent-$a\b|$a\.verdict\.json" \
    "${HARNESS[@]}" scripts/dev DEVELOPMENT.md docs/developer/cicd.html docs/en/developer/cicd.html 2>/dev/null)"
  [ -z "$hits" ] || GONE="$GONE"$'\n'"$hits"
done
[ -z "$GONE" ] && ok "no text calls a removed agent (builder, tester)" || bad "removed agents still called:$GONE"

echo "── settings ──"
OUT="$(python3 - "$ROOT" <<'PY'
import json, os, re, sys
root = sys.argv[1]
d = json.load(open(os.path.join(root, ".claude/settings.json"), encoding="utf-8"))
# code.claude.com/docs/en/settings-reference: model is an alias or a full id,
# effortLevel low|medium|high|xhigh (max only per session or per agent).
if not re.fullmatch(r"sonnet|opus|haiku|fable|claude-[a-z0-9-]+", d.get("model", "")):
    print("BAD model %r" % d.get("model"))
if d.get("effortLevel") not in ("low", "medium", "high", "xhigh"):
    print("BAD effortLevel %r" % d.get("effortLevel"))
rules = [r for k in ("allow", "ask", "deny") for r in d.get("permissions", {}).get(k, [])]
for r in rules:
    m = re.match(r"Bash\((?:bash|python3) (scripts/[^ :*]+)", r)
    if m and not (os.path.exists(os.path.join(root, m.group(1))) or "*" in r[len("Bash("):].split(":")[0]):
        print("BAD rule %r names a script that does not exist" % r)
print("RULES %d" % len(rules))
PY
)"
grep '^BAD ' <<<"$OUT" | sed 's/^BAD /  /'
[ -z "$(grep '^BAD ' <<<"$OUT")" ] && ok "settings.json: model, effortLevel and the scripts its rules name" || bad "settings.json"
[ "$(sed -n 's/^RULES //p' <<<"$OUT")" -ge 10 ] 2>/dev/null && ok "settings.json: $(sed -n 's/^RULES //p' <<<"$OUT") permission rules read" \
  || bad "too few permission rules read — the scan is broken"
# The rules name the sessions' model and effort; settings.json (a plain `claude`) and
# start-session.sh must start them that way.
grep -q '"model": "opus"' "$ROOT/.claude/settings.json" && grep -q '"effortLevel": "medium"' "$ROOT/.claude/settings.json" \
  && grep -q '^| Kern-Session | Opus, medium' "$ROOT/CLAUDE.md" \
  && ok "the session model in settings.json is the one CLAUDE.md §6 names" || bad "session model: settings vs CLAUDE.md §6"
KERN="$(bash "$ROOT/scripts/dev/start-session.sh" kern --dry-run 2>&1)"
KLEIN="$(bash "$ROOT/scripts/dev/start-session.sh" klein --dry-run 2>&1)"
grep -q -- '--model opus --effort medium' <<<"$KERN" && grep -q -- '--model sonnet --effort medium' <<<"$KLEIN" \
  && grep -q '^| Klein-Session | Sonnet, medium' "$ROOT/CLAUDE.md" \
  && ok "start-session.sh starts kern and klein as CLAUDE.md §6 names them" || bad "start-session.sh vs CLAUDE.md §6"
for a in reviewer security advisor; do
  grep -q "^model: opus" "$ROOT/.claude/agents/$a.md" && grep -q "^effort: high" "$ROOT/.claude/agents/$a.md" \
    && grep -q "^| \`$a\` | Opus, high" "$ROOT/CLAUDE.md" \
    && ok "$a: opus/high in its file and in CLAUDE.md §6" || bad "$a: model or effort differs from CLAUDE.md §6"
done

echo "── references ──"
# Every "CLAUDE.md §N" in the harness and the scripts names a section that exists.
SECS="$(sed -n 's/^## \([0-9][0-9]*\)\. .*/\1/p' "$ROOT/CLAUDE.md" | tr '\n' ' ')"
REFS="$(cd "$ROOT" && grep -rhoE 'CLAUDE\.md §[0-9]+' "${HARNESS[@]}" scripts/dev scripts/tests/heavy.sh DEVELOPMENT.md \
  2>/dev/null | sed 's/.*§//' | sort -un)"
missing=""
for n in $REFS; do case " $SECS " in *" $n "*) ;; *) missing="$missing §$n" ;; esac; done
[ -n "$REFS" ] && [ -z "$missing" ] && ok "every CLAUDE.md §N reference exists (sections: $SECS)" || bad "dangling:$missing"
# Every skill and rule file the harness names exists.
# Claude Code's own commands (/compact, /model …) are no project skills; /test and
# /vm also name API paths (`/checks`) and are left out of this scan.
missing=""
for s in $(cd "$ROOT" && grep -rhoE '`/[a-z-]+`' CLAUDE.md .claude/agents .claude/rules tasks/README.md \
             .claude/skills/feature-build .claude/skills/feature-plan .claude/skills/roadmap | tr -d '`/' | sort -u); do
  case "$s" in compact|model|effort|config|clear|help|status|agents|resume|init|memory|permissions|cost|doctor|tmp) continue ;; esac
  [ -f "$ROOT/.claude/skills/$s/SKILL.md" ] || missing="$missing /$s"
done
[ -z "$missing" ] && ok "every /skill named exists" || bad "missing skills:$missing"
missing=""
for r in $(cd "$ROOT" && grep -rhoE '\.claude/rules/[a-z-]+\.md' "${HARNESS[@]}" | sort -u); do
  [ -f "$ROOT/$r" ] || missing="$missing $r"
done
[ -z "$missing" ] && ok "every .claude/rules file named exists" || bad "missing rules:$missing"

echo "── verdicts ──"
# The closing check (review.sh final) and the reviewer's brief name the same fields.
R="$ROOT/.claude/agents/reviewer.md"
absent=""
for k in '"mode":"branch"' '"head"' '"code"' '"tests"' '"coverage"' '"probes"' '"evidence"' 'red|green|not-runnable' \
         '<id>.verdict.json' 'branch.verdict.json' 'review.sh final'; do
  grep -qF -- "$k" "$R" || absent="$absent reviewer.md:$k"
done
for k in 'branch.verdict.json' '"head"' '"coverage"' '"probes"' '"evidence"' '"red", "green", "not-runnable"'; do
  grep -qF -- "$k" "$ROOT/scripts/dev/review.sh" || absent="$absent review.sh:$k"
done
grep -qF '.ah-out/review/$SLUG/$ID.verdict.json' "$ROOT/scripts/dev/task-close.sh" || absent="$absent task-close.sh:<id>.verdict.json"
[ -z "$absent" ] && ok "reviewer.md, review.sh final and task-close.sh agree on the verdict files and fields" \
  || bad "not named where it must be:$absent"
# The process names its closing check and both reviewer modes where it is run.
FB="$ROOT/.claude/skills/feature-build/SKILL.md"
grep -q 'Einsatzart `task`' "$FB" && grep -q 'Einsatzart `branch`' "$FB" && grep -q 'review.sh final' "$FB" \
  && ok "/feature-build runs the reviewer in both modes and review.sh final" || bad "/feature-build lacks a mode or the final check"
# The path-bound rules do not load for worktree paths; whoever works there reads them.
unread=""
for f in "$FB" "$ROOT/.claude/skills/feature-plan/SKILL.md" "$R"; do
  grep -q '\.claude/rules/testing\.md' "$f" && grep -q '\.claude/rules/docs\.md\|`docs\.md`' "$f" \
    || unread="$unread ${f#"$ROOT"/}"
done
[ -z "$unread" ] && ok "feature-build, feature-plan and reviewer read testing.md and docs.md themselves" \
  || bad "they do not read the rules they need:$unread"

LIST="$(sed -n '/^AH_SCRIPT_TESTS_DEFAULT=/,/"$/p' "$ROOT/scripts/tests/run.sh")"
grep -qw 'harness_consistency_test' <<<"$LIST" && ok "registered in AH_SCRIPT_TESTS_DEFAULT" || bad "not registered"

echo "harness_consistency_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
