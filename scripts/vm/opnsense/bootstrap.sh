#!/bin/sh
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

# Turns a base-freebsd box into OPNsense for the base-opnsense template; run by
# `vm.py bake --profile base-opnsense`, as root, which reboots afterwards:
#
#   AH_OPNSENSE_KEY='<public key>' sh scripts/vm/opnsense/bootstrap.sh 26.7
#
# opnsense/update's own bootstrap does the conversion (it deletes every package
# of the base image and replaces base and kernel); this script pins it, keeps
# its reboot for vm.py, adds the guest agent and rsync and writes a config.xml
# with the user the pool's leases log in as.
set -eu
PATH=/sbin:/bin:/usr/sbin:/usr/bin:/usr/local/sbin:/usr/local/bin
export PATH

# A commit, not a branch, and its hash: what runs as root in every bake is the
# script that was read, not whatever stable/ carries that day.
BOOTSTRAP_COMMIT=ef64082e685ba743c4b4d730852652360538551c
BOOTSTRAP_SHA256=ed7c0d9739f375cc941fab7d23033717e1dd16aa2758fc8e544cdb4b90b4f57c
BOOTSTRAP_URL="https://raw.githubusercontent.com/opnsense/update/${BOOTSTRAP_COMMIT}/src/bootstrap/opnsense-bootstrap.sh.in"

die() {
    echo "bootstrap: $*" >&2
    exit 1
}

release=${1:-}
case $release in
[0-9][0-9].[0-9]) ;;
*) die "usage: AH_OPNSENSE_KEY='<public key>' $0 <release, e.g. 26.7>" ;;
esac
case ${AH_OPNSENSE_KEY:-} in
ssh-* | ecdsa-* | sk-*) ;;
*) die "AH_OPNSENSE_KEY is not an ssh public key" ;;
esac
[ "$(id -u)" = 0 ] || die "must run as root"

here=$(cd "$(dirname "$0")" && pwd)
[ -f "$here/config.xml.in" ] || die "no config.xml.in next to $0"
work=$(mktemp -d /tmp/ah-opnsense.XXXXXX)
trap 'rm -rf "$work"' EXIT

fetch -q -o "$work/opnsense-bootstrap.sh" "$BOOTSTRAP_URL"
[ "$(sha256 -q "$work/opnsense-bootstrap.sh")" = "$BOOTSTRAP_SHA256" ] ||
    die "opnsense-bootstrap.sh at $BOOTSTRAP_COMMIT does not hash to the pinned sha256"

# Its last word is a PATH-resolved `reboot`: the reboot is vm.py's, after the
# config below is in place and the template's guest user has been switched.
mkdir "$work/bin"
printf '#!/bin/sh\necho "reboot: left to vm.py"\n' > "$work/bin/reboot"
chmod 0755 "$work/bin/reboot"
PATH="$work/bin:$PATH" sh "$work/opnsense-bootstrap.sh" -r "$release" -y

# The guest agent is how vm.py finds the box's address; rsync is how a lease
# gets its checkout. Both went with the base image's packages.
pkg install -y os-qemu-guest-agent rsync

mkdir -p /conf
# Both passwords are random and nobody keeps them: the web GUI is not part of
# the tests, and the unix password of every account is `*` anyway.
# shellcheck disable=SC2016  # PHP, not shell: its $ are its own
AH_IN="$here/config.xml.in" AH_OUT=/conf/config.xml php -r '
$hash = function () {
    return password_hash(bin2hex(random_bytes(32)), PASSWORD_BCRYPT);
};
$template = file_get_contents(getenv("AH_IN"));
if ($template === false) {
    exit(1);
}
$xml = strtr($template, [
    "@ROOT_HASH@" => $hash(),
    "@USER_HASH@" => $hash(),
    "@AUTHORIZED_KEYS@" => base64_encode(getenv("AH_OPNSENSE_KEY") . "\n"),
]);
if (preg_match("/@[A-Z_]+@/", $xml) || simplexml_load_string($xml) === false) {
    exit(1);
}
exit(file_put_contents(getenv("AH_OUT"), $xml) === false ? 1 : 0);
' || die "config.xml was not rendered"
chmod 0640 /conf/config.xml
sync
echo "bootstrap: OPNsense $release installed, config.xml written; reboot next"
