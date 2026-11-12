#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# cache_settings.sh [--uncached <workflow>]… [--tag-uncached <workflow>]… <workflow>… — the cache settings ci-9 relies on, per step:
#   - every Swatinem/rust-cache step sets `cache-bin: false` in its `with:` block, so no tool
#     binary (and no .crates.toml that makes `cargo install` skip the build) comes back from a
#     cache;
#   - no rust-cache `cache-directories` and no actions/cache `path` names .cargo/bin;
#   - every cache of ~/.cache/ms-playwright keys on hashFiles(…) and has no restore-keys,
#     so only an exact entry for this lockfile is restored.
# A workflow given with --uncached (release.yml, R-1288) restores no cache at all: there every
# Swatinem/rust-cache and actions/cache step is a violation, setup-node needs
# `package-manager-cache: false` and no `cache:`, setup-go needs `cache: false`, and setup-python
# or setup-java may not set `cache:`, setup-dotnet no `cache:` other than false, setup-uv needs
# `enable-cache: false`, setup-ruby no `bundler-cache:` other than false, and
# docker/build-push-action needs `no-cache: true` and no `cache-from`/`cache-to`.
# A workflow given with --tag-uncached (docker.yml, R-1349) caches on main but not on a tag: the
# rules of --uncached hold there, except that every docker/build-push-action step sets exactly
# `no-cache: ${{ startsWith(github.ref, 'refs/tags/') }}` and a `cache-from`/`cache-to` is
# `${{ !startsWith(github.ref, 'refs/tags/') && <value without ||> || '' }}`.
# In both, docker/bake-action and a `docker build`, `docker buildx build` or `docker buildx bake`
# in a run: step are violations: their cache settings are not read.
# A `with:` written as a flow mapping (`with: { … }`, or `{` on the line below) is a violation
# everywhere: it is not read.
# A violation is printed as a GitHub error annotation with file and line; exit 1 then.
set -euo pipefail

usage() { echo "usage: cache_settings.sh [--uncached <workflow>]… [--tag-uncached <workflow>]… <workflow>…" >&2; exit 2; }
files=() modes=()
while [ "$#" -gt 0 ]; do
    case "$1" in
    --uncached)
        [ "$#" -ge 2 ] || usage
        files+=("$2") modes+=(1)
        shift 2
        ;;
    --tag-uncached)
        [ "$#" -ge 2 ] || usage
        files+=("$2") modes+=(2)
        shift 2
        ;;
    -*) usage ;;
    *)
        files+=("$1") modes+=(0)
        shift
        ;;
    esac
done
[ "${#files[@]}" -ge 1 ] || usage

