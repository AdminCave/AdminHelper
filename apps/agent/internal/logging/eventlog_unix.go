// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux || freebsd

package logging

// platformReporter returns nil on Linux and FreeBSD: systemd keeps the service's stdout
// in the journal, and on FreeBSD, where the cron job discards stdout, agent.log carries
// every line; Init has nothing to report elsewhere.
func platformReporter() reportFunc {
	return nil
}
