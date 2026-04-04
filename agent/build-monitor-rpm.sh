#!/bin/bash
# Build .rpm package for srm-monitor-agent
set -euo pipefail

VERSION="${VERSION:-0.1.0}"
PKG_NAME="srm-monitor-agent"

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
mkdir -p "${SRCDIR}/usr/local/bin"
mkdir -p "${SRCDIR}/etc/systemd/system"
mkdir -p "${SRCDIR}/etc/srm"

# Monitor agent
cp agent/srm-monitor-agent "${SRCDIR}/usr/local/bin/srm-monitor-agent"
chmod 755 "${SRCDIR}/usr/local/bin/srm-monitor-agent"

# systemd units
cp agent/systemd/srm-monitor-agent.service "${SRCDIR}/etc/systemd/system/"
cp agent/systemd/srm-monitor-agent.timer   "${SRCDIR}/etc/systemd/system/"

cd "${RPMBUILD_DIR}/SOURCES"
tar czf "${PKG_NAME}-${VERSION}.tar.gz" "${PKG_NAME}-${VERSION}"
cd -

sed "s/__VERSION__/${VERSION}/" agent/rpm-monitor/srm-monitor-agent.spec > "${RPMBUILD_DIR}/SPECS/${PKG_NAME}.spec"

rpmbuild --define "_topdir ${RPMBUILD_DIR}" -bb "${RPMBUILD_DIR}/SPECS/${PKG_NAME}.spec"

cp "${RPMBUILD_DIR}"/RPMS/noarch/*.rpm .

echo "=== RPM erstellt ==="
