#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Hermetic test of apt_archives_verify.sh: a stub apt-cache stands in for the package index.
# Runs in the CI job ops-scripts.

set -uo pipefail

here=$(cd "$(dirname "$0")" && pwd)
verify="$here/apt_archives_verify.sh"
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT

passed=0 failed=0
check() { # check <name> <expected> <actual>
    if [ "$2" = "$3" ]; then
        passed=$((passed + 1))
    else
        failed=$((failed + 1))
        echo "FAIL $1: expected '$2', got '$3'" >&2
    fi
}
present() { [ -e "$work/arch/$1" ] || [ -L "$work/arch/$1" ] && echo yes || echo no; }

mkdir -p "$work/bin" "$work/arch/partial"
printf 'good\n' >"$work/arch/libfoo_1.2-3_amd64.deb"
printf 'evil\n' >"$work/arch/libbar_4.5_amd64.deb"
printf 'epoch\n' >"$work/arch/libbaz_1%3a2.0_all.deb"
printf 'gone\n' >"$work/arch/libold_0.9_amd64.deb"
printf 'odd\n' >"$work/arch/noversion.deb"
# What else a restored cache may carry: a half download, a link named like a package, a
# directory named like one, a foreign file, a hidden one.
printf 'half\n' >"$work/arch/partial/libfoo_1.3_amd64.deb"
printf 'outside\n' >"$work/outside.deb"
ln -s "$work/outside.deb" "$work/arch/liblink_1.0_amd64.deb"
mkdir "$work/arch/libdir_1.0_amd64.deb"
printf 'x\n' >"$work/arch/notes.txt"
printf 'x\n' >"$work/arch/.hidden"

sum() { sha256sum "$work/arch/$1" | cut -d' ' -f1; }
# The index: libfoo and libbaz as they are; libbar with the hash of another content;
# libold not at all. The stub answers only the exact "<pkg>=<version>" apt-cache gets.
cat >"$work/bin/apt-cache" <<EOF
#!/usr/bin/env bash
[ "\$1" = show ] && [ "\$2" = -- ] || exit 100
case "\$3" in
libfoo=1.2-3) printf 'Package: libfoo\nSHA256: %s\n\nPackage: libfoo\nSHA256: 00\n' "$(sum libfoo_1.2-3_amd64.deb)" ;;
libbar=4.5) printf 'Package: libbar\nSHA256: %s\n' "$(printf 'real\n' | sha256sum | cut -d' ' -f1)" ;;
libbaz=1:2.0) printf 'Package: libbaz\nSHA256: %s\n' "$(sum 'libbaz_1%3a2.0_all.deb')" ;;
*) echo "E: No packages found" >&2; exit 100 ;;
esac
EOF
chmod +x "$work/bin/apt-cache"

out=$(PATH="$work/bin:$PATH" bash "$verify" "$work/arch") rc=$? || true
check "exit" 0 "$rc"
check "matching hash: kept" yes "$(present libfoo_1.2-3_amd64.deb)"
check "other hash than the index: deleted" no "$(present libbar_4.5_amd64.deb)"
check "epoch in the file name: kept" yes "$(present 'libbaz_1%3a2.0_all.deb')"
check "not in the index: deleted" no "$(present libold_0.9_amd64.deb)"
check "no version in the name: deleted" no "$(present noversion.deb)"
check "partial/ emptied" no "$(present partial/libfoo_1.3_amd64.deb)"
check "partial/ stays a directory" yes "$([ -d "$work/arch/partial" ] && [ ! -L "$work/arch/partial" ] && echo yes || echo no)"
check "link named like a package: deleted" no "$(present liblink_1.0_amd64.deb)"
check "link target outside: untouched" yes "$([ -e "$work/outside.deb" ] && echo yes || echo no)"
check "directory named like a package: deleted" no "$(present libdir_1.0_amd64.deb)"
check "foreign file: deleted" no "$(present notes.txt)"
check "hidden file: deleted" no "$(present .hidden)"
check "summary" "apt_archives_verify.sh: 2 kept, 3 dropped, 5 other removed" "$out"

# partial as a link: the link goes, a real directory takes its place, the target stays.
mkdir -p "$work/arch2" "$work/elsewhere"
printf 'x\n' >"$work/elsewhere/keep"
ln -s "$work/elsewhere" "$work/arch2/partial"
rc=0; out=$(PATH="$work/bin:$PATH" bash "$verify" "$work/arch2") || rc=$?
check "partial as a link: exit and summary" "0:apt_archives_verify.sh: 0 kept, 0 dropped, 1 other removed" "$rc:$out"
check "partial as a link: now a directory" yes "$([ -d "$work/arch2/partial" ] && [ ! -L "$work/arch2/partial" ] && echo yes || echo no)"
check "partial as a link: target untouched" yes "$([ -e "$work/elsewhere/keep" ] && echo yes || echo no)"

# The cache directory itself as a link: the link goes, a real directory takes its place.
mkdir -p "$work/elsewhere2"
printf 'x\n' >"$work/elsewhere2/keep_1.0_amd64.deb"
ln -s "$work/elsewhere2" "$work/arch3"
rc=0; out=$(PATH="$work/bin:$PATH" bash "$verify" "$work/arch3") || rc=$?
check "directory as a link: exit and summary" "0:apt_archives_verify.sh: 0 kept, 0 dropped, 1 other removed" "$rc:$out"
check "directory as a link: now a directory with partial/" yes "$([ -d "$work/arch3/partial" ] && [ ! -L "$work/arch3" ] && echo yes || echo no)"
check "directory as a link: target untouched" yes "$([ -e "$work/elsewhere2/keep_1.0_amd64.deb" ] && echo yes || echo no)"

rc=0; out=$(PATH="$work/bin:$PATH" bash "$verify" "$work/empty-does-not-exist") || rc=$?
check "missing directory: nothing to keep" "0:apt_archives_verify.sh: 0 kept, 0 dropped, 0 other removed" "$rc:$out"

rc=0; bash "$verify" 2>/dev/null || rc=$?
check "usage: fails" yes "$([ "$rc" -ne 0 ] && echo yes || echo no)"

echo "apt_archives_verify_test.sh: $passed passed, $failed failed"
[ "$failed" -eq 0 ]
