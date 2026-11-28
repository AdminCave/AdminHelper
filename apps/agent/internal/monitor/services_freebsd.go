// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build freebsd

package monitor

import (
	"context"
	"os"
	"time"
)

// runService runs service(8) under the plugin timeout, by its full path so the PATH of the caller
// does not matter.
func runService(ctx context.Context, args ...string) ([]byte, error) {
	return runWithTimeout(ctx, "/usr/sbin/service", args...)
}

// collectServiceHealth collects the rc.d service status (rcServiceHealth); ctx ends every service
// call.
func collectServiceHealth(ctx context.Context) *ServiceHealth {
	return rcServiceHealth(ctx, runService, os.ReadFile)
}

// collectServiceHealthCached is collectServiceHealth through the cache the last run left
// (rcServiceHealthCached).
func collectServiceHealthCached(ctx context.Context, saved *serviceCache, now time.Time) (*ServiceHealth, *serviceCache) {
	return rcServiceHealthCached(ctx, runService, os.ReadFile, func() string { return rcConfStamp(rcConfPaths) }, saved, now)
}

// collectWatchedServices checks the status of the watched rc.d services (rcWatchedServices); ctx ends
// every service call.
func collectWatchedServices(ctx context.Context, names []string) []WatchedService {
	return rcWatchedServices(ctx, runService, names)
}
