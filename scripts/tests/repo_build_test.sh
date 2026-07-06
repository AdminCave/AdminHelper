#!/usr/bin/env bash
#
# repo_build_test.sh — verifies apps/agent/build-repo.sh end to end with a
# throwaway GPG key and dummy .deb/.rpm: the built APT + YUM trees must be
# structurally complete and carry valid signatures in the right key formats.
# Runs once per key type (rsa + ed25519) — build-repo.sh is key-type agnostic and
# the maintainer's real repo key is ed25519, so both must pass identically.
#
# Runs natively when all tools are present (dpkg-dev, apt-utils, createrepo-c,
# rpm, gnupg). createrepo_c ships only on rpm distros / Debian universe, so when
# it is missing the test re-execs itself inside an ubuntu container that installs
# the toolchain — identical to what release.yml does in CI. Set AH_REPO_TEST_NATIVE=1
# to force the native path (used by the container re-exec to avoid a loop).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD_REPO="${REPO_ROOT}/apps/agent/build-repo.sh"
VERSION="9.9.9"
KEY_ID="repo-test@adminhelper.invalid"
IMAGE="ubuntu:24.04"

# --- Container re-exec when createrepo_c is unavailable ----------------------
if ! command -v createrepo_c >/dev/null 2>&1 && [ "${AH_REPO_TEST_NATIVE:-0}" != 1 ]; then
    command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1 || {
        echo "FEHLER: createrepo_c fehlt und Docker ist nicht nutzbar — Test kann die RPM-Repo-Seite nicht verifizieren." >&2
        echo "        Installiere 'createrepo-c' (apt) oder starte Docker." >&2
        exit 1
    }
    echo "[repo-test] createrepo_c fehlt lokal → Re-Exec im Container ${IMAGE} ..."
    exec docker run --rm -v "${REPO_ROOT}:/src:ro" -w /src "$IMAGE" bash -c '
        set -e
        export DEBIAN_FRONTEND=noninteractive
        apt-get update -qq
        apt-get install -y -qq dpkg-dev apt-utils createrepo-c rpm gnupg gzip >/dev/null
        export AH_REPO_TEST_NATIVE=1
        exec bash scripts/tests/repo_build_test.sh
    '
fi

# --- Native run -------------------------------------------------------------
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }
ok()   { echo "  ok: $*"; }

echo "[repo-test] Werkzeuge: $(command -v dpkg-scanpackages apt-ftparchive createrepo_c rpm gpg | tr '\n' ' ')"

# 1) Dummy .deb (valid metadata, trivial payload) — key-independent, built once.
echo "[repo-test] Baue Dummy-.deb ..."
DEBDIR="${WORK}/deb/adminhelper-agent_${VERSION}_amd64"
mkdir -p "${DEBDIR}/DEBIAN" "${DEBDIR}/usr/share/adminhelper-agent"
cat > "${DEBDIR}/DEBIAN/control" <<EOF
Package: adminhelper-agent
Version: ${VERSION}
Architecture: amd64
Maintainer: Repo Test <${KEY_ID}>
Section: net
Priority: optional
Description: dummy package for repo_build_test
EOF
echo "marker" > "${DEBDIR}/usr/share/adminhelper-agent/marker"
DEB_FILE="${WORK}/adminhelper-agent_${VERSION}_amd64.deb"
dpkg-deb --root-owner-group --build "$DEBDIR" "$DEB_FILE" >/dev/null

# 2) Dummy .rpm (x86_64, no debuginfo just like the real spec) — built once.
echo "[repo-test] Baue Dummy-.rpm ..."
RPMTOP="${WORK}/rpmbuild"
mkdir -p "${RPMTOP}"/{BUILD,RPMS,SOURCES,SPECS,SRPMS}
cat > "${RPMTOP}/SPECS/adminhelper-agent.spec" <<EOF
Name:           adminhelper-agent
Version:        ${VERSION}
Release:        1
Summary:        dummy package for repo_build_test
License:        GPL-3.0-or-later
%global debug_package %{nil}
%description
dummy
%install
mkdir -p %{buildroot}/usr/share/adminhelper-agent
echo marker > %{buildroot}/usr/share/adminhelper-agent/marker
%files
/usr/share/adminhelper-agent/marker
EOF
rpmbuild --define "_topdir ${RPMTOP}" -bb "${RPMTOP}/SPECS/adminhelper-agent.spec" >/dev/null 2>&1
RPM_FILE="$(ls "${RPMTOP}"/RPMS/*/adminhelper-agent-${VERSION}-1.*.rpm | head -1)"

