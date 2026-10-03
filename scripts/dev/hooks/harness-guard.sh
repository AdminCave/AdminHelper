#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# harness-guard.sh — PreToolUse hook: an autonomous run does not edit the files
# that define its own rules (autonomy stage 4), and no session deletes by glob
# in a shared temp directory (R-0098).
#
# Registered in .claude/settings.json for Edit|Write|MultiEdit|Bash. It reads the
# hook's JSON from stdin, works out which file the call would WRITE, and matches
# that against scripts/dev/harness-paths.txt:
#
#   AH_AUTONOMOUS=1 and no .vm/harness.off  ->  deny (JSON on stdout, exit 0)
#   otherwise                               ->  one warning line on stderr, exit 0
#   not a harness path                      ->  no output at all, exit 0
#
# A Bash command that deletes by glob in a SHARED temp directory — /tmp,
# /var/tmp, /dev/shm, $TMPDIR, or Claude Code's /tmp/claude-<uid>, …/-<project>
# and …/-<project>/<session-uuid> — is denied in EVERY mode, and the kill switch does
# not lift it (Kevin, 2026-09-27): on 2026-09-25 a reviewer cleaned up with
# `rm -rf /tmp/tmp.*` and took the fixtures of every other session along. That
# covers a loop over such a glob that deletes in its body (`for d in /tmp/x*`,
# `for d in $(ls /tmp/x*)`, `… | while read d`), `… | xargs rm` behind it (also
# `|&`, `xargs sh -c 'rm …'`, a `grep -l` as the lister), an operand after `--`,
# a glob ABOVE the root at any depth (`/t*/claude-1000/*`, R-0109), and since
# R-0125 `[^x]` read like `[!x]`, a brace list (`/{tmp,x}/…`) and a literal
# operand after `cd` into a glob (`cd /t* && rm -rf claude-1000`). One
# level deeper is somebody's own directory (a scratchpad, an mktemp dir) and
# stays free: "anywhere below /tmp" hit 13 legitimate scratchpad cleanups in
# 34 513 real commands. Not seen: a list read by `mapfile`/`readarray` or a
# process substitution, a list without a glob whose paths are built at runtime
# (`ls /tmp | while read d; do rm -rf /tmp/$d`), a list piped into a shell
# without xargs (`… | sh -c 'xargs rm'`, `… | sed 's/^/rm /' | sh`),
# `cat … | xargs rm` (the file's content, not names), a brace sequence
# (`{1..3}`), a variable inside a brace list (`/{$X,y}/…`) and the expansions
# past the 32nd of a brace list.
#
# The same holds for the ways past the pre-commit hook (R-0102, Kevin
# 2026-09-27): `git commit --no-verify`/`-n` (also inside `-qn`), `git am -n`
# and its long form (pre-applypatch is the one hook git am runs), `git -c
# core.hooksPath=…` (and its GIT_CONFIG_* twins), and `git config … core.hooksPath`
# unless it only reads, or dropping the whole `core` section. Kevin's own shell is
# untouched: the hook sees only what the model runs. Not seen, like the write
# gaps below: a git alias for `commit -n` or `am -n`, `.git/config` written directly (it is
# no harness path), a hooksPath brought in through `include.path`, `git config
# --edit`, `eval` or a command substitution, git-commit called by its exec path,
# and plumbing (`commit-tree`, `update-ref`). `chmod -x` on a hook is a write to
# a harness path (below), so the harness rule, not this one, covers it.
#
# Always exits 0: exit 2 would block every call whatever the JSON says, and any
# other non-zero exit blocks nothing — the call goes on through the normal
# permission flow. The decision is carried by the JSON document, the documented
# way for a hook to deny a call; an error in here therefore fails open.
#
# Bash commands are BEST EFFORT and deliberately narrow: only the shapes that
# actually write — a `>`/`>>` redirection, `sed -i`, `tee`, `cp`/`mv`/`install`,
# the ones that take a file away entirely (`rm`, `truncate`, `ln -sf`, `dd
# of=`), and the ones that change what it is (`chmod`, `chown`, `chgrp`) — are
# inspected, and only when they are the segment's COMMAND, so reading a
# harness file (`cat CLAUDE.md`, `grep -n mv scripts/tests/run.sh`) stays free.
# git writes through its output options too (R-0159): `--output` of diff, log,
# show, range-diff and format-patch, `-o`/`--output` of archive, the directory of
# format-patch, the file of `bundle create`, and `grep -O<cmd>` runs a command on
# its matches. Not seen there: `--output` of other subcommands (rev-list,
# diff-tree, whatchanged, …), a pager or alias set through `-c`/GIT_PAGER,
# `archive --exec`, and `git diff` outside a repository, which reads past `--`
# like `--no-index` without saying so.
# What a take-away verb (`rm`, `rmdir`, `shred`, `unlink`, `chmod`/`chown`/
# `chgrp`, the source of `mv`, the start of a deleting `find`) reaches also
# hits when harness paths lie BELOW it — `rm -rf .claude`, and a glob through
# what it matches in the tree: `rm -rf scripts/dev/*`, `rm -rf ./*`, while
# `rm -f *.log` takes the logs only; behind a variable a glob reaches its
# directory (R-0127). Not seen: `git clean`, `git rm`, a delete from python or another
# interpreter.
# The command is tokenized before it is split into segments, so a `|` or `&&`
# inside a quoted string (a commit message, say) is text and not a pipeline; a
# newline only ends a command when it is neither inside a quote nor inside a
# here-doc body, for the same reason (a here-string `<<<`, a shift inside
# `$((…))` and anything in a comment start none, R-0126/R-0133). The flip side of skipping here-doc bodies
# is a known gap: `bash <<EOF … EOF` hides its commands from this guard.
# `cd` is followed within a command, and `bash -c "…"` is scanned recursively,
# because Claude Code does not strip it before matching its own rules either.
#
# Known gaps, checked and accepted: a file written or deleted from inside
# python/perl or an interactive editor, a path built at runtime
# (`$VAR/CLAUDE.md`, `rm -rf "$D"/*` — the hook cannot resolve a variable other
# than $TMPDIR), `find … -exec sh -c 'rm …'`, a process substitution `<(…)` (as
# an operand or feeding a loop, `done < <(ls /tmp/x*)`), `find … -exec sed -i`,
# a here-doc fed to a shell (`bash <<EOF … EOF`), a quoted string of operator
# characters only (`-m ");"`, read as the operators once shlex has dropped the
# quotes; one with a `<` or `>` in it stays a word, R-0134), a `#` inside a word
# (`a#b`), which shlex reads as the start of a comment (R-0145),
# `<<- EOF` with a space before the delimiter, and the
# three git ways of restoring content over a file — `git apply <patch>`,
# `git checkout <rev> -- <pfad>`, `git restore --source=<rev> -- <pfad>`. For the
# runner the settings cover those (checkout/restore/stash are denied outright,
# and anything not allowed is denied under dontAsk); in an interactive session
# they are the reason the deny list exists next to this hook. The real boundary for the runner is the deny list in its
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

