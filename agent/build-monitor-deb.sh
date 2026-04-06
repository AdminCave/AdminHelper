#!/bin/bash
# Build .deb package for srm-monitor-agent
set -euo pipefail

VERSION="${VERSION:-0.7.0}"
PKG_NAME="srm-monitor-agent"
BUILD_DIR="build-deb/${PKG_NAME}_${VERSION}_all"

echo "=== Building ${PKG_NAME} ${VERSION} (deb) ==="

rm -rf build-deb
mkdir -p "${BUILD_DIR}/DEBIAN"
mkdir -p "${BUILD_DIR}/usr/local/bin"
mkdir -p "${BUILD_DIR}/etc/systemd/system"
mkdir -p "${BUILD_DIR}/etc/srm"

# Control file with version
sed "s/__VERSION__/${VERSION}/" agent/deb-monitor/DEBIAN/control > "${BUILD_DIR}/DEBIAN/control"
cp agent/deb-monitor/DEBIAN/postinst "${BUILD_DIR}/DEBIAN/"
cp agent/deb-monitor/DEBIAN/prerm    "${BUILD_DIR}/DEBIAN/"
cp agent/deb-monitor/DEBIAN/postrm   "${BUILD_DIR}/DEBIAN/"
chmod 755 "${BUILD_DIR}/DEBIAN/postinst" "${BUILD_DIR}/DEBIAN/prerm" "${BUILD_DIR}/DEBIAN/postrm"

# Monitor agent
cp agent/srm-monitor-agent "${BUILD_DIR}/usr/local/bin/srm-monitor-agent"
chmod 755 "${BUILD_DIR}/usr/local/bin/srm-monitor-agent"

# systemd units
cp agent/systemd/srm-monitor-agent.service "${BUILD_DIR}/etc/systemd/system/"
cp agent/systemd/srm-monitor-agent.timer   "${BUILD_DIR}/etc/systemd/system/"

# Build
dpkg-deb --build "${BUILD_DIR}"
mv "build-deb/${PKG_NAME}_${VERSION}_all.deb" .

echo "=== Paket erstellt: ${PKG_NAME}_${VERSION}_all.deb ==="
