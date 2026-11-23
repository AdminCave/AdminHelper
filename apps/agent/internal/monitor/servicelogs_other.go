// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build !linux && !windows

package monitor

import "context"

// serviceLogsSupported: FreeBSD sends no error lines; the admin reads the syslog (R-1391).
const serviceLogsSupported = false

const serviceLogUnitsListed = false

func serviceLogUnits(systemd *ServiceHealth) ([]string, map[string]string) {
	return failedUnits(systemd)
}

func newServiceLogReader() func(context.Context, string) ([]string, bool) {
	return func(context.Context, string) ([]string, bool) { return nil, false }
}
