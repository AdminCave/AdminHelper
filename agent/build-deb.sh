#!/bin/bash
# Build .deb package for srm-frpc-client
set -euo pipefail

VERSION="${VERSION:-0.7.0}"
PKG_NAME="srm-frpc-client"
BUILD_DIR="build-deb/${PKG_NAME}_${VERSION}_amd64"

echo "=== Building ${PKG_NAME} ${VERSION} (deb) ==="

rm -rf build-deb
mkdir -p "${BUILD_DIR}/DEBIAN"
mkdir -p "${BUILD_DIR}/usr/bin"
mkdir -p "${BUILD_DIR}/usr/local/bin"
mkdir -p "${BUILD_DIR}/etc/systemd/system"
mkdir -p "${BUILD_DIR}/etc/frp"

# Control file with version
sed "s/__VERSION__/${VERSION}/" agent/deb/DEBIAN/control > "${BUILD_DIR}/DEBIAN/control"
cp agent/deb/DEBIAN/postinst "${BUILD_DIR}/DEBIAN/"
cp agent/deb/DEBIAN/prerm    "${BUILD_DIR}/DEBIAN/"
cp agent/deb/DEBIAN/postrm   "${BUILD_DIR}/DEBIAN/"
chmod 755 "${BUILD_DIR}/DEBIAN/postinst" "${BUILD_DIR}/DEBIAN/prerm" "${BUILD_DIR}/DEBIAN/postrm"

# frpc binary (must exist in project root, downloaded by CI)
if [ -f frpc ]; then
    cp frpc "${BUILD_DIR}/usr/bin/frpc"
    chmod 755 "${BUILD_DIR}/usr/bin/frpc"
else
    echo "WARNUNG: frpc Binary nicht gefunden. Dummy wird erstellt."
    echo '#!/bin/sh' > "${BUILD_DIR}/usr/bin/frpc"
    echo 'echo "frpc placeholder"' >> "${BUILD_DIR}/usr/bin/frpc"
    chmod 755 "${BUILD_DIR}/usr/bin/frpc"
fi

# Sync agent
cp agent/srm-frpc-sync "${BUILD_DIR}/usr/local/bin/srm-frpc-sync"
chmod 755 "${BUILD_DIR}/usr/local/bin/srm-frpc-sync"

# systemd units
cp agent/systemd/frpc.service           "${BUILD_DIR}/etc/systemd/system/"
cp agent/systemd/srm-frpc-sync.service  "${BUILD_DIR}/etc/systemd/system/"
cp agent/systemd/srm-frpc-sync.timer    "${BUILD_DIR}/etc/systemd/system/"

# Build
dpkg-deb --build "${BUILD_DIR}"
mv "build-deb/${PKG_NAME}_${VERSION}_amd64.deb" .

echo "=== Paket erstellt: ${PKG_NAME}_${VERSION}_amd64.deb ==="
