#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# apt_archives_verify.sh <dir> — keeps a .deb in <dir> only when its SHA256 is the one the
# signed package index names for it, and deletes every other one. For the archive caches of
# the CI jobs: apt takes a file already in Dir::Cache::Archives when its size matches the
# index, without hashing it, so a restored cache is checked against the index first. Run it
# after `apt-get update` and before the download. Everything else a restored cache may carry
# goes too: the content of partial/, links, directories and other files, and a link in place
# of <dir> or partial/ (only the link, never its target); partial/ stays as an empty directory.
set -euo pipefail

dir=${1:?usage: apt_archives_verify.sh <dir>}
shopt -s nullglob dotglob
kept=0 dropped=0 other=0
if [ -L "$dir" ]; then
    rm -f -- "$dir"
    other=$((other + 1))
    mkdir -p -- "$dir/partial"
fi
if [ -d "$dir" ]; then
    for e in "$dir"/*; do
        [ -L "$e" ] || case $e in
        "$dir"/partial) [ -d "$e" ] && continue ;;
        *.deb) [ -f "$e" ] && continue ;;
        esac
        rm -rf -- "$e"
        other=$((other + 1))
    done
    # Globbed only now: before the loop, a link named partial would have led it elsewhere.
    for e in "$dir"/partial/*; do
        rm -rf -- "$e"
        other=$((other + 1))
    done
    mkdir -p -- "$dir/partial"
fi
for f in "$dir"/*.deb; do
    name=${f##*/}
    name=${name%.deb}
    pkg=${name%%_*}
    rest=${name#*_}
    ver=${rest%_*}
    # apt names an epoch "1%3a2.0" in the file name.
    ver=${ver//%3a/:}
    have=$(sha256sum -- "$f" | cut -d' ' -f1)
    index=$(apt-cache show -- "$pkg=$ver" 2>/dev/null || true)
    if [ "$rest" != "$name" ] && grep -qxF "SHA256: $have" <<<"$index"; then
        kept=$((kept + 1))
    else
        rm -f -- "$f"
        dropped=$((dropped + 1))
    fi
done
echo "apt_archives_verify.sh: $kept kept, $dropped dropped, $other other removed"