# Reads the hook JSON on stdin, prints one finding per line: `T <operand>` for
# each glob delete in a shared temp directory, `B <words>` for a way past the
# pre-commit hook, `H <path>` for each repo-relative file this call would write,
# `A <path>` for each checkout path it takes away ("." is the root). Prints
# nothing for a call that does none of these.
# The program is handed over with -c, not on stdin: `python3 -` would eat the
# very JSON this hook has to read.
PARSE=$(cat <<'PY'
import fnmatch, glob, itertools, json, os, re, shlex, sys

root = os.path.realpath(sys.argv[1])

# Wrappers that stand in front of the real command word, plus the subshell
# parentheses shlex hands over as their own tokens — each with the flags that
# take the NEXT word as their value (`sudo -u root tee …`, `timeout -k 5 10s …`).
# Per wrapper: `nice -n` takes a value, `sudo -n` does not, and one shared set
# let `sudo -n rm …` eat the rm.
WRAPPERS = {
    "sudo": {"-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-T", "-U", "-R",
             "--user", "--group", "--chdir", "--host", "--prompt", "--role", "--type",
             "--other-user", "--command-timeout", "--chroot", "--close-from"},
    "env": {"-u", "-C", "--unset", "--chdir"},
    "timeout": {"-k", "-s", "--kill-after", "--signal"},
    "nice": {"-n", "--adjustment"},
    "ionice": {"-c", "-n", "-p", "-P", "-u", "--class", "--classdata"},
    "stdbuf": {"-i", "-o", "-e", "--input", "--output", "--error"},
    "xargs": {"-a", "-d", "-E", "-I", "-L", "-n", "-P", "-s", "--arg-file", "--delimiter",
              "--max-args", "--max-procs", "--max-chars", "--max-lines", "--replace", "--eof"},
    "time": {"-f", "-o", "--format", "--output"},
    "exec": {"-a"},
    "nohup": set(), "setsid": set(), "command": set(), "builtin": set(),
    "(": set(), ")": set(), "{": set(), "}": set(),
}
# Shell keywords in front of a command: `for …; do rm x; done` reaches the
# segment `do rm x`, and reading `do` as the command word hid the rm.
KEYWORDS = {"do", "then", "else", "elif", "if", "while", "until", "!"}
# timeout's duration (`10`, `10s`, `1.5m`, `.5`) is no command word either.
DURATION = re.compile(r"^([0-9]+\.?[0-9]*|\.[0-9]+)[smhd]?$")
SEPARATORS = {"|", "|&", "||", "&&", ";", "&", ";;", ";&", ";;&"}
# Pipes hand what the left side lists on to the right side; `|&` is `2>&1 |`.
PIPES = {"|", "|&"}
# The shell operators, longest first: shlex hands a run of punctuation over as
# ONE token (`$(ls /tmp/x*); do` ends in `);`), and each has to be split back
# into the operators it is made of.
OPERATORS = sorted(SEPARATORS | {"(", ")", "<", ">", ">>", "<<", "<<<", ">&", "<&", "&>", "&>>",
                                 ">|", "<>"}, key=len, reverse=True)
DELETERS = {"rm", "rmdir", "unlink", "shred"}
# A chmod mode word: octal, or symbolic (`+x`, `u=rw,go-w`).
CHMOD_MODE = re.compile(r"^([0-7]+|[ugoa]*[-+=].*)$")

# The temp roots. `$TMPDIR` as TEXT stands for itself (a placeholder root no
# real path has), its current VALUE is a root as well.
TMPDIR_ROOT = "/<TMPDIR>"
TMP_ROOTS = ["/tmp", "/var/tmp", "/dev/shm", TMPDIR_ROOT]
_tmpdir = os.environ.get("TMPDIR", "")
if os.path.isabs(_tmpdir) and os.path.normpath(_tmpdir) != "/":
    TMP_ROOTS.append(os.path.normpath(_tmpdir))
TMPDIR_TEXT = re.compile(r"^\$(?:TMPDIR\b|\{TMPDIR(?::?[-=?+][^}]*)?\})")
# Where a word that starts with any other variable points: nowhere this hook
# can name, so nothing below it is matched (`cd "$SP" && rm -rf x*` is free).
UNRESOLVED = "/<unresolved>"

out = []        # repo-relative paths this call writes
taken = []      # repo-relative paths it takes away (deletes, moves, chmods): "." is the root
tmp_hits = []   # glob deletes in a shared temp directory
bypasses = []   # ways past the pre-commit hook
deletes = []    # every delete seen, nested `bash -c` included: a loop counts them


GLOB_LIMIT = 1000   # matches of one glob operand; past that, its directory counts


def taken_away(word, base):
    """The checkout paths a take-away verb reaches with this operand (R-0127):
    the path itself; for a glob, also one a `cd` into a glob put in front of
    it, what it matches in the real tree (`rm -rf ./*` -> every entry of the
    root, `rm -f *.log` -> the logs, not the root); "." for the root and every
    directory above it. A glob behind a variable cannot be matched and reaches
    its literal directory (`scripts/$X/*` -> scripts). Nothing outside the
    checkout, nothing for an operand that is a variable."""
    full = resolve(word, base)
    if full == UNRESOLVED:
        return []
    if not has_glob(full):
        found = [full]
    elif "$" in full or "`" in full or "[:" in full:
        # A variable, or a POSIX class (`[[:lower:]]`) Python does not know.
        found = [glob_dir(full, "/")]
    else:
        found = list(itertools.islice(glob.iglob(full.replace("[^", "[!")), GLOB_LIMIT + 1))
        if len(found) > GLOB_LIMIT:
            found = [glob_dir(full, "/")]
    hits = []
    for p in found:
        if p == UNRESOLVED:
            continue
        p = os.path.realpath(p)
        # The root, and every directory above it, holds the whole checkout.
        if p == root or root.startswith(p.rstrip(os.sep) + os.sep):
            hits.append(".")
        elif p.startswith(root + os.sep):
            hits.append(os.path.relpath(p, root))
    return hits


def rel(p, base):
    """Repo-relative path, or None for anything outside the checkout."""
    if not p or not isinstance(p, str):
        return None
    p = os.path.realpath(p if os.path.isabs(p) else os.path.join(base, p))
    if p == root:
        return None
    return os.path.relpath(p, root) if p.startswith(root + os.sep) else None


def resolve(word, base):
    """An absolute, normalized path for a word. `$TMPDIR`/`${TMPDIR…}` in front
    becomes its placeholder root; any other variable, `~` or a command
    substitution in front makes it UNRESOLVED."""
    word = TMPDIR_TEXT.sub(TMPDIR_ROOT, word, count=1)
    if word.startswith(("$", "~", "`")):
        return UNRESOLVED
    # normpath keeps a leading `//` (POSIX leaves it implementation-defined);
    # on Linux `//tmp` is /tmp.
    return "/" + os.path.normpath(os.path.join(base, word)).lstrip("/")


def in_repo(p):
    real = os.path.realpath(p)
    return real == root or real.startswith(root + os.sep)


# Claude Code's own directories in a temp root: per uid, per project (the path
# encoded with a leading `-`), per session (a UUID; it holds tasks/ and
# scratchpad/ of all its subagents), and the two it keeps per uid for every
# session (bash-edit-diff/ with one folder per session, bundled-skills/). Any
# other name there is somebody's own entry — an `mktemp -d -p /tmp/claude-<uid>`
# dir, a file (`rm.out`).
CLAUDE_DIR = re.compile(r"/claude-[0-9]+(/(-[^/]*(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})?"
                        r"|bash-edit-diff|bundled-skills))?$")


def is_shared(p):
    """p IS a shared temp directory — a temp root, or one of Claude Code's
    directories in it. Not below one, and not a named entry in one: that is
    somebody's own. Never inside this checkout."""
    if in_repo(p):
        return False
    for c in (p, os.path.realpath(p)):
        for r in TMP_ROOTS:
            if c == r or r != TMPDIR_ROOT and c.startswith(r.rstrip("/") + "/") \
                    and CLAUDE_DIR.match(c[len(r.rstrip("/")):]):
                return True
    return False


def has_glob(word):
    return any(c in word for c in "*?[")


def glob_dir(word, base):
    """The directory a glob operand reaches into: its literal part — up to the
    first glob character or variable — cut back to the last `/`
    (`/tmp/tmp.*` -> /tmp, `/tmp/$U/*` -> /tmp, `$SP/tmp.*` -> UNRESOLVED)."""
    word = TMPDIR_TEXT.sub(TMPDIR_ROOT, word, count=1)
    lit = word[:min(i for i, c in enumerate(word + "*") if c in "*?[$`")]
    if not lit and word.startswith(("$", "`")):
        return UNRESOLVED
    return resolve(lit[:lit.rfind("/") + 1], base) if "/" in lit else os.path.normpath(base)


def reaches_root(pattern):
    """The glob can match a temp root itself or an entry right in it: `/tmp*`,
    `/t*`, `/*/tmp.*`, and `tmp*` after `cd /` all take /tmp along. With its
    glob character ABOVE the root it reaches every depth: `/t*/claude-1000/*`
    and `cd /t* && rm -rf claude-1000/*` walk into every session's directories
    (R-0109). A glob that only starts below the root, in a path that names the
    root literally, matches deeper entries only — somebody's own."""
    # bash reads `[^x]` like `[!x]`; Python's fnmatch takes the `^` literally
    # (R-0125).
    comps = pattern.replace("[^", "[!").strip("/").split("/")
    for r in TMP_ROOTS:
        rc = r.strip("/").split("/")
        if r == TMPDIR_ROOT or len(comps) < len(rc) or not all(
                fnmatch.fnmatchcase(c, p) for c, p in zip(rc, comps)):
            continue
        if len(comps) <= len(rc) + 1 or any(has_glob(p) for p in comps[:len(rc)]):
            return True
    return False


def brace_expand(word, limit=32):
    """bash's brace expansion, comma lists only and nested (`/{tmp,x}/tmp.*` ->
    `/tmp/tmp.*`, `/x/tmp.*`), capped at `limit` results. `${…}` is a variable,
    `{}` and `{a}` stay literal, and a sequence `{1..3}` is a documented limit."""
    for i, c in enumerate(word):
        if c != "{" or (i and word[i - 1] == "$"):
            continue
        depth, commas = 0, []
        for j in range(i, len(word)):
            if word[j] == "{":
                depth += 1
            elif word[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            elif word[j] == "," and depth == 1:
                commas.append(j)
        else:
            continue            # never closed: no expansion here
        if not commas:
            continue
        out, last = [], i + 1
        for k in commas + [j]:
            for e in brace_expand(word[:i] + word[last:k] + word[j + 1:], limit):
                out.append(e)
                if len(out) >= limit:
                    return out
            last = k + 1
        return out
    return [word]


def tmp_glob(word, base):
    """A glob whose literal directory is a shared temp directory, or one that
    reaches a temp root (see reaches_root); or a shared directory itself (`rm -rf /tmp`
    takes the same as `rm -rf /tmp/*`). A bare `$TMPDIR` is left to the
    variable rule: `rm -rf "$TMPDIR"` after `export TMPDIR=$(mktemp -d …)` is
    cleanup. Every brace expansion of the word counts (R-0125)."""
    return any(tmp_glob_one(w, base) for w in brace_expand(word) if w)


def tmp_glob_one(word, base):
    # A cwd that is itself a glob (`cd /t* && rm -rf claude-1000`) makes a
    # literal operand a glob (R-0125).
    full = resolve(word, base)
    if has_glob(word) or full != UNRESOLVED and has_glob(full):
        d = glob_dir(word, base)
        if d == UNRESOLVED or in_repo(d):
            return False
        return is_shared(d) or reaches_root(full)
    return full != TMPDIR_ROOT and is_shared(full)


def printable(word):
    return "".join(c if c.isprintable() else "?" for c in word)


def find_delete(args, cwd):
    """For `find <start…> <expr>`: whether it deletes (-delete, -exec(dir) rm),
    the start path that makes that a delete in a shared temp directory — a
    shared directory itself or a glob in one, whatever the expression selects
    there — and its start paths."""
    i = 0
    while i < len(args) and (args[i] in ("-H", "-L", "-P", "-D") or args[i].startswith("-O")):
        i += 2 if args[i] == "-D" else 1
    starts = []
    while i < len(args) and not (args[i].startswith("-") or args[i] in ("(", "!", ")", ",")):
        starts.append(args[i])
        i += 1
    expr = args[i:]
    deletes = "-delete" in expr or any(
        a in ("-exec", "-execdir", "-ok", "-okdir") and j + 1 < len(expr)
        and os.path.basename(expr[j + 1]) in DELETERS
        for j, a in enumerate(expr))
    starts = starts or ["."]
    for s in starts:
        if tmp_glob(s, cwd):
            return deletes, s, starts
    return deletes, None, starts


# `git commit` options whose value may be the NEXT word: skipped, so that
# `-m "-n"` stays a message. In a cluster like `-am` the value follows it.
COMMIT_SHORT_VALUE = set("mFCct")
COMMIT_LONG_VALUE = {"--message", "--file", "--reuse-message", "--reedit-message", "--template",
                     "--author", "--date", "--cleanup", "--fixup", "--squash", "--trailer",
                     "--pathspec-from-file"}
CONFIG_VALUE = {"-f", "--file", "--blob", "--type", "--default", "--comment"}
GIT_CONFIG_ENV = re.compile(r"^GIT_CONFIG_(?:KEY_[0-9]+|PARAMETERS)=")


def hooks_key(s):
    return s.lower().startswith("core.hookspath")


def commit_skips_hook(rest):
    j = 0
    while j < len(rest):
        a = rest[j]
        if a == "--":
            break
        if a.startswith("--"):
            name = a.split("=", 1)[0]
            # git takes any unambiguous prefix of a long option.
            if len(name) >= len("--no-veri") and "--no-verify".startswith(name):  # review: ok the flag this guard refuses
                return a
            # ... value options included: `--mess "-n x"` is a message, and git
            # takes a prefix down to one letter (`--m -- -n` skips the hook).
            if "=" not in a and len(name) > 2 and any(o.startswith(name) for o in COMMIT_LONG_VALUE):
                j += 1
        elif a.startswith("-") and len(a) > 1:
            for k, c in enumerate(a[1:]):
                if c == "n":
                    return a
                if c in COMMIT_SHORT_VALUE or c in "Su":
                    # The rest of the cluster is the value; at its end, the next word.
                    if c in COMMIT_SHORT_VALUE and k == len(a) - 2:
                        j += 1
                    break
        j += 1
    return None


# `git am` options whose value may be the NEXT word: skipped, so that
# `--resolvemsg -- -n` is read as git reads it — `--` is the message, -n a flag.
AM_LONG_VALUE = {"--resolvemsg", "--directory", "--exclude", "--include", "--whitespace",
                 "--patch-format", "--quoted-cr", "--empty"}


def am_skips_hook(rest):
    """`git am -n` (and its long form) skips pre-applypatch, the one hook git am
    runs (R-0110 T8). In a cluster, -C and -p take the rest as their value, or
    the next word at its end (`-C1`, `-C 1`); -S takes only an attached key id."""
    j = 0
    while j < len(rest):
        a = rest[j]
        if a == "--":
            break
        if a.startswith("--"):
            name = a.split("=", 1)[0]
            # git am has no other long option under --no-v, so every prefix from
            # there on is the flag (commit needs more: --no-verbose).
            if len(name) >= len("--no-v") and "--no-verify".startswith(name):  # review: ok the flag this guard refuses
                return a
            # git takes any unambiguous prefix, down to one letter (`--d`).
            if "=" not in a and len(name) > 2 and any(o.startswith(name) for o in AM_LONG_VALUE):
                j += 1
        elif a.startswith("-") and len(a) > 1:
            for k, c in enumerate(a[1:]):
                if c == "n":
                    return a
                if c in "CpS":
                    if c in "Cp" and k == len(a) - 2:
                        j += 1
                    break
        j += 1
    return None


def config_sets_hooks(rest):
    words, opts, j = [], set(), 0
    while j < len(rest):
        a = rest[j]
        if a.startswith("-"):
            opts.add(a.split("=", 1)[0])
            if a in CONFIG_VALUE:
                j += 1
        else:
            words.append(a)
        j += 1
    # Dropping or renaming the section takes core.hooksPath with it.
    if (opts & {"--remove-section", "--rename-section"} or words[:1] in (["remove-section"], ["rename-section"])) \
            and any(w.lower() == "core" for w in words):
        return True
    if not any(hooks_key(w) for w in words) or words[0] in ("get", "list"):
        return False
    if words[0] in ("set", "unset"):
        return True
    if opts & {"--get", "--get-all", "--get-regexp", "--get-urlmatch", "--list", "-l"}:
        return False
    # `git config core.hooksPath` alone reads it; a value or --unset writes.
    return bool(opts & {"--unset", "--unset-all", "--add", "--replace-all"}) or len(words) >= 2


def git_skips_hook(args):
    """The ways a git call gets past the pre-commit hook, or None."""
    i = 0
    while i < len(args) and args[i].startswith("-"):
        a = args[i]
        if a in ("-c", "--config-env") and i + 1 < len(args):
            if hooks_key(args[i + 1].split("=", 1)[0]) or hooks_key(args[i + 1]):
                return "git %s %s" % (a, args[i + 1])
            i += 2
            continue
        if a.startswith("--config-env=") and hooks_key(a.split("=", 1)[1]):
            return "git " + a
        i += 2 if a in ("-C", "--git-dir", "--work-tree", "--namespace", "--attr-source") else 1
    if i >= len(args):
        return None
    sub, rest = args[i], args[i + 1:]
    if sub == "commit":
        hit = commit_skips_hook(rest)
        return "git commit " + hit if hit else None
    if sub == "am":
        hit = am_skips_hook(rest)
        return "git am " + hit if hit else None
    if sub == "config" and config_sets_hooks(rest):
        return "git config " + " ".join(rest)
    return None


def git_writes(args, cwd):
    """Where a git call writes through its output options (R-0159): files
    (`--output` of diff/log/show/range-diff/format-patch, `-o`/`--output` of
    archive, the file of `bundle create`), directories (`-o`/`--output-directory`
    of format-patch) and the commands `grep -O`/`--open-files-in-pager` runs, with
    the paths its matches can come from. Read like git reads them: short clusters
    left to right (`-ko DIR`), unique prefixes of a long option (`--open=`), `--`
    ending the options only where the revision parser takes it first (diff without
    --no-index, log, show) — elsewhere a value option can swallow it. Relative
    paths count from `-C`, as git takes them."""
    i, gcwd = 0, cwd
    while i < len(args) and args[i].startswith("-"):
        a = args[i]
        if a == "-C" and i + 1 < len(args):
            gcwd = resolve(args[i + 1], gcwd)
            i += 2
            continue
        i += 2 if a in ("-c", "--config-env", "--git-dir", "--work-tree", "--namespace", "--attr-source") else 1
    files, dirs, cmds = [], [], []
    if i >= len(args):
        return files, dirs, cmds, gcwd
    sub, rest = args[i], args[i + 1:]

    def long_opt(a, name, least):
        """The value of `--name[=v]` or a unique prefix of it; "" without a value."""
        key = a.split("=", 1)[0]
        if len(key) >= least and name.startswith(key):
            return a.split("=", 1)[1] if "=" in a else ""
        return None

    if sub == "bundle" and rest[:1] == ["create"]:
        j, ops = 1, []
        while j < len(rest):
            a = rest[j]
            if long_opt(a, "--version", 3) == "" and "=" not in a:
                j += 2
                continue
            if not a.startswith("-"):
                ops.append(a)
            j += 1
        return ops[:1], dirs, cmds, gcwd

    revisions_first = sub in ("log", "show") or (sub == "diff" and "--no-index" not in rest)
    # Short options of these commands that take a value: required ones take the
    # rest of the cluster or the next word, optional ones only the rest.
    takes = {"grep": ("efmABC", ""), "format-patch": ("ov", "USGOMCBlX"),
             "archive": ("o", "")}.get(sub, ("", ""))
    pathspecs, pager_cmds = [], []
    j, seen_dashes = 0, False
    while j < len(rest):
        a, nxt = rest[j], rest[j + 1] if j + 1 < len(rest) else None
        if a == "--":
            if revisions_first:
                break
            seen_dashes = True
            j += 1
            continue
        if seen_dashes and sub == "grep":
            pathspecs.append(a)
        if a.startswith("--"):
            out_v = long_opt(a, "--output", 8)
            dir_v = long_opt(a, "--output-directory", 10) if sub == "format-patch" else None
            pager_v = long_opt(a, "--open-files-in-pager", 4) if sub == "grep" else None
            if sub in ("diff", "log", "show", "range-diff", "archive", "format-patch") and out_v is not None:
                if out_v:
                    files.append(out_v)
                elif "=" not in a and nxt is not None:
                    files.append(nxt)
                    j += 1
            elif dir_v is not None:
                if dir_v:
                    dirs.append(dir_v)
                elif "=" not in a and nxt is not None:
                    dirs.append(nxt)
                    j += 1
            elif pager_v:
                pager_cmds.append(pager_v)
        elif a.startswith("-") and len(a) > 1:
            required, optional = takes
            k = 1
            while k < len(a):
                c, tail = a[k], a[k + 1:]
                if sub == "grep" and c == "O":
                    if tail:
                        pager_cmds.append(tail)
                    break
                if c in required:
                    value = tail or nxt
                    if not tail:
                        j += 1
                    if c == "o" and value is not None:
                        (dirs if sub == "format-patch" else files).append(value)
                    break
                if c in optional:
                    break
                k += 1
        j += 1
    if pager_cmds:
        # The pager gets the matching files appended. A pathspec that names an
        # existing file is where its matches come from; anything else — no
        # pathspec, a directory, a glob, `:(magic)` — can match any tracked file,
        # so a harness file stands in: a writing pager (`sed -i`, `tee`) is seen,
        # a reading one (`less`) is not.
        def plain(p):
            return not re.search(r"[*?\[]", p) and not p.startswith(":") \
                and os.path.isfile(p if os.path.isabs(p) else os.path.join(gcwd, p))
        files_named = [p for p in pathspecs if plain(p)]
        if not pathspecs or len(files_named) < len(pathspecs):
            files_named.append(os.path.join(root, "CLAUDE.md"))
        tail = " ".join(shlex.quote(p) for p in files_named)
        cmds.extend(c + " " + tail for c in pager_cmds)
    return files, dirs, cmds, gcwd


def grep_lists(args):
    """grep prints file NAMES with -l/-L (also in a cluster like -rl), read
    like getopt: in `-el` the l is -e's pattern, not a flag."""
    for a in args:
        if a in ("--files-with-matches", "--files-without-match"):
            return True
        if a == "--":
            break
        if a.startswith("-") and not a.startswith("--"):
            for c in a[1:]:
                if c in "lL":
                    return True
                if c in "efmABCdDX":
                    break
    return False


def tokenize(cmd):
    """Shell tokens, quotes respected. punctuation_chars keeps the operators as
    tokens of their own, so `x|tee f` and `>CLAUDE.md` survive while a `|` inside
    a quoted commit message does not become a pipeline."""
    lex = shlex.shlex(cmd, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    try:
        return split_operators(list(lex))
    except ValueError:
        return cmd.split()


def split_operators(tokens):
    """A token of punctuation only that is no single operator — `);`, `));`,
    `)|` — becomes the operators it is made of, longest match first; without
    that, the body of `for d in $(ls /tmp/x*); do rm …` never became a segment."""
    out = []
    for t in tokens:
        if t in OPERATORS or not t or any(c not in "();<>|&" for c in t):
            out.append(t)
            continue
        while t:
            op = next((o for o in OPERATORS if t.startswith(o)), t[0])
            out.append(op)
            t = t[len(op):]
    return out


def quoted_ops(line):
    """The line with every word made only of quoted or escaped redirection
    characters (`"<"`, `'>'`, `\\<`) turned into a plain word: shlex drops the
    quotes, and such a word arrived as the bare operator. Read as a redirection
    it swallowed the word next to it (`git commit -m "<" -n`)."""
    out, start, content = [], 0, []
    quote, esc = None, False

    def close(end):
        chars = "".join(c for c, _ in content)
        if content and all(q for _, q in content) and all(c in "<>|&" for c in chars) \
                and any(c in "<>" for c in chars):
            out.append("'\x1e" + chars + "'")
        else:
            out.append(line[start:end])
        content.clear()

    for i, c in enumerate(line):
        if esc:
            content.append((c, True))
            esc = False
        elif c == "\\" and quote != "'":
            esc = True
        elif quote:
            if c == quote:
                quote = None
            else:
                content.append((c, True))
        elif c in "\"'":
            quote = c
        elif c.isspace() or c in ";&|()<>":
            close(i)
            out.append(c)
            start = i + 1
        else:
            content.append((c, False))
    close(len(line))
    return "".join(out)


def is_redirect(tok):
    # Input as well as output (R-0134): left in the segment, a `<` in front of
    # the verb hid it, and behind cp/mv `< /dev/null` became the destination.
    return ("<" in tok or ">" in tok) and all(c in "<>|&" for c in tok)


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
    arith = 0            # open parentheses of a `((…))` / `$((…))`
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
            elif arith:
                # Inside `((…))` / `$((…))` a `<<` or `<<=` is a shift, not a
                # here-doc (R-0133): read as one, it hid every line after it.
                arith += {"(": 1, ")": -1}.get(ch, 0)
            elif ch == "#" and (i == 0 or line[i - 1] in " \t;&|()<>"):
                # A comment, as bash reads one: a `#` at the start of a word.
                # A `((`, a `<<X` or a quote in it opens nothing; read as code,
                # they hid the lines below or flagged a here-doc body.
                break
            elif line[i:i + 2] == "((":
                arith = 2
                i += 2
                continue
            elif ch == "<" and line[i:i + 3] == "<<<":
                # A here-string: its word is data on THIS line, and no body
                # follows — read as `<<` it took `<` for a delimiter and hid
                # every line after it (R-0126).
                i += 3
                continue
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


def case_arm(seg, state):
    """The part of a segment that runs as a command. After `case w in` and after
    every `;;` a pattern comes first, up to its `)` — possibly on a line of its
    own, possibly split by `|` (`a|b)`). Returns [] for a pattern-only segment."""
    k = 0
    while k < len(seg) and (seg[k] in KEYWORDS or seg[k] in ("(", "{")):
        k += 1
    if k < len(seg) and seg[k] == "case":
        state["case"] = state["arm"] = True
        seg = seg[seg.index("in", k) + 1:] if "in" in seg[k:] else []
    elif k < len(seg) and seg[k] == "esac":
        state["case"] = state["arm"] = False
        return []
    if state["arm"]:
        if ")" not in seg:
            return []
        state["arm"] = False
        seg = seg[seg.index(")") + 1:]
    return seg


def scan(cmd, base, depth=0):
    if depth > 2:
        return
    cur = base
    # What one segment tells the next: the case syntax; the loops that are open,
    # each as (the temp glob it walks or None, the deletes seen when it opened);
    # the temp glob a pipe carries into the next segment.
    state = {"case": False, "arm": False, "loops": [], "pipe": None}
    for line in logical_lines(cmd):
        segment = []
        for tok in tokenize(quoted_ops(line)) + [";"]:
            if tok in SEPARATORS:
                # An empty segment (the `;` a line ends with) changes nothing.
                if segment:
                    cur = run_segment(case_arm(segment, state), cur, depth, state, tok)
                    if state["case"] and tok in (";;", ";&", ";;&"):
                        state["arm"] = True
                segment = []
            else:
                segment.append(tok)
    # A loop that is never closed still counts.
    for glob, seen in state["loops"]:
        if glob and len(deletes) > seen:
            tmp_hits.append(glob)


def run_segment(tok, cwd, depth, state, sep):
    """Record what this segment writes; return the cwd the NEXT one runs in.
    sep is the separator that ends it (`|` hands a temp glob on)."""
    piped, state["pipe"] = state["pipe"], None
    if not tok:
        return cwd

    # Redirections first, and they leave the token list with their word:
    # `cp a b > /dev/null` must not mistake /dev/null for the copy's destination.
    # Only `>` writes; `<`, `<&` and `<<<` read (`<>` does both, so it counts).
    clean, i = [], 0
    while i < len(tok):
        t = tok[i]
        # An input operator right before another operator is no redirection:
        # bash takes no operator as a redirection's word. A quoted `"<"` is a
        # word already (quoted_ops).
        if is_redirect(t) and ">" not in t and i + 1 < len(tok) and is_redirect(tok[i + 1]):
            clean.append(t)
            i += 1
            continue
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
    i, value_flags = 0, set()
    while i < len(clean):
        t = clean[i]
        if "=" in t and not t.startswith("-") and t.split("=")[0].isidentifier():
            i += 1
        elif t.startswith("-"):
            # A cluster is read like getopt, left to right: the first flag that
            # takes a value takes the rest of the word (`-uroot`), or the next
            # word when it ends the cluster (`sudo -nu root`).
            takes = t in value_flags
            if not takes and len(t) > 2 and t[1] != "-":
                for k, c in enumerate(t[1:], 1):
                    if "-" + c in value_flags:
                        takes = k == len(t) - 1
                        break
            i += 2 if takes else 1
        elif os.path.basename(t) in WRAPPERS:
            value_flags = WRAPPERS[os.path.basename(t)]
            i += 1
        elif t in KEYWORDS or DURATION.match(t):
            i += 1
        else:
            break
    # GIT_CONFIG_KEY_n / GIT_CONFIG_PARAMETERS are `git -c` by environment — as a
    # prefix, on their own (`X=…; export X`, `set -a; X=…`) or behind export.
    verb = os.path.basename(clean[i]) if i < len(clean) else ""
    args = clean[i + 1:]
    env_words = clean[:i] + (args if verb in ("export", "declare", "typeset", "local") else [])
    bypasses.extend(w for w in env_words if GIT_CONFIG_ENV.match(w) and "hookspath" in w.lower())
    if not verb:
        return cwd
    # After `--` every word is an operand: `rm -rf -- -home-x*` deletes -home-x*.
    end = args.index("--") if "--" in args else len(args)
    words = [a for a in args[:end] if not a.startswith("-")] + args[end + 1:]
    # The operands as bash hands them over: `rm CLAUDE.{md,x}` writes CLAUDE.md
    # (R-0125).
    # An empty alternative (`{a,}`) yields no word, as in bash.
    words = [e for w in words for e in brace_expand(w) if e]

    if verb == "git":
        hit = git_skips_hook(args)
        if hit:
            bypasses.append(hit)
        files, dirs, cmds, gcwd = git_writes(args, cwd)
        out.extend(rel(f, gcwd) for f in files)
        # format-patch writes NNNN-<subject>.patch into the directory, like `cp x dir/`.
        out.extend(rel(os.path.join(d, "0001-format-patch.patch"), gcwd) for d in dirs)
        # A pager command is scanned like `bash -c`, with the files it is handed.
        for c in cmds:
            scan(c, gcwd, depth + 1)

    # A temp glob reaches a delete by name; through a loop over it that deletes
    # in its body, however the body gets there (`rm "$d"`, `cd "$d" && rm ./*`,
    # `bash -c`) — `for d in /tmp/x*`, `… /tmp/x* | while read d`; or through a
    # pipe into `xargs rm`, from a lister or from the loop's `done`. A delete
    # after `done` is no part of the loop.
    selects = None
    if verb in DELETERS:
        deletes.append(verb)
        tmp_hits.extend(w for w in words if tmp_glob(w, cwd))
        if piped and "xargs" in (os.path.basename(t) for t in clean[:i]):
            tmp_hits.append(piped)
    elif verb == "find":
        is_delete, selects, starts = find_delete(args, cwd)
        if is_delete:
            deletes.append(verb)
            if selects is not None:
                tmp_hits.append(selects)
            taken.extend(p for w in starts for e in brace_expand(w) if e for p in taken_away(e, cwd))
    elif verb in ("for", "select"):
        globs = [w for w in args[args.index("in") + 1:] if tmp_glob(w, cwd)] if "in" in args else []
        state["loops"].append((globs[0] if globs else None, len(deletes)))
    elif verb == "read" and any(t in ("while", "until") for t in clean[:i]):
        state["loops"].append((piped, len(deletes)))
    elif verb == "done" and state["loops"]:
        glob, seen = state["loops"].pop()
        if glob and len(deletes) > seen:
            tmp_hits.append(glob)
        selects = glob
    if any(t in ("while", "until") for t in clean[:i]) and verb != "read":
        state["loops"].append((None, len(deletes)))   # a loop over nothing; `done` pops it
    if sep in PIPES:
        # Only a lister hands a glob on: `cat /tmp/*.list | xargs rm` reads them.
        listed = next((w for w in words if has_glob(w) and tmp_glob(w, cwd)), None) \
            if verb in ("ls", "echo", "printf") or verb == "grep" and grep_lists(args) else None
        state["pipe"] = piped or selects or listed

    if verb == "cd":
        return resolve(words[0], cwd) if words else cwd

    if verb in ("bash", "sh", "dash", "zsh"):
        # -c, but also -lc and friends: any flag carrying a c takes the next word
        # as a command string.
        seen = len(deletes)
        for j, a in enumerate(args):
            if a.startswith("-") and "c" in a:
                rest = [w for w in args[j + 1:] if not w.startswith("-")]
                if rest:
                    scan(rest[0], cwd, depth + 1)
                break
        # `… | xargs sh -c 'rm -rf "$@"' _` deletes what the pipe carries, like
        # `… | xargs rm`.
        if piped and len(deletes) > seen and "xargs" in (os.path.basename(t) for t in clean[:i]):
            tmp_hits.append(piped)
    elif verb == "sed" and any(
        a == "-i" or a.startswith("-i.") or a.startswith("--in-place") for a in args
    ):
        out.extend(rel(w, cwd) for w in words[1:])   # words[0] is sed's script
    elif verb == "tee":
        out.extend(rel(w, cwd) for w in words)
    elif verb in ("rm", "rmdir", "shred", "truncate", "unlink"):
        # Taking a harness file away is the most complete edit there is.
        out.extend(rel(w, cwd) for w in words)
        if verb != "truncate":
            taken.extend(p for w in words for p in taken_away(w, cwd))
    elif verb == "ln":
        # `ln -sf x CLAUDE.md` replaces the file with a link to something else.
        out.extend(rel(w, cwd) for w in words[1:] if len(words) > 1)
    elif verb == "dd":
        for a in args:
            if a.startswith("of="):
                out.append(rel(a[3:], cwd))
    elif verb in ("chmod", "chown", "chgrp"):
        # `chmod -x scripts/dev/hooks/pre-commit` disarms the hook as surely as
        # deleting it (R-0110). The mode, owner or group comes first unless
        # --reference names a file for it; a `-x` mode already left `words`.
        # getopt takes any unambiguous prefix of --reference (`--ref=`).
        ops = list(words)
        refs = [k for k, a in enumerate(args)
                if len(a.split("=", 1)[0]) >= 5 and "--reference".startswith(a.split("=", 1)[0])]
        if refs:
            k = refs[0]
            if "=" not in args[k] and k + 1 < len(args) and args[k + 1] in ops:
                ops.remove(args[k + 1])   # the reference file is only read
        elif ops and (verb != "chmod" or CHMOD_MODE.match(ops[0])):
            ops = ops[1:]
        out.extend(rel(w, cwd) for w in ops)
        taken.extend(p for w in ops for p in taken_away(w, cwd))
    elif verb in ("cp", "mv", "install"):
        # An explicit -t/--target-directory, or the last word, is the target.
        target = None
        for j, a in enumerate(args):
            if a == "-t" and j + 1 < len(args):
                target = args[j + 1]
            elif a.startswith("--target-directory="):
                target = a.split("=", 1)[1]
        sources = list(words)
        if target is not None and target in sources:
            sources.remove(target)    # `-t dir` is no source (`mv -t scripts/dev x`)
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
            taken.extend(p for w in sources for p in taken_away(w, cwd))
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

for w in dict.fromkeys(tmp_hits):
    print("T " + printable(w))
for w in dict.fromkeys(bypasses):
    print("B " + printable(w))
for p in dict.fromkeys(p for p in out if p):
    print("H " + p)
for p in dict.fromkeys(p for p in taken if p):
    print("A " + printable(p))
PY
)
targets() { python3 -c "$PARSE" "$ROOT"; }

# The list is shell `case` patterns, where `*` crosses `/` — `.claude/**` is the
# whole subtree, every other line is the file itself. A checkout without the
# list guards no harness paths; the temp rule does not need it.
match() {
  local path="$1" pattern
  [ -f "$PATHS" ] || return 1
  while IFS= read -r pattern; do
    case "$pattern" in ''|'#'*) continue ;; esac
    # shellcheck disable=SC2254  # the list IS patterns; that is the point
    case "$path" in $pattern) return 0 ;; esac
  done < "$PATHS"
  return 1
}

