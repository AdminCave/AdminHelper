// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build !linux

package monitor

// collectSystemState has no system_state block outside Linux; the state passes through unchanged.
func collectSystemState(st reportState) (map[string]any, reportState) {
	return nil, st
}
