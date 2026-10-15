#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# harness-guard.sh — PreToolUse hook for Bash calls. Two rules on the command
# text, in every session:
#   1. No glob delete in a shared temp directory (R-0098): a command that deletes
#      (rm, rmdir, unlink, shred, also behind xargs or in a loop body) while one
#      of its words is a glob below /tmp, /var/tmp, /dev/shm or $TMPDIR, or a
#      relative glob after a cd there; and a deleting find that starts there. On
#      2026-09-25 a reviewer cleaned up with `rm -rf /tmp/tmp.*` and took every
#      other session's fixtures along.
#   2. No way past the git hooks (R-0102): `git commit --no-verify`/`-n` (also
#      inside `-qn`), `git -c core.hooksPath=…`, a `git config` that writes
#      core.hooksPath.
# Every other tool passes untouched, so an edit to a file whose text says
# --no-verify stays free whatever matcher a running session still holds. A hit
# prints the documented deny JSON; the exit is 0 either way (exit 2 would block
# every call), so an error in here fails open.
# Best effort on the text, false alarms before misses: a quoted word or a
# here-doc body counts like any other word. Not seen: a path built at runtime
# (`rm -rf "$D"/*`), eval, a git alias, GIT_CONFIG_* and `git am -n`.
#
# Run (manually): echo '{"tool_name":"Bash","tool_input":{"command":"…"}}' \
#                   | bash scripts/dev/hooks/harness-guard.sh
set -uo pipefail
command -v python3 >/dev/null 2>&1 || exit 0
python3 -I -c '
import json, os, re, shlex, sys

TMPDIR = os.environ.get("TMPDIR", "").rstrip("/")
ROOTS = ["/tmp", "/var/tmp", "/dev/shm"] + ([TMPDIR] if TMPDIR.startswith("/") else [])
SKIP = {"sudo", "env", "nohup", "command", "builtin", "exec", "time", "timeout", "nice", "xargs",
        "setsid", "stdbuf", "do", "then", "else", "elif", "if", "while", "until", "!", "{", "}"}

def under_tmp(w):
    return bool(re.match(r"\$\{?TMPDIR\b", w)) or any(w == r or w.startswith(r + "/") for r in ROOTS)

def segments(cmd):
    lex = shlex.shlex(cmd, posix=True, punctuation_chars="();<>|&\n")
    lex.whitespace, lex.whitespace_split, lex.commenters = " \t\r", True, ""
    try:
        words = list(lex)
    except ValueError:  # an open quote: plain words then
        words = cmd.split()
    seg, words = [], iter(words + [";"])
    for w in words:
        if w and set(w) <= set(";|&()\n"):
            if seg:
                yield seg
            seg = []
        elif w and set(w) <= set("<>&"):
            next(words, None)  # a redirection and its target
        else:
            seg.append(w)

def command(seg):
    i = 0
    while i < len(seg) and (seg[i] in SKIP or seg[i].startswith("-")
                            or re.match(r"[A-Za-z_][A-Za-z0-9_]*=|[0-9.]+[smhd]?$", seg[i])):
        i += 1
    return (os.path.basename(seg[i]), seg[i + 1:]) if i < len(seg) else ("", [])

def git_bypass(args):
    i = 0
    while i < len(args) and args[i].startswith("-"):
        a = args[i]
        value = args[i + 1] if a in ("-c", "-C", "--git-dir", "--work-tree") and i + 1 < len(args) else ""
        if a.startswith("-c") and (a[2:] or value).lower().startswith("core.hookspath="):
            return "git -c core.hooksPath"
        i += 2 if value else 1
    sub, rest = (args[i], iter(args[i + 1:])) if i < len(args) else ("", iter([]))
    for a in rest if sub == "commit" else []:
        if a == "--":
            break
        if a.startswith("--no-veri") and "--no-verify".startswith(a):
            return "git commit --no-verify"
        for k, ch in enumerate(a[1:] if re.match(r"-[A-Za-z]+$", a) else ""):
            if ch == "n":
                return "git commit " + a
            if ch in "mFCct":  # takes the rest, or the next word, as its value
                if k == len(a) - 2:
                    next(rest, None)
                break
    low = [a.lower() for a in rest] if sub == "config" else []
    if "core.hookspath" in low and (low[-1] != "core.hookspath" or any(a.startswith("--unset") or a == "unset" for a in low)):
        return "git config core.hooksPath"
    return ""

def scan(cmd, depth=0):
    deleting, globs, in_tmp = False, [], False
    for seg in segments(cmd):
        name, args = command(seg)
        hit = git_bypass(args) if name == "git" else ""
        if hit:
            return "pre-commit bypass (" + hit + "): the hooks run review.sh sec --staged; fix what it reports instead (R-0102)"
        shell_c = [k for k, a in enumerate(args[:-1]) if re.match(r"-[A-Za-z]*c[A-Za-z]*$", a)]
        if name in ("bash", "sh", "dash", "zsh") and shell_c and depth < 3:
            hit = scan(args[shell_c[0] + 1], depth + 1)
            if hit:
                return hit
        if name == "cd":
            in_tmp = bool(args) and under_tmp(args[-1])
        globs += [w for w in seg if re.search(r"[*?\[]", w) and (under_tmp(w) or (in_tmp and not w.startswith("/")))]
        deleting = deleting or name in ("rm", "rmdir", "unlink", "shred")
        if name == "find" and ("-delete" in args or any(os.path.basename(a) == "rm" for a in args)):
            deleting = True
            globs += [a for a in args if under_tmp(a)]
    if deleting and globs:
        return "glob delete in a shared temp directory (" + globs[0] + "): delete your own directories by their full path, never with a glob (R-0098)"
    return ""

try:
    call = json.load(sys.stdin)
except ValueError:
    sys.exit(0)
tool_input = call.get("tool_input") if isinstance(call, dict) and call.get("tool_name") == "Bash" else None
cmd = tool_input.get("command") if isinstance(tool_input, dict) else None
why = scan(cmd) if isinstance(cmd, str) else ""
if why:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                      "permissionDecision": "deny", "permissionDecisionReason": why}}))
'
exit 0
