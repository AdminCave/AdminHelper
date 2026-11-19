// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build !linux && !freebsd && !windows

package monitor

import "context"

// collectSystemState has no system_state block outside Linux, FreeBSD and Windows; the state passes through
// unchanged.
func collectSystemState(_ context.Context, st reportState) (map[string]any, reportState) {
	return nil, st
}
