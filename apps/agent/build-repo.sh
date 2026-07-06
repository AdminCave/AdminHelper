#!/bin/bash
# Build a self-contained, GPG-signed APT + YUM repository for adminhelper-agent.
#
# Stateless single-version repo: each release builds a fresh tree carrying just
# the current .deb/.rpm. That is all `apt upgrade` / `dnf upgrade` need (clients
# compare "installed" vs "highest in the index"), so there is no reprepro/aptly
# database state to carry across releases.
#
# Output layout ($OUT_DIR, default ./repo):
#   apt/
#     pool/main/adminhelper-agent_<ver>_amd64.deb
#     dists/stable/{Release,Release.gpg,InRelease}
#     dists/stable/main/binary-amd64/{Packages,Packages.gz}
#     adminhelper-archive-keyring.gpg   (DEARMORED — apt signed-by wants binary)
#   rpm/
#     adminhelper-agent-<ver>-1.x86_64.rpm   (rpm --addsign'd)
#     repodata/{repomd.xml,repomd.xml.asc,...}
#     RPM-GPG-KEY-adminhelper            (ARMORED — dnf gpgkey wants ASCII)
#
# Inputs (env):
#   VERSION            (required)  e.g. 0.38.0 — version embedded in the asset names
#   REPO_GPG_KEY_ID    (required)  fingerprint/email of an already-imported secret key
#   DEB                (optional)  path to the .deb  (default: ./adminhelper-agent_<ver>_amd64.deb)
#   RPM                (optional)  path to the .rpm  (default: ./adminhelper-agent-<ver>-1.*.x86_64.rpm)
#   OUT_DIR            (optional)  output root (default: ./repo)
#   REPO_ORIGIN/REPO_LABEL/REPO_SUITE  (optional) APT Release identity
#
# The signing key must be imported into the active GNUPGHOME beforehand and be
# passphrase-less (CI key, like MINISIGN_SECRET_KEY) — signing runs --batch with
# pinentry loopback and never prompts.
set -euo pipefail

if [ -z "${VERSION:-}" ]; then
    echo "FEHLER: VERSION ist nicht gesetzt (z.B. VERSION=0.38.0 bash apps/agent/build-repo.sh)." >&2
    exit 1
fi
if [ -z "${REPO_GPG_KEY_ID:-}" ]; then
    echo "FEHLER: REPO_GPG_KEY_ID ist nicht gesetzt (Fingerprint/Email des importierten Signaturschluessels)." >&2
    exit 1
fi

PKG_NAME="adminhelper-agent"
OUT_DIR="${OUT_DIR:-repo}"
DEB="${DEB:-${PKG_NAME}_${VERSION}_amd64.deb}"
REPO_ORIGIN="${REPO_ORIGIN:-AdminHelper}"
REPO_LABEL="${REPO_LABEL:-AdminHelper}"
REPO_SUITE="${REPO_SUITE:-stable}"
REPO_COMPONENT="main"
KEYRING_NAME="adminhelper-archive-keyring.gpg"
RPM_KEY_NAME="RPM-GPG-KEY-adminhelper"

# Default RPM path is a glob: the dist tag is optional (.el9/.fc40 on rpm distros,
# absent on the ubuntu CI runner), so match -1.x86_64 AND -1.<dist>.x86_64.
if [ -z "${RPM:-}" ]; then
    RPM=$(ls "${PKG_NAME}-${VERSION}"-1*.x86_64.rpm 2>/dev/null | head -1 || true)
fi

# --- Preconditions ----------------------------------------------------------
for t in dpkg-scanpackages apt-ftparchive createrepo_c rpm rpmsign gpg gzip; do
    command -v "$t" >/dev/null 2>&1 \
        || { echo "FEHLER: benoetigtes Werkzeug fehlt: $t" >&2; exit 1; }
done
[ -f "$DEB" ] || { echo "FEHLER: .deb nicht gefunden: $DEB" >&2; exit 1; }
[ -n "$RPM" ] && [ -f "$RPM" ] || { echo "FEHLER: .rpm nicht gefunden (RPM=…): ${RPM:-<leer>}" >&2; exit 1; }
gpg --list-secret-keys "$REPO_GPG_KEY_ID" >/dev/null 2>&1 \
    || { echo "FEHLER: kein geheimer Schluessel fuer REPO_GPG_KEY_ID=$REPO_GPG_KEY_ID im Keyring." >&2; exit 1; }

# Non-interactive gpg signing wrapper (passphrase-less CI key).
gpg_sign() { gpg --batch --yes --pinentry-mode loopback --local-user "$REPO_GPG_KEY_ID" "$@"; }

# rpm's %__gpg default differs across distros: Debian-rpm points at /usr/bin/gpg,
# Ubuntu-rpm (CI runner) at /usr/bin/gpg2 which modern gnupg no longer ships
# ("Could not exec gpg"). Pin it to the gpg actually on PATH.
GPG_BIN="$(command -v gpg)"

echo "=== Building adminhelper-agent ${VERSION} repository (apt + rpm) ==="
rm -rf "$OUT_DIR"
APT_ROOT="${OUT_DIR}/apt"
RPM_ROOT="${OUT_DIR}/rpm"

