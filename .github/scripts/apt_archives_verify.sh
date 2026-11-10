#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# apt_archives_verify.sh <dir> — keeps a .deb in <dir> only when its SHA256 is the one the
# signed package index names for it, and deletes every other one. For the archive caches of
# the CI jobs: apt takes a file already in Dir::Cache::Archives when its size matches the
# index, without hashing it, so a restored cache is checked against the index first. Run it
# after `apt-get update` and before the download.
set -euo pipefail

dir=${1:?usage: apt_archives_verify.sh <dir>}
shopt -s nullglob
kept=0 dropped=0
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
echo "apt_archives_verify.sh: $kept kept, $dropped dropped"