# The documented deny document. The text is escaped for JSON: a file name with
# a quote in it would otherwise produce a broken document, and a guard whose
# answer cannot be parsed is a guard that failed open.
deny() {
  local esc="${1//\\/\\\\}"
  esc="${esc//\"/\\\"}"
  # A control character (a tab in a file name) is no valid JSON string either.
  esc="$(printf '%s' "$esc" | LC_ALL=C tr '\001-\037' '?')"
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"%s"}}\n' "$esc"
}

# A path that is taken away — deleted, moved, chmod'ed, a deleting find's start
# — takes everything below it along: it hits when a pattern lies below it
# (`rm -rf scripts/dev/hooks`, `rm -rf .claude`, R-0127). The checkout root
# holds them all. Only for these verbs; every other write is the path itself.
holds_harness() {
  local path="$1" pattern
  [ -f "$PATHS" ] || return 1
  while IFS= read -r pattern; do
    case "$pattern" in ''|'#'*) continue ;; esac
    [ "$path" = "." ] && return 0
    case "$pattern" in "$path"/*) return 0 ;; esac
  done < "$PATHS"
  return 1
}

TMP_HIT="" BYPASS="" HIT=""
while IFS= read -r line; do
  case "$line" in
    "T "*) [ -n "$TMP_HIT" ] || TMP_HIT="${line#T }" ;;
    "B "*) [ -n "$BYPASS" ] || BYPASS="${line#B }" ;;
    "H "*) if [ -z "$HIT" ] && match "${line#H }"; then HIT="${line#H }"; fi ;;
    "A "*)
      # A taken path is a harness path itself (`find .claude/skills -delete`)
      # or holds them.
      if [ -z "$HIT" ] && match "${line#A }"; then HIT="${line#A }"
      elif [ -z "$HIT" ] && holds_harness "${line#A }"; then HIT="${line#A } (holds harness paths)"; fi ;;
  esac
done < <(targets)

# No mode, no kill switch: the one rule of this hook that also binds the model
# in an interactive session (Kevin, 2026-09-27).
if [ -n "$TMP_HIT" ]; then
  deny "glob delete in a shared temp directory, or of one: $TMP_HIT — refused in every mode; delete your own directories by their full path, never with a glob (create them with mktemp -d -p <your dir>)"
  exit 0
fi
if [ -n "$BYPASS" ]; then
  deny "pre-commit bypass: $BYPASS — refused in every mode; the hook runs review.sh sec --staged, fix what it reports instead (R-0102)"
  exit 0
fi

[ -n "$HIT" ] || exit 0

if [ "${AH_AUTONOMOUS:-0}" = "1" ] && [ ! -e "$MARKER" ]; then
  deny "harness path: $HIT (autonomous run; bash scripts/dev/harness.sh off lifts this)"
else
  echo "harness-guard: $HIT is a harness path — change it deliberately, not in passing" >&2
fi
exit 0
