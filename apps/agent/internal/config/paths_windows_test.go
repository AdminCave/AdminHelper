// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package config

import (
	"os"
	"path/filepath"
	"testing"

	"golang.org/x/sys/windows"
)

func TestDataDirsIgnoreTheProgramDataVariable(t *testing.T) {
	pd, err := windows.KnownFolderPath(windows.FOLDERID_ProgramData, 0)
	if err != nil {
		t.Fatal(err)
	}
	t.Setenv("ProgramData", t.TempDir())
	for _, v := range []string{"ADMINHELPER_MONITOR_DIR", "ADMINHELPER_FRP_DIR", "ADMINHELPER_LOG_DIR"} {
		t.Setenv(v, "")
	}
	root := filepath.Join(pd, "AdminHelper")
	for _, c := range []struct{ name, got, want string }{
		{"MonitorDir", MonitorDir(), root},
		{"FrpDir", FrpDir(), filepath.Join(root, "frp")},
		{"LogDir", LogDir(), filepath.Join(root, "logs")},
	} {
		if c.got != c.want {
			t.Errorf("%s = %q, want %q", c.name, c.got, c.want)
		}
	}
}

// Outside a test binary the overrides are ignored: the caller's environment never moves the data.
func TestDataDirsIgnoreTheOverridesOutsideTests(t *testing.T) {
	pd, err := windows.KnownFolderPath(windows.FOLDERID_ProgramData, 0)
	if err != nil {
		t.Fatal(err)
	}
	prev := overridesAllowed
	t.Cleanup(func() { overridesAllowed = prev })
	overridesAllowed = func() bool { return false }
	for _, v := range []string{"ADMINHELPER_MONITOR_DIR", "ADMINHELPER_FRP_DIR", "ADMINHELPER_LOG_DIR"} {
		t.Setenv(v, t.TempDir())
	}
	root := filepath.Join(pd, "AdminHelper")
	for _, c := range []struct{ name, got, want string }{
		{"MonitorDir", MonitorDir(), root},
		{"FrpDir", FrpDir(), filepath.Join(root, "frp")},
		{"LogDir", LogDir(), filepath.Join(root, "logs")},
	} {
		if c.got != c.want {
			t.Errorf("%s = %q, want %q", c.name, c.got, c.want)
		}
	}
	overridesAllowed = func() bool { return true }
	if got := MonitorDir(); got != os.Getenv("ADMINHELPER_MONITOR_DIR") {
		t.Errorf("in a test run MonitorDir = %q, want the override", got)
	}
}
