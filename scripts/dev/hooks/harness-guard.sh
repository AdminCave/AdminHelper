#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# harness-guard.sh — PreToolUse hook: an autonomous run does not edit the files
# that define its own rules (autonomy stage 4).
#
# Registered in .claude/settings.json for Edit|Write|MultiEdit|Bash. It reads the
# hook's JSON from stdin, works out which file the call would WRITE, and matches
# that against scripts/dev/harness-paths.txt:
#
#   AH_AUTONOMOUS=1 and no .vm/harness.off  ->  deny (JSON on stdout, exit 0)
#   otherwise                               ->  one warning line on stderr, exit 0
#   not a harness path                      ->  no output at all, exit 0
#
# Never exits non-zero: a PreToolUse hook that errors turns into a blocked tool
# call for everything, harness path or not. The decision is carried by the JSON
# document, which is the documented way for a hook to deny a call.
#
# Bash commands are BEST EFFORT and deliberately narrow: only the shapes that
# actually write — a `>`/`>>` redirection, `sed -i`, `tee`, `cp`/`mv`/`install`,
# and the ones that take a file away entirely (`rm`, `truncate`, `ln -sf`, `dd
# of=`) — are inspected, and only when they are the segment's COMMAND, so reading a
# harness file (`cat CLAUDE.md`, `grep -n mv scripts/tests/run.sh`) stays free.
# The command is tokenized before it is split into segments, so a `|` or `&&`
# inside a quoted string (a commit message, say) is text and not a pipeline; a
# newline only ends a command when it is neither inside a quote nor inside a
# here-doc body, for the same reason. The flip side of skipping here-doc bodies
# is a known gap: `bash <<EOF … EOF` hides its commands from this guard.
# `cd` is followed within a command, and `bash -c "…"` is scanned recursively,
# because Claude Code does not strip it before matching its own rules either.
#
# Known gaps, checked and accepted: a file written from inside python/perl or an
# interactive editor, a path built at runtime (`$VAR/CLAUDE.md`), and
# `find … -exec sed -i`. The real boundary for the runner is the deny list in its
# settings.json (Edit(./.claude/**) and friends); this hook is the second layer.
#
# The WARNING path is nearly silent by design of the hook API: at exit 0 Claude
# Code keeps only stdout JSON and shows stderr in --debug, so the interactive
# warning reaches a debug session and a manual call, not the normal transcript.
# What carries weight is the denial in an autonomous run — the mode this guard
# exists for.
#
# Run (manually):  echo '{"tool_name":"Edit","tool_input":{"file_path":"…"}}' \
#                    | bash scripts/dev/hooks/harness-guard.sh

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)" || exit 0
PATHS="$ROOT/scripts/dev/harness-paths.txt"
MARKER="$ROOT/.vm/harness.off"

[ -f "$PATHS" ] || exit 0

# python3 does the parsing: the hook input is JSON with escaped strings, and a
# shell that guesses at those is a guard that can be talked past with a quote.
# Without python3 the hook steps aside (and says so) rather than denying every
# Edit on the box — every box this runs on has python3 (run.sh, vm.py), and the
# deny rules in the runner's settings.json are the boundary that does not depend
# on this hook at all.
if ! command -v python3 >/dev/null 2>&1; then
  echo "harness-guard: python3 missing — harness paths are unguarded in this session" >&2
  exit 0
fi

