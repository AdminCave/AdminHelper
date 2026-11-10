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
present() { [ -e "$work/arch/$1" ] && echo yes || echo no; }

mkdir -p "$work/bin" "$work/arch/partial"
printf 'good\n' >"$work/arch/libfoo_1.2-3_amd64.deb"
printf 'evil\n' >"$work/arch/libbar_4.5_amd64.deb"
printf 'epoch\n' >"$work/arch/libbaz_1%3a2.0_all.deb"
printf 'gone\n' >"$work/arch/libold_0.9_amd64.deb"
printf 'odd\n' >"$work/arch/noversion.deb"

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
check "partial/ untouched" yes "$(present partial)"
check "summary" "apt_archives_verify.sh: 2 kept, 3 dropped" "$out"

rc=0; out=$(PATH="$work/bin:$PATH" bash "$verify" "$work/empty-does-not-exist") || rc=$?
check "missing directory: nothing to keep" "0:apt_archives_verify.sh: 0 kept, 0 dropped" "$rc:$out"

rc=0; bash "$verify" 2>/dev/null || rc=$?
check "usage: fails" yes "$([ "$rc" -ne 0 ] && echo yes || echo no)"

echo "apt_archives_verify_test.sh: $passed passed, $failed failed"
[ "$failed" -eq 0 ]
