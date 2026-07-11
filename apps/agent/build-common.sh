# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

# shellcheck shell=bash

# Shared helpers for build-deb.sh / build-rpm.sh. Source this AFTER cd'ing to the
# repo root so the relative paths below resolve regardless of the caller's CWD.
# Not executable on its own — it only defines PKG_NAME and the require_*/copy_units
# helpers (audit 2.56: the two packagers duplicated this verbatim).

# shellcheck disable=SC2034  # consumed by the sourcing build-deb.sh / build-rpm.sh
PKG_NAME="adminhelper-agent"

# require_version aborts unless VERSION is set (both packagers need it for the
# artifact name and the control/spec version substitution). $1 is the script path
# shown in the hint.
require_version() {
    if [ -z "${VERSION:-}" ]; then
        echo "FEHLER: VERSION ist nicht gesetzt (z.B. VERSION=0.26.0 bash ${1:-apps/agent/build-*.sh})." >&2
        exit 1
    fi
}

# require_binary aborts unless the given file exists. The Go agent and frpc are
# built/downloaded by CI or make before packaging.
require_binary() {
    if [ ! -f "$1" ]; then
        echo "FEHLER: $1 nicht gefunden. Bitte zuerst bauen." >&2
        exit 1
    fi
}

# copy_units installs the three systemd units into the given system directory.
# A new unit is added here once, not in both packagers.
copy_units() {
    cp apps/agent/systemd/frpc.service              "$1/"
    cp apps/agent/systemd/adminhelper-agent.service "$1/"
    cp apps/agent/systemd/adminhelper-agent.timer   "$1/"
}
