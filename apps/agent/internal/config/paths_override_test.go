// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package config

import (
	"os"
	"testing"
)

// The ADMINHELPER_*_DIR overrides move the data dirs only in a test binary; a root or elevated
// run that keeps the caller's environment (sudo -E) gets the fixed paths (R-1655).
func TestDataDirOverridesApplyOnlyInTests(t *testing.T) {
	dirs := []struct {
		env string
		get func() string
	}{
		{"ADMINHELPER_MONITOR_DIR", MonitorDir},
		{"ADMINHELPER_FRP_DIR", FrpDir},
		{"ADMINHELPER_LOG_DIR", LogDir},
	}
	prev := overridesAllowed
	t.Cleanup(func() { overridesAllowed = prev })
	for _, d := range dirs {
		t.Setenv(d.env, "")
	}
	overridesAllowed = func() bool { return false }
	defaults := make([]string, len(dirs))
	for i, d := range dirs {
		defaults[i] = d.get()
	}
	for _, d := range dirs {
		t.Setenv(d.env, t.TempDir())
	}
	for i, d := range dirs {
		if got := d.get(); got != defaults[i] {
			t.Errorf("%s set outside a test: dir = %q, want the default %q", d.env, got, defaults[i])
		}
	}
	overridesAllowed = func() bool { return true }
	for _, d := range dirs {
		if got, want := d.get(), os.Getenv(d.env); got != want || want == "" {
			t.Errorf("%s set in a test: dir = %q, want %q", d.env, got, want)
		}
	}
}
