#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# cache_settings.sh <workflow…> — the cache settings ci-9 relies on, per step:
#   - every Swatinem/rust-cache step sets `cache-bin: false`, so no tool binary (and no
#     .crates.toml that makes `cargo install` skip the build) comes back from a cache;
#   - every cache of ~/.cache/ms-playwright keys on hashFiles(…) and has no restore-keys,
#     so only an exact entry for this lockfile is restored.
# A violation is printed as a GitHub error annotation with file and line; exit 1 then.
set -euo pipefail

[ "$#" -ge 1 ] || { echo "usage: cache_settings.sh <workflow…>" >&2; exit 2; }

bad=0
for f in "$@"; do
    [ -r "$f" ] || { echo "cache_settings.sh: cannot read $f" >&2; exit 2; }
    # A step runs from its `- ` line to the next non-blank line indented no deeper than that
    # dash. Comment lines never count as settings.
    out=$(awk -v file="$f" '
        function indent(s) { match(s, /^ */); return RLENGTH }
        function check() {
            if (start == 0) return
            if (rust && !nobin)
                printf "::error file=%s,line=%d::rust-cache step without cache-bin: false\n", file, start
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
            if (line ~ /^[ ]*- /) {
                check()
                start = NR; dash = ind
                rust = nobin = pw = hashed = restore = 0
                sub(/^[ ]*- /, "", line)
            }
            if (!start) next
            sub(/[ ]+#.*$/, "", line)
            if (line ~ /^[ ]*uses:[ ]*Swatinem\/rust-cache@/) rust = 1
            if (line ~ /^[ ]*cache-bin:[ ]*["\047]?false["\047]?[ ]*$/) nobin = 1
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
echo "cache_settings: ok ($#)"
