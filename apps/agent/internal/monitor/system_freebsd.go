// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build freebsd

package monitor

import "context"

// collectSystemState reports reboot_required and security_updates (freebsdSystemState). FreeBSD has
// no counter of OOM kills like Linux' /proc/vmstat, so oom_kills stays out.
func collectSystemState(ctx context.Context, st reportState) (map[string]any, reportState) {
	return freebsdSystemState(ctx, st)
}
