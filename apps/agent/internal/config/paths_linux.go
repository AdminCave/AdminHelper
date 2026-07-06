// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package config

import "os"

// The ADMINHELPER_*_DIR overrides exist so the orchestration flows (frpc.Sync/Apply, monitor.Init/
// Push, provision.Run) can run against a t.TempDir() in unit tests instead of only as root against
// the real /etc paths (6.96 — the test seam for 6.1 and the sibling agent coverage gaps).
func FrpDir() string {
	if d := os.Getenv("ADMINHELPER_FRP_DIR"); d != "" {
		return d
	}
	return "/etc/frp"
}

func MonitorDir() string {
	if d := os.Getenv("ADMINHELPER_MONITOR_DIR"); d != "" {
		return d
	}
	return "/etc/adminhelper"
}

func LogDir() string {
	if d := os.Getenv("ADMINHELPER_LOG_DIR"); d != "" {
		return d
	}
	return "/var/log/adminhelper"
}
