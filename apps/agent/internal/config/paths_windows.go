// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package config

import (
	"os"
	"path/filepath"
	"sync"
	"testing"

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

// overridesAllowed gates the ADMINHELPER_*_DIR overrides to test binaries: they exist so the
// orchestration flows run against a t.TempDir() (6.96), and an elevated console inherits the
// caller's variables, which must not move an administrator's data (R-1645).
var overridesAllowed = testing.Testing

func override(name string) string {
	if !overridesAllowed() {
		return ""
	}
	return os.Getenv(name)
}

func FrpDir() string {
	if d := override("ADMINHELPER_FRP_DIR"); d != "" {
		return d
	}
	return filepath.Join(programData(), "AdminHelper", "frp")
}

func MonitorDir() string {
	if d := override("ADMINHELPER_MONITOR_DIR"); d != "" {
		return d
	}
	return filepath.Join(programData(), "AdminHelper")
}

func LogDir() string {
	if d := override("ADMINHELPER_LOG_DIR"); d != "" {
		return d
	}
	return filepath.Join(programData(), "AdminHelper", "logs")
}
