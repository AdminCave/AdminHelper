// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package monitor

import (
	"context"
)

// serviceLogsSupported: the error lines come from the journal.
const serviceLogsSupported = true

// serviceLogUnitsListed: the failed units are the ones with error lines, so the block needs no
// log_units.
const serviceLogUnitsListed = false

// serviceLogUnits are the units whose error lines are sent: the failed ones (failedUnits).
func serviceLogUnits(systemd *ServiceHealth) ([]string, map[string]string) {
	return failedUnits(systemd)
}

// newServiceLogReader opens one run's reader: a journalctl call per unit (readServiceLog).
func newServiceLogReader() func(context.Context, string) ([]string, bool) {
	return readServiceLog
}

// journalCLI indirects the journalctl lookup and call of readServiceLog so tests can drive it without
// a journal (same reason as systemCLI). The call runs under pluginTimeout and ctx.
var journalCLI = newCommand()

// readServiceLog reads the last maxLogLines journal entries of unit, every priority, each bare
// message (journalctl(1): --unit, --lines, --output=cat), through serviceLogLines. ok is false for a
// name outside the unit class, which the allowlist would refuse, without journalctl, or when the
// call fails; the log says why.
func readServiceLog(ctx context.Context, unit string) ([]string, bool) {
	if !reUnitName.MatchString(unit) {
		return nil, false
	}
	if _, err := journalCLI.lookPath("journalctl"); err != nil {
		logger.Warnf("service logs: journalctl not found, no error lines")
		return nil, false
	}
	out, err := journalCLI.run(ctx, pluginTimeout, nil, "journalctl", "--no-pager", "--quiet", "--output=cat",
		"--unit="+unit, "--lines=10")
	if err != nil {
		logger.Warnf("service logs: journalctl --unit=%s failed: %s", unit,
			commandFailure("journalctl", pluginTimeout, err))
		return nil, false
	}
	return serviceLogLines(out), true
}