# 3) Build + verify the repo for ONE gpg key type (fresh keyring + output tree).
verify_for_keytype() {
    local keyspec="$1" label="$2" fpr OUT APT RPM_REPO rpmpkg rpmdb pkgsha f
    echo "[repo-test] === Schluesseltyp ${label} (${keyspec}) ==="
    export GNUPGHOME="${WORK}/gnupg-${label}"
    mkdir -p "$GNUPGHOME"; chmod 700 "$GNUPGHOME"
    gpg --batch --passphrase '' --quick-generate-key \
        "AdminHelper Repo Test <${KEY_ID}>" "$keyspec" sign 0 >/dev/null 2>&1
    fpr="$(gpg --list-secret-keys --with-colons | awk -F: '/^fpr:/{print $10; exit}')"

    OUT="${WORK}/repo-${label}"
    ( cd "$WORK"
      VERSION="$VERSION" REPO_GPG_KEY_ID="$fpr" OUT_DIR="$OUT" \
          DEB="$DEB_FILE" RPM="$RPM_FILE" bash "$BUILD_REPO" >/dev/null )
    APT="${OUT}/apt"; RPM_REPO="${OUT}/rpm"

    # APT side ----------------------------------------------------------------
    for f in "pool/main/adminhelper-agent_${VERSION}_amd64.deb" \
             "dists/stable/main/binary-amd64/Packages" "dists/stable/main/binary-amd64/Packages.gz" \
             "dists/stable/Release" "dists/stable/InRelease" "dists/stable/Release.gpg" \
             "adminhelper-archive-keyring.gpg"; do
        [ -s "${APT}/${f}" ] || fail "[$label] APT-Datei fehlt/leer: $f"
    done
    grep -q "^Package: adminhelper-agent$" "${APT}/dists/stable/main/binary-amd64/Packages" \
        || fail "[$label] Packages enthält das Paket nicht"
    grep -q "^Filename: pool/main/adminhelper-agent_${VERSION}_amd64.deb$" \
        "${APT}/dists/stable/main/binary-amd64/Packages" || fail "[$label] Packages: Filename-Pfad falsch"
    # Release must carry the Packages SHA256 (chain root → package hash).
    pkgsha=$(sha256sum "${APT}/dists/stable/main/binary-amd64/Packages" | cut -d' ' -f1)
    grep -q "$pkgsha" "${APT}/dists/stable/Release" || fail "[$label] Release deckt Packages-SHA256 nicht"
    grep -q "^SHA256:" "${APT}/dists/stable/Release" || fail "[$label] Release ohne SHA256-Sektion"
    # Release identity: the deb822 source binds to Origin/Suite/Codename; a changed
    # REPO_SUITE would silently break every installed apt source (6.69).
    grep -q '^Origin: AdminHelper$' "${APT}/dists/stable/Release" || fail "[$label] Release Origin falsch"
    grep -q '^Suite: stable$'       "${APT}/dists/stable/Release" || fail "[$label] Release Suite falsch"
    grep -q '^Codename: stable$'    "${APT}/dists/stable/Release" || fail "[$label] Release Codename falsch"
    # Valid-Until bounds a freeze/replay attack on the certless repo plane (3.10); assert
    # it exists AND is in apt's RFC 2822 English form (LC_ALL=C), not a localized date.
    grep -qE '^Valid-Until: (Mon|Tue|Wed|Thu|Fri|Sat|Sun), ' "${APT}/dists/stable/Release" || fail "[$label] Release Valid-Until fehlt/localized"
    gpg --verify "${APT}/dists/stable/InRelease" >/dev/null 2>&1 \
        || fail "[$label] InRelease-Signatur ungültig"
    gpg --verify "${APT}/dists/stable/Release.gpg" "${APT}/dists/stable/Release" >/dev/null 2>&1 \
        || fail "[$label] Release.gpg-Signatur ungültig"
    # apt keyring must be DEARMORED (binary), not ASCII-armored.
    head -c 40 "${APT}/adminhelper-archive-keyring.gpg" | grep -q "BEGIN PGP" \
        && fail "[$label] apt-Keyring ist armored — muss dearmored (binär) sein"
    ok "[$label] APT: Baum + Signaturen (InRelease/Release.gpg) + dearmored Keyring"

    # RPM side ----------------------------------------------------------------
    rpmpkg="${RPM_REPO}/$(basename "$RPM_FILE")"
    for f in "$rpmpkg" "${RPM_REPO}/repodata/repomd.xml" \
             "${RPM_REPO}/repodata/repomd.xml.asc" "${RPM_REPO}/RPM-GPG-KEY-adminhelper"; do
        [ -s "$f" ] || fail "[$label] RPM-Datei fehlt/leer: $f"
    done
    # Package signature: import the key into a scratch rpmdb, then checksig.
    rpmdb="${WORK}/rpmdb-${label}"; mkdir -p "$rpmdb"
    rpm --dbpath "$rpmdb" --import "${RPM_REPO}/RPM-GPG-KEY-adminhelper"
    rpm --dbpath "$rpmdb" --checksig "$rpmpkg" | grep -Eqi 'signatures OK|pgp.*OK' \
        || fail "[$label] RPM-Paketsignatur nicht OK ($(rpm --dbpath "$rpmdb" --checksig "$rpmpkg"))"
    gpg --verify "${RPM_REPO}/repodata/repomd.xml.asc" "${RPM_REPO}/repodata/repomd.xml" >/dev/null 2>&1 \
        || fail "[$label] repomd.xml-Signatur ungültig"
    # dnf gpgkey must be ARMORED (ASCII).
    head -c 40 "${RPM_REPO}/RPM-GPG-KEY-adminhelper" | grep -q "BEGIN PGP PUBLIC KEY" \
        || fail "[$label] RPM-GPG-KEY ist nicht armored — dnf gpgkey erwartet ASCII-armored"
    ok "[$label] RPM: Baum + Paket-/repomd.xml-Signatur + armored Key"
}

# rsa3072 guards the legacy path; ed25519 is the maintainer's real key type.
verify_for_keytype "rsa3072" "rsa"
verify_for_keytype "ed25519" "ed25519"

echo "[repo-test] PASS — APT- und RPM-Repo korrekt gebaut und signiert (rsa + ed25519)."
