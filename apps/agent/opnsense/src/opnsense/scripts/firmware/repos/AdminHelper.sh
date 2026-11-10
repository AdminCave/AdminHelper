#!/bin/sh
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

# The repository script of os-adminhelper. OPNsense runs each script of this directory when it
# writes the firmware settings (system_firmware_configure: at boot and with every firmware
# reload) and shows only what it writes to stderr; the package's +POST_INSTALL runs it once more.
#
# It points pkg at the repository of the AdminHelper server the agent is registered with: the repo
# plane on port 8445 of the server's host, as agent-install.sh does on Linux, with each package
# signed by the key whose public part this package ships. Before the agent is enrolled TLS stays
# unverified there as well: the signature carries the packages' authenticity. Once it is, fetch(3)
# verifies the server with the enrolled CA; pkg sets a repository's ENV for its own fetches only
# and restores it afterwards (libpkg/fetch.c). The priority stays below OPNsense's 11, so pkg
# prefers OPNsense's package for a name both repositories carry.
#
# Without a usable server URL or without the key it leaves the file alone: a file written by hand
# to install the plugin keeps working until the agent is registered.

LC_ALL=C
export LC_ALL
umask 022

etc=/usr/local/etc/adminhelper
conf=/usr/local/etc/pkg/repos/AdminHelper.conf
pubkey=/usr/local/etc/pkg/keys/AdminHelper.pub
ca=$etc/identity/ca.crt

# conf_value FILE KEY prints the value of KEY in one of the agent's KEY="value" files, read as the
# agent reads it: trimmed, without quotes, the last line counts.
conf_value() {
    [ -f "$1" ] || return 0
    awk -v key="$2" '
        { line = $0; sub(/^[ \t]+/, "", line); sub(/[ \t\r]+$/, "", line) }
        line == "" || line ~ /^#/ { next }
        {
            i = index(line, "=")
            if (i == 0) next
            k = substr(line, 1, i - 1); sub(/[ \t]+$/, "", k)
            if (k != key) next
            v = substr(line, i + 1); sub(/^[ \t]+/, "", v); gsub(/^"+|"+$/, "", v)
            value = v
        }
        END { print value }' "$1"
}

# host_of URL prints the host of an https URL, an IPv6 address in brackets. The host goes into a
# UCL string that pkg expands, so only the characters of a host name or an address pass.
host_of() {
    case "$1" in
    https://*) authority=${1#https://} ;;
    *) return 1 ;;
    esac
    authority=${authority%%/*}
    case "$authority" in
    \[*\]*)
        host=${authority%%]*}]
        case "${host#\[}" in
        '' | ] | *[!0123456789ABCDEFabcdef:.]*]) return 1 ;;
        esac
        rest=${authority#"$host"}
        ;;
    *)
        host=${authority%%:*}
        case "$host" in
        '' | [.-]* | *[!0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz.-]*) return 1 ;;
        esac
        rest=${authority#"$host"}
        ;;
    esac
    # Nothing but a port may follow the host: no user, query or fragment.
    case "$rest" in
    '' | :) ;;
    :*[!0123456789]*) return 1 ;;
    :*) ;;
    *) return 1 ;;
    esac
    echo "$host"
}

[ -f "$pubkey" ] || exit 0
host=$(host_of "$(conf_value "$etc/frp/adminhelper.conf" ADMINHELPER_URL)") ||
    host=$(host_of "$(conf_value "$etc/monitor.conf" MONITOR_URL)") ||
    exit 0

if [ -f "$ca" ]; then
    env="SSL_CA_CERT_FILE: \"$ca\""
else
    # Without a verified peer a check of its name proves nothing, and the name may not match.
    env='SSL_NO_VERIFY_PEER: "1", SSL_NO_VERIFY_HOSTNAME: "1"'
fi

mkdir -p "${conf%/*}" || exit 1
cat > "$conf.new" <<EOF || exit 1
# Written by os-adminhelper from the agent's configuration; changes do not last.
AdminHelper: {
  url: "https://$host:8445/freebsd/\${ABI}",
  signature_type: "pubkey",
  pubkey: "$pubkey",
  env: { $env },
  priority: 5,
  enabled: yes
}
EOF
mv -f "$conf.new" "$conf"
