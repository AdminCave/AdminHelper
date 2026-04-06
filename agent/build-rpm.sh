#!/bin/bash
# Build .rpm package for srm-frpc-client
set -euo pipefail

VERSION="${VERSION:-0.7.1}"
PKG_NAME="srm-frpc-client"

echo "=== Building ${PKG_NAME} ${VERSION} (rpm) ==="

# Install rpmbuild if needed
command -v rpmbuild >/dev/null 2>&1 || {
    if command -v dnf >/dev/null 2>&1; then
        dnf install -y rpm-build
    elif command -v yum >/dev/null 2>&1; then
        yum install -y rpm-build
    fi
}

# Setup rpmbuild directories
RPMBUILD_DIR="${PWD}/build-rpm/rpmbuild"
rm -rf build-rpm
mkdir -p "${RPMBUILD_DIR}"/{BUILD,RPMS,SOURCES,SPECS,SRPMS}

# Create source tarball
SRCDIR="${RPMBUILD_DIR}/SOURCES/${PKG_NAME}-${VERSION}"
mkdir -p "${SRCDIR}/usr/bin"
mkdir -p "${SRCDIR}/usr/local/bin"
mkdir -p "${SRCDIR}/etc/systemd/system"
mkdir -p "${SRCDIR}/etc/frp"

# frpc binary
if [ -f frpc ]; then
    cp frpc "${SRCDIR}/usr/bin/frpc"
    chmod 755 "${SRCDIR}/usr/bin/frpc"
fi

# Sync agent
cp agent/srm-frpc-sync "${SRCDIR}/usr/local/bin/srm-frpc-sync"
chmod 755 "${SRCDIR}/usr/local/bin/srm-frpc-sync"

# systemd units
cp agent/systemd/frpc.service           "${SRCDIR}/etc/systemd/system/"
cp agent/systemd/srm-frpc-sync.service  "${SRCDIR}/etc/systemd/system/"
cp agent/systemd/srm-frpc-sync.timer    "${SRCDIR}/etc/systemd/system/"

cd "${RPMBUILD_DIR}/SOURCES"
tar czf "${PKG_NAME}-${VERSION}.tar.gz" "${PKG_NAME}-${VERSION}"
cd -

# Write spec file with version
sed "s/__VERSION__/${VERSION}/" agent/rpm/srm-frpc-client.spec > "${RPMBUILD_DIR}/SPECS/${PKG_NAME}.spec"

# Build
rpmbuild --define "_topdir ${RPMBUILD_DIR}" -bb "${RPMBUILD_DIR}/SPECS/${PKG_NAME}.spec"

# Copy result
cp "${RPMBUILD_DIR}"/RPMS/x86_64/*.rpm .

echo "=== RPM erstellt ==="
