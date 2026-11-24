// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package config

// The ADMINHELPER_*_DIR overrides let the orchestration flows (frpc.Sync/Apply, push.Init/Push,
// provision.Run) run against a t.TempDir() in unit tests; outside a test binary they are ignored
// (override in paths.go).
func FrpDir() string {
	if d := override("ADMINHELPER_FRP_DIR"); d != "" {
		return d
	}
	return "/etc/frp"
}

func MonitorDir() string {
	if d := override("ADMINHELPER_MONITOR_DIR"); d != "" {
		return d
	}
	return "/etc/adminhelper"
}

func LogDir() string {
	if d := override("ADMINHELPER_LOG_DIR"); d != "" {
		return d
	}
	return "/var/log/adminhelper"
}
