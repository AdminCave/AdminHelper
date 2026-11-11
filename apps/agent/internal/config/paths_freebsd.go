// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build freebsd

package config

import "os"

// FreeBSD keeps the configuration of third-party software under /usr/local/etc (hier(7)); the
// ADMINHELPER_*_DIR overrides are the same test seam as on Linux (paths_linux.go).
func FrpDir() string {
	if d := os.Getenv("ADMINHELPER_FRP_DIR"); d != "" {
		return d
	}
	return "/usr/local/etc/adminhelper/frp"
}

func MonitorDir() string {
	if d := os.Getenv("ADMINHELPER_MONITOR_DIR"); d != "" {
		return d
	}
	return "/usr/local/etc/adminhelper"
}

func LogDir() string {
	if d := os.Getenv("ADMINHELPER_LOG_DIR"); d != "" {
		return d
	}
	return "/var/log/adminhelper"
}
