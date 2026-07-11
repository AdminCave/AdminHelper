#!/bin/bash
# Build .deb package for adminhelper-agent (unified Go agent)
set -euo pipefail

cd "$(dirname "$0")/../.."   # repo root, regardless of the caller's CWD
source apps/agent/build-common.sh

require_version "apps/agent/build-deb.sh"
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

# adminhelper-agent Go binary (built by CI or make) + frpc (downloaded by CI)
require_binary apps/agent/bin/adminhelper-agent
cp apps/agent/bin/adminhelper-agent "${BUILD_DIR}/usr/bin/adminhelper-agent"
chmod 755 "${BUILD_DIR}/usr/bin/adminhelper-agent"

require_binary frpc
cp frpc "${BUILD_DIR}/usr/bin/frpc"
chmod 755 "${BUILD_DIR}/usr/bin/frpc"

# systemd units
copy_units "${BUILD_DIR}/etc/systemd/system"

# Build
dpkg-deb --root-owner-group --build "${BUILD_DIR}"
mv "build-deb/${PKG_NAME}_${VERSION}_amd64.deb" .

echo "=== Paket erstellt: ${PKG_NAME}_${VERSION}_amd64.deb ==="