bad=0
for i in "${!files[@]}"; do
    f=${files[$i]}
    [ -r "$f" ] || { echo "cache_settings.sh: cannot read $f" >&2; exit 2; }
    # A step runs from its `- ` line to the next non-blank line indented no deeper than that
    # dash. Comment lines never count as settings.
    out=$(awk -v file="$f" -v mode="${modes[$i]}" '
        BEGIN { dockerbuild = "(^|[^[:alnum:]_.-])docker[[:space:]]+((buildx|compose|image|builder)[[:space:]]+)?(build|bake)([[:space:];|&)]|$)" }
        function indent(s) { match(s, /^ */); return RLENGTH }
        function keyof(s) { if (!match(s, /^[ ]*[A-Za-z0-9_-]+:/)) return ""; s = substr(s, 1, RLENGTH - 1); sub(/^[ ]*/, "", s); return s }
        function check() {
            if (start == 0) return
            if (rust && !nobin)
                printf "::error file=%s,line=%d::rust-cache step without cache-bin: false\n", file, start
            if (rust && bindir)
                printf "::error file=%s,line=%d::rust-cache cache-directories names .cargo/bin\n", file, start
            if (acache && binpath)
                printf "::error file=%s,line=%d::actions/cache path names .cargo/bin\n", file, start
            if (flow)
                printf "::error file=%s,line=%d::with: as a flow mapping is not checked, write it as a block\n", file, start
            if (mode) {
                if (rust || acache)
                    printf "::error file=%s,line=%d::cache step in a workflow that runs without caches\n", file, start
                if (snode && (hascache || !pmfalse))
                    printf "::error file=%s,line=%d::setup-node without package-manager-cache: false or with cache:\n", file, start
                if (sgo && !cachefalse)
                    printf "::error file=%s,line=%d::setup-go without cache: false\n", file, start
                if (spyjava && hascache)
                    printf "::error file=%s,line=%d::setup step with cache: in a workflow that runs without caches\n", file, start
                if (suv && !uvoff)
                    printf "::error file=%s,line=%d::setup-uv without enable-cache: false\n", file, start
                if (sruby && bundler)
                    printf "::error file=%s,line=%d::setup-ruby with bundler-cache in a workflow that runs without caches\n", file, start
                if (mode == 2 && bpa && (!notag || unguarded))
                    printf "::error file=%s,line=%d::build-push-action not switched off on tags (no-cache/cache-from/cache-to)\n", file, start
                if (mode == 1 && bpa && (bcache || !nocache))
                    printf "::error file=%s,line=%d::build-push-action with cache-from/cache-to or without no-cache: true\n", file, start
                if (bake)
                    printf "::error file=%s,line=%d::docker/bake-action is not checked, build with build-push-action\n", file, start
                if (runbuild)
                    printf "::error file=%s,line=%d::docker build/bake in a run: step is not checked, build with build-push-action\n", file, start
            }
            if (pw && !hashed)
                printf "::error file=%s,line=%d::ms-playwright cache whose key does not use hashFiles(\n", file, start
            if (pw && restore)
                printf "::error file=%s,line=%d::ms-playwright cache with restore-keys\n", file, start
        }
        {
            line = $0
            if (line ~ /^[ ]*$/ || line ~ /^[ ]*#/) next
            ind = indent(line)
            if (start && ind <= dash && line !~ /^[ ]*- /) { check(); start = 0 }
            first = 0
            # A dash deeper than the step is a list inside it (a path list), not a new step.
            if (line ~ /^[ ]*- / && (!start || ind <= dash)) {
                check()
                # The step keys sit where the first key after the dash starts.
                match(line, /^[ ]*-[ ]+/)
                start = NR; dash = ind; keyind = RLENGTH; first = 1
                rust = acache = nobin = bindir = binpath = pw = hashed = restore = 0
                snode = sgo = spyjava = hascache = cachefalse = pmfalse = 0
                suv = uvoff = sruby = bundler = bpa = bcache = nocache = flow = 0
                notag = unguarded = bake = runbuild = 0
                blk = ""; wkey = ""; withind = 0
                sub(/^[ ]*-[ ]+/, "", line)
            }
            if (!start) next
            sub(/[ ]+#.*$/, "", line)
            # The with: block is what lies deeper than the step keys under `with:`. A list item at
            # the height of its key belongs to that key.
            if (!first && ind == keyind && line ~ /^[ ]*- /) {
                # a list under a step key: nothing to read
            } else if (first || ind == keyind) {
                k = keyof(line)
                if (k == "with" && line ~ /^[ ]*with:[ ]*[{]/) flow = 1
                blk = k; wkey = ""; withind = 0
                if (k == "uses") {
                    u = tolower(line)
                    sub(/^[ ]*uses:[ ]*["\047]?/, "", u)
                    if (u ~ /^swatinem\/rust-cache@/) rust = 1
                    if (u ~ /^actions\/cache(\/restore|\/save)?@/) acache = 1
                    if (u ~ /^actions\/setup-node@/) snode = 1
                    if (u ~ /^actions\/setup-go@/) sgo = 1
                    if (u ~ /^actions\/setup-(python|java|dotnet)@/) spyjava = 1
                    if (u ~ /^astral-sh\/setup-uv@/) suv = 1
                    if (u ~ /^ruby\/setup-ruby@/) sruby = 1
                    if (u ~ /^docker\/build-push-action@/) bpa = 1
                    if (u ~ /^docker\/bake-action(\/[^@]*)?@/) bake = 1
                }
                if (k == "run" && line ~ dockerbuild) runbuild = 1
            } else if (ind > keyind && blk == "run") {
                if (line ~ dockerbuild) runbuild = 1
            } else if (ind > keyind && blk == "with") {
                # A flow mapping may also start on the line below `with:`.
                if (!withind && line ~ /^[ ]*[{]/) flow = 1
                if (!withind) withind = ind
                if (ind == withind && line !~ /^[ ]*- /) {
                    wkey = keyof(line)
                    if (line ~ /^[ ]*cache-bin:[ ]*["\047]?false["\047]?[ ]*$/) nobin = 1
                    if (wkey == "cache") {
                        if (line ~ /^[ ]*cache:[ ]*["\047]?false["\047]?[ ]*$/) cachefalse = 1
                        else hascache = 1
                    }
                    if (line ~ /^[ ]*package-manager-cache:[ ]*["\047]?false["\047]?[ ]*$/) pmfalse = 1
                    if (line ~ /^[ ]*enable-cache:[ ]*["\047]?false["\047]?[ ]*$/) uvoff = 1
                    if (wkey == "bundler-cache" && line !~ /^[ ]*bundler-cache:[ ]*["\047]?false["\047]?[ ]*$/) bundler = 1
                    if (wkey == "cache-from" || wkey == "cache-to") {
                        bcache = 1
                        # A further || in the middle would give the tag a value of its own.
                        if (line !~ /^[ ]*cache-(from|to):[ ]*\$\{\{ !startsWith\(github\.ref, \047refs\/tags\/\047\) && [^|]* \|\| \047\047 \}\}[ ]*$/) unguarded = 1
                    }
                    if (line ~ /^[ ]*no-cache:[ ]*\$\{\{ startsWith\(github\.ref, \047refs\/tags\/\047\) \}\}[ ]*$/) notag = 1
                    if (line ~ /^[ ]*no-cache:[ ]*["\047]?true["\047]?[ ]*$/) nocache = 1
                }
                if (line ~ /\.cargo\/bin/) {
                    if (wkey == "cache-directories") bindir = 1
                    if (wkey == "path") binpath = 1
                }
            }
            if (line ~ /ms-playwright/) pw = 1
            if (line ~ /^[ ]*key:.*hashFiles\(/) hashed = 1
            if (line ~ /^[ ]*restore-keys:/) restore = 1
        }
        END { check() }
    ' "$f")
    if [ -n "$out" ]; then
        printf '%s\n' "$out"
        bad=1
    fi
done

if [ "$bad" -ne 0 ]; then
    exit 1
fi
echo "cache_settings: ok (${#files[@]})"
