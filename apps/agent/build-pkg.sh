#!/bin/bash

# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

# Build the FreeBSD package of adminhelper-agent with pkg-create(8), one per ABI, and with a key the
# signed pkg repository of each ABI with pkg-repo(8).
#
# The Go agent is static, so both ABIs carry the same files; pkg installs a package only on the ABI
# its manifest names. Like build-repo.sh the output is stateless: each build replaces
# $OUT_DIR/freebsd, so pkg repo, which takes every package below its directory, sees no stale one.
#
# Output layout ($OUT_DIR, default ./build-pkg):
#   freebsd/<ABI>/All/adminhelper-agent-<ver>.pkg
#   freebsd/<ABI>/{meta.conf,packagesite.pkg,data.pkg}   (only with PKG_REPO_KEY)
#
# Inputs (env):
#   VERSION       (required)  e.g. 0.47.0
#   AGENT_BINARY  (optional)  the FreeBSD agent (default: apps/agent/bin/adminhelper-agent-freebsd)
#   FRPC_BINARY   (optional)  frpc of the frp release freebsd_amd64 (default: ./frpc-freebsd)
#   OUT_DIR       (optional)  output root (default: ./build-pkg)
#   PKG_REPO_KEY  (optional)  PEM file of the repository's RSA signing key
# Relative paths are taken from the repo root.
#
# pkg must be on the PATH: FreeBSD's, or one built from the freebsd/pkg sources on Linux.
set -euo pipefail
# The version check's ranges match ASCII only in the C locale (bash's =~ follows the locale).
export LC_ALL=C

cd "$(dirname "$0")/../.."   # repo root, regardless of the caller's CWD
source apps/agent/build-common.sh

require_version "apps/agent/build-pkg.sh"

ABIS="FreeBSD:14:amd64 FreeBSD:15:amd64"
AGENT_BINARY="${AGENT_BINARY:-apps/agent/bin/adminhelper-agent-freebsd}"
FRPC_BINARY="${FRPC_BINARY:-frpc-freebsd}"
OUT_DIR="${OUT_DIR:-build-pkg}"

# pkg splits <name>-<version> at the last '-' and reads '_' and ',' as port revision and epoch; the
# manifest quotes the version as is. So only a plain version passes.
if ! [[ $VERSION =~ ^[0-9][0-9A-Za-z.]*$ ]]; then
    echo "ERROR: VERSION '$VERSION' is no pkg version (digits, letters and dots only)." >&2
    exit 1
fi
require_binary "$AGENT_BINARY"
require_binary "$FRPC_BINARY"
if [ -n "${PKG_REPO_KEY:-}" ] && [ ! -f "$PKG_REPO_KEY" ]; then
    echo "ERROR: PKG_REPO_KEY $PKG_REPO_KEY not found." >&2
    exit 1
fi
command -v pkg >/dev/null 2>&1 || { echo "ERROR: pkg not found on the PATH." >&2; exit 1; }

echo "=== Building ${PKG_NAME} ${VERSION} (pkg: ${ABIS}) ==="

WORK=$(mktemp -d)
trap 'rm -rf -- "$WORK"' EXIT

STAGE="$WORK/stage"
install -d "$STAGE/usr/local/bin" "$STAGE/usr/local/libexec/adminhelper" "$STAGE/usr/local/etc/rc.d" \
    "$STAGE/usr/local/etc/newsyslog.conf.d"
install -m 0755 "$AGENT_BINARY" "$STAGE/usr/local/bin/adminhelper-agent"
install -m 0755 "$FRPC_BINARY" "$STAGE/usr/local/libexec/adminhelper/frpc"
install -m 0755 apps/agent/freebsd/adminhelper_frpc "$STAGE/usr/local/etc/rc.d/adminhelper_frpc"
install -m 0644 apps/agent/freebsd/newsyslog.conf "$STAGE/usr/local/etc/newsyslog.conf.d/adminhelper.conf"

# Paths relative to the prefix. Without @owner and @group the archive would carry the build user.
cat > "$WORK/plist" <<'EOF'
@owner root
@group wheel
bin/adminhelper-agent
libexec/adminhelper/frpc
etc/rc.d/adminhelper_frpc
etc/newsyslog.conf.d/adminhelper.conf
EOF

rm -rf -- "${OUT_DIR:?}/freebsd"
for abi in $ABIS; do
    meta="$WORK/meta-${abi//:/-}"
    mkdir "$meta"
    cp apps/agent/freebsd/post-install "$meta/+POST_INSTALL"
    cp apps/agent/freebsd/pre-deinstall "$meta/+PRE_DEINSTALL"
    # JSON is valid UCL; the fields pkg requires (libpkg/pkg.c, pkg_is_valid) and the ABI.
    cat > "$meta/+MANIFEST" <<EOF
{
  "name": "${PKG_NAME}",
  "version": "${VERSION}",
  "origin": "sysutils/${PKG_NAME}",
  "comment": "AdminHelper agent: FRP tunnel sync and monitoring",
  "desc": "Agent of AdminHelper. It syncs the FRP tunnels the server assigns to this host and reports its monitoring data.",
  "www": "https://admincave.com",
  "maintainer": "packages@admincave.com",
  "prefix": "/usr/local",
  "abi": "${abi}",
  "licenselogic": "single",
  "licenses": ["GPLv3+"],
  "categories": ["sysutils"]
}
EOF
    repo="$OUT_DIR/freebsd/$abi"
    pkg create -m "$meta" -r "$STAGE" -p "$WORK/plist" -o "$repo/All"
    if [ -n "${PKG_REPO_KEY:-}" ]; then
        # The type before the first ':' keeps a ':' in the key's path out of the split.
        pkg repo "$repo" "rsa:$PKG_REPO_KEY"
    fi
done

echo "=== pkg built under ${OUT_DIR}/freebsd ==="
