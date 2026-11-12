#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# tauri_cli_pins.sh <workflow…> — every `cargo install … tauri-cli` in the given workflow files
# must name a plain version (`--version X.Y.Z`, quoted or not), and all of them the same one;
# each file must hold at least one. The 'Keep in lockstep' comments next to the pins are not
# enforced anywhere else (4.22). Counted are all non-comment lines, also inside a `run: |`
# block, with backslash continuations joined first.
set -euo pipefail

[ "$#" -ge 1 ] || { echo "usage: tauri_cli_pins.sh <workflow…>" >&2; exit 2; }

pin_lines() {
    sed -e ':a' -e '/\\$/N; s/\\\n//; ta' -- "$1" |
        grep -vE '^[[:space:]]*#' |
        grep -E 'cargo[[:space:]]+install[[:space:]]' |
        grep -E '(^|[[:space:]"])tauri-cli([[:space:]"@]|$)' || true
}

all="" counts="" bad=0
for f in "$@"; do
    lines=$(pin_lines "$f")
    n=$(grep -c . <<<"$lines" || true)
    counts="$counts$(basename -- "$f") $n, "
    [ "$n" -ge 1 ] || bad=1
    all="$all$lines"$'\n'
done
pins=$(grep . <<<"$all" |
    sed -E 's/.*--version[[:space:]]+"?([0-9]+\.[0-9]+\.[0-9]+)"?([[:space:]].*)?$/\1/;t;s/.*/none/' || true)
vers=$(sort -u <<<"$pins" | grep . | tr '\n' ' ' || true)
echo "tauri-cli pins: ${counts}versions: $vers"
if [ "$bad" -ne 0 ] || grep -qx none <<<"$pins" || [ "$(sort -u <<<"$pins" | grep -c .)" -ne 1 ]; then
    echo "::error::tauri-cli pins must all name the same version (${counts}versions: $vers)"
    exit 1
fi
