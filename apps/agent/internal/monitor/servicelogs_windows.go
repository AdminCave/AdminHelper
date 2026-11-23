// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package monitor

import "context"

// serviceLogsSupported: the error lines of a stopped automatic service come from the event log
// (winevents.go, R-1391).
const serviceLogsSupported = true

// serviceLogUnitsListed: a Windows block has no failed services, so it names the services with
// error lines in log_units (windowsLogUnits).
const serviceLogUnitsListed = true

// serviceLogUnits are the services whose error lines are sent (windowsLogUnits).
func serviceLogUnits(systemd *ServiceHealth) ([]string, map[string]string) {
	return windowsLogUnits(systemd)
}

// newServiceLogReader opens one run's reader: two event queries for all services together.
func newServiceLogReader() func(context.Context, string) ([]string, bool) {
	return windowsLogReader(runWithTimeout)
}
