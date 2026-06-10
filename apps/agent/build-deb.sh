#!/bin/bash
# Build .deb package for adminhelper-agent (unified Go agent)
set -euo pipefail

if [ -z "${VERSION:-}" ]; then
    echo "FEHLER: VERSION ist nicht gesetzt (z.B. VERSION=0.26.0 bash apps/agent/build-deb.sh)." >&2
    exit 1
fi
PKG_NAME="adminhelper-agent"
BUILD_DIR="build-deb/${PKG_NAME}_${VERSION}_amd64"

echo "=== Building ${PKG_NAME} ${VERSION} (deb) ==="

rm -rf build-deb
mkdir -p "${BUILD_DIR}/DEBIAN"
mkdir -p "${BUILD_DIR}/usr/bin"
mkdir -p "${BUILD_DIR}/etc/systemd/system"
mkdir -p "${BUILD_DIR}/etc/frp"
mkdir -p "${BUILD_DIR}/etc/adminhelper"

# Control file with version
sed "s/__VERSION__/${VERSION}/" apps/agent/deb/DEBIAN/control > "${BUILD_DIR}/DEBIAN/control"
cp apps/agent/deb/DEBIAN/postinst "${BUILD_DIR}/DEBIAN/"
cp apps/agent/deb/DEBIAN/prerm    "${BUILD_DIR}/DEBIAN/"
cp apps/agent/deb/DEBIAN/postrm   "${BUILD_DIR}/DEBIAN/"
chmod 755 "${BUILD_DIR}/DEBIAN/postinst" "${BUILD_DIR}/DEBIAN/prerm" "${BUILD_DIR}/DEBIAN/postrm"

# adminhelper-agent Go binary (must exist, built by CI or make)
if [ -f apps/agent/bin/adminhelper-agent ]; then
    cp apps/agent/bin/adminhelper-agent "${BUILD_DIR}/usr/bin/adminhelper-agent"
    chmod 755 "${BUILD_DIR}/usr/bin/adminhelper-agent"
else
    echo "FEHLER: apps/agent/bin/adminhelper-agent nicht gefunden. Bitte zuerst bauen."
    exit 1
fi

# frpc binary (downloaded by CI)
if [ -f frpc ]; then
    cp frpc "${BUILD_DIR}/usr/bin/frpc"
    chmod 755 "${BUILD_DIR}/usr/bin/frpc"
else
    echo "FEHLER: frpc Binary nicht gefunden (./frpc im Repo-Root erwartet)." >&2
    exit 1
fi

# systemd units
cp apps/agent/systemd/frpc.service                "${BUILD_DIR}/etc/systemd/system/"
cp apps/agent/systemd/adminhelper-agent.service    "${BUILD_DIR}/etc/systemd/system/"
cp apps/agent/systemd/adminhelper-agent.timer      "${BUILD_DIR}/etc/systemd/system/"

# Build
dpkg-deb --root-owner-group --build "${BUILD_DIR}"
mv "build-deb/${PKG_NAME}_${VERSION}_amd64.deb" .

echo "=== Paket erstellt: ${PKG_NAME}_${VERSION}_amd64.deb ==="
