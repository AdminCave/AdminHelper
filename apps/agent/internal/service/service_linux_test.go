// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package service

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"
)

// fakeSystemctl puts a systemctl that runs script on the PATH, and nothing else there: no test
// reaches the host's systemd. script calls other programs by absolute path.
func fakeSystemctl(t *testing.T, script string) {
	t.Helper()
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "systemctl"), []byte("#!/bin/sh\n"+script+"\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", dir)
}

// R-0641: EnableTimer, the one place of the setup that enables the agent timer, enables and
// starts exactly adminhelper-agent.timer.
func TestEnableTimerEnablesTheAgentTimer(t *testing.T) {
	calls := filepath.Join(t.TempDir(), "calls")
	fakeSystemctl(t, `printf '%s\n' "$*" >> '`+calls+`'`)

	if err := EnableTimer(); err != nil {
		t.Fatalf("EnableTimer: %v", err)
	}
	got, err := os.ReadFile(calls)
	if err != nil {
		t.Fatal(err)
	}
	if want := "enable --now adminhelper-agent.timer\n"; string(got) != want {
		t.Errorf("systemctl calls = %q, want %q", got, want)
	}
}

// A systemctl that does not answer (hung systemd or D-Bus) costs the setup the cap, and the call
// ends with context.DeadlineExceeded, not with the "signal: killed" of the kill.
func TestEnableTimerTimesOut(t *testing.T) {
	fakeSystemctl(t, "exec /bin/sleep 30")
	old := timerTimeout
	timerTimeout = 200 * time.Millisecond
	t.Cleanup(func() { timerTimeout = old })

	res := make(chan error, 1)
	go func() { res <- EnableTimer() }()
	select {
	case err := <-res:
		if !errors.Is(err, context.DeadlineExceeded) {
			t.Errorf("EnableTimer = %v, want an error that wraps context.DeadlineExceeded", err)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("EnableTimer did not return within 3s")
	}
}
