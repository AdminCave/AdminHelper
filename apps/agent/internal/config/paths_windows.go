// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package config

import (
	"os"
	"path/filepath"
)

// ADMINHELPER_*_DIR overrides mirror paths_linux.go so the orchestration flows are unit-testable
// against a t.TempDir() on either platform (6.96).
func FrpDir() string {
	if d := os.Getenv("ADMINHELPER_FRP_DIR"); d != "" {
		return d
	}
	return filepath.Join(os.Getenv("ProgramData"), "AdminHelper", "frp")
}

func MonitorDir() string {
	if d := os.Getenv("ADMINHELPER_MONITOR_DIR"); d != "" {
		return d
	}
	return filepath.Join(os.Getenv("ProgramData"), "AdminHelper")
}

func LogDir() string {
	if d := os.Getenv("ADMINHELPER_LOG_DIR"); d != "" {
		return d
	}
	return filepath.Join(os.Getenv("ProgramData"), "AdminHelper", "logs")
}
