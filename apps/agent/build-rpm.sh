#!/bin/bash
# Build .rpm package for adminhelper-agent (unified Go agent)
set -euo pipefail

VERSION="${VERSION:-0.24.0}"
PKG_NAME="adminhelper-agent"

echo "=== Building ${PKG_NAME} ${VERSION} (rpm) ==="

command -v rpmbuild >/dev/null 2>&1 || {
    if command -v dnf >/dev/null 2>&1; then
        dnf install -y rpm-build
    elif command -v yum >/dev/null 2>&1; then
        yum install -y rpm-build
    fi
}

RPMBUILD_DIR="${PWD}/build-rpm/rpmbuild"
rm -rf build-rpm
mkdir -p "${RPMBUILD_DIR}"/{BUILD,RPMS,SOURCES,SPECS,SRPMS}

SRCDIR="${RPMBUILD_DIR}/SOURCES/${PKG_NAME}-${VERSION}"
mkdir -p "${SRCDIR}/usr/bin"
mkdir -p "${SRCDIR}/usr/local/bin"
mkdir -p "${SRCDIR}/etc/systemd/system"
mkdir -p "${SRCDIR}/etc/frp/pki"
mkdir -p "${SRCDIR}/etc/adminhelper"

# adminhelper-agent Go binary
if [ -f apps/agent/bin/adminhelper-agent ]; then
    cp apps/agent/bin/adminhelper-agent "${SRCDIR}/usr/local/bin/adminhelper-agent"
    chmod 755 "${SRCDIR}/usr/local/bin/adminhelper-agent"
else
    echo "FEHLER: apps/agent/bin/adminhelper-agent nicht gefunden."
    exit 1
fi

# frpc binary
if [ -f frpc ]; then
    cp frpc "${SRCDIR}/usr/bin/frpc"
    chmod 755 "${SRCDIR}/usr/bin/frpc"
fi

# systemd units
cp apps/agent/systemd/frpc.service                "${SRCDIR}/etc/systemd/system/"
cp apps/agent/systemd/adminhelper-agent.service    "${SRCDIR}/etc/systemd/system/"
cp apps/agent/systemd/adminhelper-agent.timer      "${SRCDIR}/etc/systemd/system/"

cd "${RPMBUILD_DIR}/SOURCES"
tar czf "${PKG_NAME}-${VERSION}.tar.gz" "${PKG_NAME}-${VERSION}"
cd -

sed "s/__VERSION__/${VERSION}/" apps/agent/rpm/adminhelper-agent.spec > "${RPMBUILD_DIR}/SPECS/${PKG_NAME}.spec"

rpmbuild --define "_topdir ${RPMBUILD_DIR}" -bb "${RPMBUILD_DIR}/SPECS/${PKG_NAME}.spec"

cp "${RPMBUILD_DIR}"/RPMS/x86_64/*.rpm .

echo "=== RPM erstellt ==="