# Reads the hook JSON on stdin, prints one repo-relative path per line: the files
# this call would write. Prints nothing for a call that writes nothing.
# The program is handed over with -c, not on stdin: `python3 -` would eat the
# very JSON this hook has to read.
PARSE=$(cat <<'PY'
import json, os, shlex, sys

root = os.path.realpath(sys.argv[1])

# Wrappers that stand in front of the real command word, plus the subshell
# parentheses shlex hands over as their own tokens.
WRAPPERS = {"sudo", "env", "timeout", "nice", "nohup", "stdbuf", "command", "xargs", "(", ")", "{", "}"}
# Wrapper flags that eat the next word (`sudo -u root tee …`, `timeout -k 5 …`).
VALUE_FLAGS = {"-u", "-g", "-k", "-s", "-n", "-p", "-C", "-D", "--user", "--group", "--signal"}
SEPARATORS = {"|", "||", "&&", ";", "&", ";;"}

out = []


def rel(p, base):
    """Repo-relative path, or None for anything outside the checkout."""
    if not p or not isinstance(p, str):
        return None
    p = os.path.realpath(p if os.path.isabs(p) else os.path.join(base, p))
    if p == root:
        return None
    return os.path.relpath(p, root) if p.startswith(root + os.sep) else None


def tokenize(cmd):
    """Shell tokens, quotes respected. punctuation_chars keeps the operators as
    tokens of their own, so `x|tee f` and `>CLAUDE.md` survive while a `|` inside
    a quoted commit message does not become a pipeline."""
    lex = shlex.shlex(cmd, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    try:
        return list(lex)
    except ValueError:
        return cmd.split()


def is_redirect(tok):
    return ">" in tok and all(c in "<>|&" for c in tok)


def logical_lines(cmd):
    """Split on newlines that really end a command — not on the ones inside a
    quoted string or a here-doc body. shlex is told to split on whitespace, and
    a newline IS whitespace, so it never becomes a token of its own: without
    this, a multi-line command arrived as ONE segment and everything below its
    first line was invisible. Splitting on every newline instead would convict a
    commit message written as a here-doc (CLAUDE.md asks for exactly that),
    because its prose lines would each look like a command."""
    out, buf = [], []
    quote = None
    esc = False
    heredocs = []        # delimiters whose bodies are still to come
    skip_to = None       # delimiter of the body currently being skipped
    for line in cmd.split("\n"):
        if skip_to is not None:
            if line.strip() == skip_to:
                skip_to = heredocs.pop(0) if heredocs else None
                if skip_to is not None:
                    heredocs.insert(0, skip_to)
                    skip_to = heredocs.pop(0)
            continue
        i = 0
        while i < len(line):
            ch = line[i]
            if esc:
                esc = False
            elif ch == "\\" and quote != "'":
                esc = True
            elif quote:
                if ch == quote:
                    quote = None
            elif ch in "\"'":
                quote = ch
            elif ch == "<" and line[i:i + 2] == "<<":
                # `<<EOF`, `<<-'EOF'`, `<< "EOF"` — the body is data, not commands.
                rest = line[i + 2:].lstrip("-").lstrip()
                delim = rest.split()[0] if rest.split() else ""
                delim = delim.strip("\"'")
                if delim:
                    heredocs.append(delim)
                i += 2
                continue
            i += 1
        buf.append(line)
        if quote is None and not esc:
            out.append("\n".join(buf) if len(buf) > 1 else buf[0])
            buf = []
            if heredocs:
                skip_to = heredocs.pop(0)
    if buf:
        out.append("\n".join(buf))
    return out


def scan(cmd, base, depth=0):
    if depth > 2:
        return
    cur = base
    for line in logical_lines(cmd):
        segment = []
        for tok in tokenize(line) + [";"]:
            if tok in SEPARATORS:
                cur = run_segment(segment, cur, depth)
                segment = []
            else:
                segment.append(tok)


def run_segment(tok, cwd, depth):
    """Record what this segment writes; return the cwd the NEXT one runs in."""
    if not tok:
        return cwd

    # Redirections first, and they leave the token list: `cp a b > /dev/null`
    # must not mistake /dev/null for the copy's destination.
    clean, i = [], 0
    while i < len(tok):
        t = tok[i]
        if is_redirect(t):
            if ">" in t and i + 1 < len(tok):
                out.append(rel(tok[i + 1], cwd))
            i += 2
            continue
        clean.append(t)
        i += 1
    if not clean:
        return cwd

    # The command word, past assignments, wrappers and their flags/values.
    i = 0
    while i < len(clean):
        t = clean[i]
        if "=" in t and not t.startswith("-") and t.split("=")[0].isidentifier():
            i += 1
        elif t.startswith("-"):
            i += 2 if t in VALUE_FLAGS else 1
        elif os.path.basename(t) in WRAPPERS or t.isdigit():
            i += 1
        else:
            break
    if i >= len(clean):
        return cwd
    verb = os.path.basename(clean[i])
    args = clean[i + 1:]
    words = [a for a in args if not a.startswith("-")]

    if verb == "cd":
        return os.path.normpath(os.path.join(cwd, words[0])) if words else cwd

    if verb in ("bash", "sh", "dash", "zsh"):
        # -c, but also -lc and friends: any flag carrying a c takes the next word
        # as a command string.
        for j, a in enumerate(args):
            if a.startswith("-") and "c" in a:
                rest = [w for w in args[j + 1:] if not w.startswith("-")]
                if rest:
                    scan(rest[0], cwd, depth + 1)
                break
    elif verb == "sed" and any(
        a == "-i" or a.startswith("-i.") or a.startswith("--in-place") for a in args
    ):
        out.extend(rel(w, cwd) for w in words[1:])   # words[0] is sed's script
    elif verb == "tee":
        out.extend(rel(w, cwd) for w in words)
    elif verb in ("rm", "shred", "truncate", "unlink"):
        # Taking a harness file away is the most complete edit there is.
        out.extend(rel(w, cwd) for w in words)
    elif verb == "ln":
        # `ln -sf x CLAUDE.md` replaces the file with a link to something else.
        out.extend(rel(w, cwd) for w in words[1:] if len(words) > 1)
    elif verb == "dd":
        for a in args:
            if a.startswith("of="):
                out.append(rel(a[3:], cwd))
    elif verb in ("cp", "mv", "install"):
        # An explicit -t/--target-directory, or the last word, is the target.
        target = None
        for j, a in enumerate(args):
            if a == "-t" and j + 1 < len(args):
                target = args[j + 1]
            elif a.startswith("--target-directory="):
                target = a.split("=", 1)[1]
        sources = words
        if target is None and len(words) > 1:
            target, sources = words[-1], words[:-1]
        if target is not None:
            out.append(rel(target, cwd))
            abs_t = target if os.path.isabs(target) else os.path.join(cwd, target)
            # A directory target writes <dir>/<basename(src)> — `cp x .claude/`
            # never matches `.claude/**` without this.
            if target.endswith("/") or os.path.isdir(abs_t):
                for src in sources:
                    out.append(rel(os.path.join(target, os.path.basename(src)), cwd))
        # `mv CLAUDE.md /tmp/x` takes the harness file AWAY — the source counts.
        if verb == "mv":
            out.extend(rel(w, cwd) for w in sources)
    return cwd


try:
    ev = json.load(sys.stdin)
except Exception:
    sys.exit(0)
if not isinstance(ev, dict):
    sys.exit(0)
tool = ev.get("tool_name") or ""
ti = ev.get("tool_input")
ti = ti if isinstance(ti, dict) else {}
# The session's own cwd, which is what a relative path in a Bash command means.
cwd = ev.get("cwd")
cwd = cwd if isinstance(cwd, str) and os.path.isdir(cwd) else root

if tool in ("Edit", "Write", "MultiEdit"):
    out.append(rel(ti.get("file_path"), cwd))
elif tool == "Bash":
    cmd = ti.get("command")
    if isinstance(cmd, str):
        scan(cmd, cwd)

for p in dict.fromkeys(p for p in out if p):
    print(p)
PY
)
targets() { python3 -c "$PARSE" "$ROOT"; }

# The list is shell `case` patterns, where `*` crosses `/` — `.claude/**` is the
# whole subtree, every other line is the file itself.
match() {
  local path="$1" pattern
  while IFS= read -r pattern; do
    case "$pattern" in ''|'#'*) continue ;; esac
    # shellcheck disable=SC2254  # the list IS patterns; that is the point
    case "$path" in $pattern) return 0 ;; esac
  done < "$PATHS"
  return 1
}

HIT=""
while IFS= read -r p; do
  [ -n "$p" ] || continue
  if match "$p"; then HIT="$p"; break; fi
done < <(targets)

[ -n "$HIT" ] || exit 0

if [ "${AH_AUTONOMOUS:-0}" = "1" ] && [ ! -e "$MARKER" ]; then
  # The documented deny document. The path is escaped for JSON: a file name with
  # a quote in it would otherwise produce a broken document, and a guard whose
  # answer cannot be parsed is a guard that failed open.
  ESC="${HIT//\\/\\\\}"; ESC="${ESC//\"/\\\"}"
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"harness path: %s (autonomous run; bash scripts/dev/harness.sh off lifts this)"}}\n' "$ESC"
else
  echo "harness-guard: $HIT is a harness path — change it deliberately, not in passing" >&2
fi
exit 0
