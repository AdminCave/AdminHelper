// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package service

import "fmt"

// cronTimeoutSec caps a run like TimeoutStartSec=270 of the systemd unit (enough for the serial
// collector timeouts plus the monitor-push retry, 4.13); cronKillAfterSec follows the SIGTERM with
// a SIGKILL. Together they stay below the five-minute interval, so two runs never overlap.
const (
	cronTimeoutSec   = 270
	cronKillAfterSec = 10
)

// cronTable returns the agent's file for /usr/local/etc/cron.d on FreeBSD: a system crontab
// (crontab(5): five time fields, the user, the command) that runs bin once every five minutes
// as root, at the lowest CPU priority, under timeout(1). Its own PATH keeps login.conf out of
// the commands the agent runs by name (service, sockstat, pkg). The output is discarded rather
// than mailed: the agent writes agent.log itself. This file has no build tag so the Linux
// tests check the line; only service_freebsd.go uses it.
func cronTable(bin string) string {
	return fmt.Sprintf(`# AdminHelper agent: frpc sync and monitoring every five minutes.
# Written by adminhelper-agent (service install, provision); service uninstall removes it.
SHELL=/bin/sh
PATH=/sbin:/bin:/usr/sbin:/usr/bin:/usr/local/sbin:/usr/local/bin
*/5 * * * * root /usr/bin/nice -n 19 /usr/bin/timeout -k %d %d %s run --once >/dev/null 2>&1
`, cronKillAfterSec, cronTimeoutSec, bin)
}
