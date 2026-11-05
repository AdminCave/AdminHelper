#!/bin/bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Starts xrdp-sesman and xrdp in the foreground with a certificate of this start, prints
# "xrdp-gfx: ready" once xrdp listens, and ends when either of them does.
set -eu

# A certificate of its own per container: the live test pins exactly this one.
rm -f /etc/xrdp/cert.pem /etc/xrdp/key.pem
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj /CN=xrdp-gfx \
    -keyout /etc/xrdp/key.pem -out /etc/xrdp/cert.pem 2>/dev/null
if id xrdp >/dev/null 2>&1; then
    chown root:xrdp /etc/xrdp/key.pem
fi
chmod 640 /etc/xrdp/key.pem

xrdp-sesman --nodaemon &
xrdp --nodaemon &

# 3389 is 0D3D, 0A is LISTEN in /proc/net/tcp; no ss or netstat in the image.
i=0
until grep -q ':0D3D [0-9A-F:]* 0A ' /proc/net/tcp /proc/net/tcp6 2>/dev/null; do
    i=$((i + 1))
    [ "$i" -le 100 ] || { echo "xrdp-gfx: xrdp does not listen" >&2; exit 1; }
    sleep 0.1
done
echo "xrdp-gfx: ready"

# Neither may die unnoticed: the container ends with the first of them.
wait -n
