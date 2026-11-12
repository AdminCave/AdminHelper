#!/bin/bash

# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

# Build the FreeBSD package of adminhelper-agent and the OPNsense plugin os-adminhelper with
# pkg-create(8), one per ABI, and with a key the signed pkg repository of each ABI with pkg-repo(8).
#
# The Go agent is static, so both ABIs carry the same files; pkg installs a package only on the ABI
# its manifest names. Like build-repo.sh the output is stateless: each build replaces
# $OUT_DIR/freebsd, so pkg repo, which takes every package below its directory, sees no stale one.
#
# os-adminhelper packs apps/agent/opnsense/src below /usr/local as OPNsense's plugins.mk does, with
# its version file and scripts, and depends on adminhelper-agent. With a key it carries the key's
# public part, which its repository script names to pkg: a repository the plugin set up accepts
# only packages signed with that key.
#
# Output layout ($OUT_DIR, default ./build-pkg):
#   freebsd/<ABI>/All/{adminhelper-agent,os-adminhelper}-<ver>.pkg
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
# pkg must be on the PATH: FreeBSD's, or one built from the freebsd/pkg sources on Linux; with
# PKG_REPO_KEY openssl as well.
set -euo pipefail
# The version check's ranges match ASCII only in the C locale (bash's =~ follows the locale).
export LC_ALL=C

cd "$(dirname "$0")/../.."   # repo root, regardless of the caller's CWD
source apps/agent/build-common.sh

require_version "apps/agent/build-pkg.sh"

ABIS="FreeBSD:14:amd64 FreeBSD:15:amd64"
# The OPNsense series on each ABI, for the plugin's version file: 26.1 runs on FreeBSD 14, 26.7 on 15.
declare -A OPNSENSE_SERIES=([FreeBSD:14:amd64]=26.1 [FreeBSD:15:amd64]=26.7)
PLUGIN=os-adminhelper
PLUGIN_SRC=apps/agent/opnsense
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
if [ -n "${PKG_REPO_KEY:-}" ] && ! command -v openssl >/dev/null 2>&1; then
    echo "ERROR: openssl not found on the PATH; it derives the public key of PKG_REPO_KEY." >&2
    exit 1
fi

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

# The plugin's tree with the modes of the checkout, as plugins.mk copies it with tar.
PSTAGE="$WORK/plugin-stage"
printf '@owner root\n@group wheel\n' > "$WORK/plugin-plist"
while IFS= read -r file; do
    mode=0644
    [ -x "$PLUGIN_SRC/src/$file" ] && mode=0755
    mkdir -p "$PSTAGE/usr/local/$(dirname "$file")"
    install -m "$mode" "$PLUGIN_SRC/src/$file" "$PSTAGE/usr/local/$file"
    echo "$file" >> "$WORK/plugin-plist"
done < <(cd "$PLUGIN_SRC/src" && find . -type f | sed 's|^\./||' | sort)
mkdir -p "$PSTAGE/usr/local/opnsense/version"
echo "opnsense/version/adminhelper" >> "$WORK/plugin-plist"
if [ -n "${PKG_REPO_KEY:-}" ]; then
    # The public key as pkg-repo(8) derives it; openssl rsa also refuses any key that pkg repo
    # could not use as rsa:.
    mkdir -p "$PSTAGE/usr/local/etc/pkg/keys"
    if ! openssl rsa -in "$PKG_REPO_KEY" -pubout -out "$PSTAGE/usr/local/etc/pkg/keys/AdminHelper.pub" \
        2>"$WORK/openssl.err"; then
        echo "ERROR: PKG_REPO_KEY $PKG_REPO_KEY is no RSA private key:" >&2
        cat "$WORK/openssl.err" >&2
        exit 1
    fi
    chmod 0644 "$PSTAGE/usr/local/etc/pkg/keys/AdminHelper.pub"
    echo "etc/pkg/keys/AdminHelper.pub" >> "$WORK/plugin-plist"
fi

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

    # The version file as plugins.mk's template writes it: OPNsense registers the plugin by it and
    # reads its tier from the annotations. Tier 4 is what OPNsense shows for any other repository.
    pmeta="$WORK/plugin-meta-${abi//:/-}"
    mkdir "$pmeta"
    cat > "$PSTAGE/usr/local/opnsense/version/adminhelper" <<EOF
{
    "product_abi": "${OPNSENSE_SERIES[$abi]}",
    "product_arch": "${abi##*:}",
    "product_conflicts": "",
    "product_email": "packages@admincave.com",
    "product_hash": "",
    "product_id": "${PLUGIN}",
    "product_name": "adminhelper",
    "product_tier": "4",
    "product_version": "${VERSION}",
    "product_website": "https://admincave.com"
}
EOF
    chmod 0644 "$PSTAGE/usr/local/opnsense/version/adminhelper"
    cp "$PLUGIN_SRC/post-install" "$pmeta/+POST_INSTALL"
    cp "$PLUGIN_SRC/post-deinstall" "$pmeta/+POST_DEINSTALL"
    cat > "$pmeta/+MANIFEST" <<EOF
{
  "name": "${PLUGIN}",
  "version": "${VERSION}",
  "origin": "opnsense/${PLUGIN}",
  "comment": "AdminHelper agent: settings and status for OPNsense",
  "desc": "OPNsense plugin of the AdminHelper agent: a page to switch the agent on and off and to show its state, the tunnel client as a service, and the pkg repository of the AdminHelper server the agent is registered with.",
  "www": "https://admincave.com",
  "maintainer": "packages@admincave.com",
  "prefix": "/usr/local",
  "abi": "${abi}",
  "licenselogic": "single",
  "licenses": ["GPLv3+"],
  "categories": ["sysutils"],
  "deps": {"${PKG_NAME}": {"origin": "sysutils/${PKG_NAME}", "version": "${VERSION}"}},
  "annotations": $(cat "$PSTAGE/usr/local/opnsense/version/adminhelper")
}
EOF
    pkg create -m "$pmeta" -r "$PSTAGE" -p "$WORK/plugin-plist" -o "$repo/All"
    if [ -n "${PKG_REPO_KEY:-}" ]; then
        # The type before the first ':' keeps a ':' in the key's path out of the split.
        pkg repo "$repo" "rsa:$PKG_REPO_KEY"
    fi
done

echo "=== pkg built under ${OUT_DIR}/freebsd ==="
