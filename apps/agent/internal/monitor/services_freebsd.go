// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build freebsd

package monitor

import (
	"context"
	"os"
)

// runService runs service(8) under the plugin timeout, by its full path so the PATH of the caller
// does not matter.
func runService(ctx context.Context, args ...string) ([]byte, error) {
	return runWithTimeout(ctx, "/usr/sbin/service", args...)
}

// collectServiceHealth collects the rc.d service status (rcServiceHealth); ctx ends every service
// call.
func collectServiceHealth(ctx context.Context) map[string]any {
	return rcServiceHealth(ctx, runService, os.ReadFile)
}

// collectWatchedServices checks the status of the watched rc.d services (rcWatchedServices); ctx ends
// every service call.
func collectWatchedServices(ctx context.Context, names []string) []map[string]any {
	return rcWatchedServices(ctx, runService, names)
}
