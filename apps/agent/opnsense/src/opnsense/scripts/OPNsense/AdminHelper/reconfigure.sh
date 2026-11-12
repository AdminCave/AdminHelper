#!/bin/sh
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

# reconfigure.sh on|off applies the switch of the settings page. configd runs it after the template
# has written the tunnel client's rcvar (YES only with the switch on and a tunnel). on schedules a
# registered agent again and starts the tunnel client unless it runs; off removes the schedule,
# then stops the tunnel client, so no run of the agent starts it again. The registration and the
# agent's files stay either way.

etc=/usr/local/etc/adminhelper
agent=/usr/local/bin/adminhelper-agent

case "$1" in
on)
    if [ -f "$etc/frp/adminhelper.conf" ] || [ -f "$etc/monitor.conf" ]; then
        "$agent" service install >/dev/null || exit 1
    fi
    if [ -f "$etc/frp/frpc.toml" ] && ! /usr/sbin/service adminhelper_frpc onestatus >/dev/null 2>&1; then
        /usr/sbin/service adminhelper_frpc start >/dev/null || exit 1
    fi
    ;;
off)
    "$agent" service uninstall >/dev/null || exit 1
    /usr/sbin/service adminhelper_frpc faststop >/dev/null || exit 1
    ;;
*)
    echo "usage: reconfigure.sh on|off" >&2
    exit 64
    ;;
esac
