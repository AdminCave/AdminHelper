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
	"slices"
	"strings"
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

// serviceSection returns the directive lines of the [Service] section of unit, without comments and
// without ExecStart, the one line the twins may differ in.
func serviceSection(t *testing.T, unit string) []string {
	t.Helper()
	var lines []string
	in := false
	for _, line := range strings.Split(unit, "\n") {
		line = strings.TrimSpace(line)
		switch {
		case strings.HasPrefix(line, "["):
			in = line == "[Service]"
		case !in || line == "" || strings.HasPrefix(line, "#") || strings.HasPrefix(line, "ExecStart="):
		default:
			lines = append(lines, line)
		}
	}
	return lines
}

// R-1221: the unit `service install` writes and the one deb/rpm ship are twins, and both keep the
// agent out of the host's way with the resource caps.
func TestServiceUnitMatchesPackagedUnit(t *testing.T) {
	packaged, err := os.ReadFile(filepath.Join("..", "..", "systemd", "adminhelper-agent.service"))
	if err != nil {
		t.Fatal(err)
	}
	dynamic := serviceUnitText("/usr/local/bin/adminhelper-agent")
	if got, want := serviceSection(t, dynamic), serviceSection(t, string(packaged)); !slices.Equal(got, want) {
		t.Errorf("[Service] of the dynamic unit =\n%v\nwant the packaged one\n%v", got, want)
	}
	for _, caps := range []string{"Nice=19", "IOSchedulingClass=idle", "CPUQuota=50%", "MemoryMax=256M", "OOMPolicy=continue"} {
		if !slices.Contains(serviceSection(t, dynamic), caps) {
			t.Errorf("dynamic unit lacks %s", caps)
		}
	}
	if !strings.Contains(dynamic, "\nExecStart=/usr/local/bin/adminhelper-agent run --once\n") {
		t.Errorf("dynamic unit does not run the given binary:\n%s", dynamic)
	}
}
