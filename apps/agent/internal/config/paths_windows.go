// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package config

import (
	"os"
	"path/filepath"
	"sync"

	"golang.org/x/sys/windows"
)

// defaultProgramData is the Windows default, taken if the known-folder API fails.
const defaultProgramData = `C:\ProgramData`

// programData is the ProgramData folder from the known-folder API, never from the environment:
// a user variable, which an elevated console inherits, must not choose where an administrator's
// run keeps and locks the agent's data (like service.Purge).
var programData = sync.OnceValue(func() string {
	if pd, err := windows.KnownFolderPath(windows.FOLDERID_ProgramData, 0); err == nil && pd != "" {
		return pd
	}
	return defaultProgramData
})

// ADMINHELPER_*_DIR overrides mirror paths_linux.go so the orchestration flows are unit-testable
// against a t.TempDir() on either platform (6.96).
func FrpDir() string {
	if d := os.Getenv("ADMINHELPER_FRP_DIR"); d != "" {
		return d
	}
	return filepath.Join(programData(), "AdminHelper", "frp")
}

func MonitorDir() string {
	if d := os.Getenv("ADMINHELPER_MONITOR_DIR"); d != "" {
		return d
	}
	return filepath.Join(programData(), "AdminHelper")
}

func LogDir() string {
	if d := os.Getenv("ADMINHELPER_LOG_DIR"); d != "" {
		return d
	}
	return filepath.Join(programData(), "AdminHelper", "logs")
}
