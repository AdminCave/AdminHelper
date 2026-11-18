// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package monitor

import "context"

// w32tmStatus runs `w32tm /query /status`; a variable so tests can drive collectSystemState without
// the Windows Time service.
var w32tmStatus = func(ctx context.Context) ([]byte, error) {
	return runWithTimeout(ctx, "w32tm", "/query", "/status")
}

// collectSystemState reports the system_state block of a Windows host: only time_synchronized, set
// when w32tm answered readably; why it is missing goes to the log. The state passes through
// unchanged.
func collectSystemState(ctx context.Context, st reportState) (map[string]any, reportState) {
	block := map[string]any{}
	out, err := w32tmStatus(ctx)
	if err != nil {
		logger.Warnf("system state: w32tm /query /status failed: %s, time_synchronized left out",
			commandFailure("w32tm", pluginTimeout, err))
		return block, st
	}
	synced, ok := parseW32tmStatus(out)
	if !ok {
		logger.Warnf("system state: no leap indicator in w32tm /query /status, time_synchronized left out")
		return block, st
	}
	block["time_synchronized"] = synced
	return block, st
}
