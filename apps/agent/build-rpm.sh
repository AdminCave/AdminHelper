#!/bin/bash
# Build .rpm package for adminhelper-agent (unified Go agent)
set -euo pipefail

cd "$(dirname "$0")/../.."   # repo root, regardless of the caller's CWD
source apps/agent/build-common.sh

require_version "apps/agent/build-rpm.sh"

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
mkdir -p "${SRCDIR}/etc/systemd/system"
mkdir -p "${SRCDIR}/etc/frp/pki"
mkdir -p "${SRCDIR}/etc/adminhelper"

# adminhelper-agent Go binary (built by CI or make) + frpc (downloaded by CI)
require_binary apps/agent/bin/adminhelper-agent
cp apps/agent/bin/adminhelper-agent "${SRCDIR}/usr/bin/adminhelper-agent"
chmod 755 "${SRCDIR}/usr/bin/adminhelper-agent"

require_binary frpc
cp frpc "${SRCDIR}/usr/bin/frpc"
chmod 755 "${SRCDIR}/usr/bin/frpc"

# systemd units
copy_units "${SRCDIR}/etc/systemd/system"

cd "${RPMBUILD_DIR}/SOURCES"
tar czf "${PKG_NAME}-${VERSION}.tar.gz" "${PKG_NAME}-${VERSION}"
cd -

sed "s/__VERSION__/${VERSION}/" apps/agent/rpm/adminhelper-agent.spec > "${RPMBUILD_DIR}/SPECS/${PKG_NAME}.spec"

rpmbuild --define "_topdir ${RPMBUILD_DIR}" -bb "${RPMBUILD_DIR}/SPECS/${PKG_NAME}.spec"

cp "${RPMBUILD_DIR}"/RPMS/x86_64/*.rpm .

echo "=== RPM erstellt ==="
