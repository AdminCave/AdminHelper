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

# Build. -Zxz, not the modern dpkg-deb default (zstd): zstd-compressed members
# are unreadable by dpkg on older targets (Debian Stretch/Buster, and the Debian-
# based firmware on UniFi/appliance hosts), which fail with "unknown compression
# for member 'control.tar.zst'". xz is understood by every dpkg since Debian 6,
# so the package installs across the whole supported fleet. The agent binary is
# already static (CGO_ENABLED=0), so only the container format limited reach.
dpkg-deb --root-owner-group -Zxz --build "${BUILD_DIR}"
mv "build-deb/${PKG_NAME}_${VERSION}_amd64.deb" .

# Regression guard (the zstd-on-old-dpkg incident): assert the built package uses
# xz members, so a future dpkg-deb default change or a dropped -Zxz fails the
# build instead of shipping a package that installs on modern CI/crabbox boxes
# but breaks on older-Debian / appliance targets. `ar t` lists the members.
members="$(ar t "${PKG_NAME}_${VERSION}_amd64.deb")"
case "$members" in
    *control.tar.zst*|*data.tar.zst*)
        echo "FEHLER: .deb verwendet zstd-Kompression — bricht auf aeltererem dpkg (Debian Stretch/Buster, Appliances). -Zxz muss greifen." >&2
        exit 1 ;;
    *control.tar.xz*) ;;  # expected
    *) echo "WARNUNG: unerwartete .deb-Member-Kompression: ${members}" >&2 ;;
esac

echo "=== Paket erstellt: ${PKG_NAME}_${VERSION}_amd64.deb ==="