# ── APT repository ──────────────────────────────────────────────────────────
echo "--- APT repo ---"
mkdir -p "${APT_ROOT}/pool/${REPO_COMPONENT}"
mkdir -p "${APT_ROOT}/dists/${REPO_SUITE}/${REPO_COMPONENT}/binary-amd64"
cp "$DEB" "${APT_ROOT}/pool/${REPO_COMPONENT}/"

# Packages index. dpkg-scanpackages writes Filename: paths relative to the dir it
# is run from, so run it from the apt root → "pool/main/…" (what apt expects).
(
    cd "$APT_ROOT"
    dpkg-scanpackages --multiversion "pool/${REPO_COMPONENT}" \
        > "dists/${REPO_SUITE}/${REPO_COMPONENT}/binary-amd64/Packages" 2>/dev/null
    gzip -9kf "dists/${REPO_SUITE}/${REPO_COMPONENT}/binary-amd64/Packages"
)

# Release file with the per-index checksums (SHA256 is the security-relevant one;
# MD5Sum/SHA1 added for older clients). apt-ftparchive scans the dists subtree.
(
    cd "$APT_ROOT"
    apt-ftparchive \
        -o "APT::FTPArchive::Release::Origin=${REPO_ORIGIN}" \
        -o "APT::FTPArchive::Release::Label=${REPO_LABEL}" \
        -o "APT::FTPArchive::Release::Suite=${REPO_SUITE}" \
        -o "APT::FTPArchive::Release::Codename=${REPO_SUITE}" \
        -o "APT::FTPArchive::Release::Components=${REPO_COMPONENT}" \
        -o "APT::FTPArchive::Release::Architectures=amd64" \
        -o "APT::FTPArchive::Release::Version=${VERSION}" \
        release "dists/${REPO_SUITE}" > "dists/${REPO_SUITE}/Release"

    # Server SHALL provide InRelease (clearsigned); also emit the detached
    # Release.gpg for older clients (Debian repo format spec).
    gpg_sign --clearsign -o "dists/${REPO_SUITE}/InRelease" "dists/${REPO_SUITE}/Release"
    gpg_sign -abs -o "dists/${REPO_SUITE}/Release.gpg" "dists/${REPO_SUITE}/Release"
)

# Public keys to ship in the client keyring. Defaults to the signing key; during a key
# rotation set REPO_GPG_EXPORT_IDS="OLD NEW" so hosts pinned to the old key keep trusting
# the repo through the overlap window, before the signing key itself switches (audit 8.3).
REPO_GPG_EXPORT_IDS="${REPO_GPG_EXPORT_IDS:-$REPO_GPG_KEY_ID}"

# Public key(s), DEARMORED (binary) — apt's signed-by= must not be ASCII-armored.
# shellcheck disable=SC2086  # intentional word-splitting: REPO_GPG_EXPORT_IDS is a key list
gpg --export $REPO_GPG_EXPORT_IDS > "${APT_ROOT}/${KEYRING_NAME}"

# ── RPM/YUM repository ──────────────────────────────────────────────────────
echo "--- RPM repo ---"
mkdir -p "$RPM_ROOT"
cp "$RPM" "${RPM_ROOT}/"
RPM_FILE="${RPM_ROOT}/$(basename "$RPM")"

# Public key(s), ARMORED (ASCII) — dnf's gpgkey= expects an armored key. Exported
# first so the signature self-check below can import it. Same rotation list as apt.
# shellcheck disable=SC2086  # intentional word-splitting: REPO_GPG_EXPORT_IDS is a key list
gpg --export --armor $REPO_GPG_EXPORT_IDS > "${RPM_ROOT}/${RPM_KEY_NAME}"

# Sign the package itself (gpgcheck=1). __gpg pins the gpg binary; the loopback
# args let a passphrase-less key sign non-interactively.
rpm --define "__gpg ${GPG_BIN}" \
    --define "_gpg_name ${REPO_GPG_KEY_ID}" \
    --define "_gpg_sign_cmd_extra_args --batch --pinentry-mode loopback --no-armor" \
    --addsign "$RPM_FILE" >/dev/null
# Self-check: `rpm --checksig` reports "signatures OK" only against an imported
# key, so verify in a scratch rpmdb (leaves the host rpm database untouched).
_vdb="$(mktemp -d)"
rpm --dbpath "$_vdb" --import "${RPM_ROOT}/${RPM_KEY_NAME}"
rpm --dbpath "$_vdb" --checksig "$RPM_FILE" | grep -qi 'signatures OK' \
    || { echo "FEHLER: RPM-Signatur nicht verifizierbar nach --addsign." >&2; rm -rf "$_vdb"; exit 1; }
rm -rf "$_vdb"

# Repo metadata + detached signature of repomd.xml (repo_gpgcheck=1).
createrepo_c --quiet "$RPM_ROOT"
gpg_sign --detach-sign --armor -o "${RPM_ROOT}/repodata/repomd.xml.asc" \
    "${RPM_ROOT}/repodata/repomd.xml"

echo "=== Repository erstellt unter ${OUT_DIR}/ ==="
find "$OUT_DIR" -type f | sort | sed 's/^/  /'
