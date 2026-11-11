// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build freebsd

package service

import (
	"os"
	"path/filepath"
	"testing"
)

// EnableTimer writes the cron table under a dot name, which cron skips, and renames it into
// place with mode 0644, also over a staged file a former run left with another mode.
func TestEnableTimerInstallsTheCronFile(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "cron.d")
	old := cronFile
	cronFile = filepath.Join(dir, "adminhelper")
	t.Cleanup(func() { cronFile = old })
	staged := filepath.Join(dir, ".adminhelper.tmp")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(staged, []byte("stale"), 0o600); err != nil {
		t.Fatal(err)
	}

	if err := EnableTimer(); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(cronFile)
	if err != nil {
		t.Fatal(err)
	}
	if string(data) != cronTable(agentBinary) {
		t.Errorf("cron file = %q, want %q", data, cronTable(agentBinary))
	}
	info, err := os.Stat(cronFile)
	if err != nil {
		t.Fatal(err)
	}
	if mode := info.Mode().Perm(); mode != 0o644 {
		t.Errorf("cron file mode = %o, want 644", mode)
	}
	if _, err := os.Stat(staged); !os.IsNotExist(err) {
		t.Errorf("the staged file is still there: %v", err)
	}
}
