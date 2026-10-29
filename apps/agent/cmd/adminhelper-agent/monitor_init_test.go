// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package main

import (
	"errors"
	"io"
	"testing"

	"adminhelper-agent/internal/monitor"
)

// stubMonitorInit puts init in place of monitor.Init and a counter in place of
// service.EnableTimer (systemctl on Linux) for one test; the timer stub returns timerErr.
func stubMonitorInit(t *testing.T, init func(monitor.InitParams) error, timerErr error) *int {
	t.Helper()
	calls := 0
	origInit, origTimer := monitorInit, enableTimer
	monitorInit = init
	enableTimer = func() error { calls++; return timerErr }
	t.Cleanup(func() { monitorInit, enableTimer = origInit, origTimer })
	return &calls
}

// runMonitorInit runs `monitor init` with the required flags and returns its error.
func runMonitorInit() error {
	cmd := monitorInitCmd()
	cmd.SetArgs([]string{"--url", "https://monitor.example/api/monitoring", "--api-key", "key", "--server-id", "srv-1"})
	cmd.SetOut(io.Discard)
	cmd.SetErr(io.Discard)
	return cmd.Execute()
}

// R-0641: `monitor init` is a setup, so it enables the agent timer, once and only after the
// monitor is set up; a refused setup (wrong trust, no certificate to pin) enables nothing. A
// timer that cannot be enabled is a warning, the setup stands.
func TestMonitorInitEnablesTheTimerAfterTheSetup(t *testing.T) {
	t.Run("setup done", func(t *testing.T) {
		var got monitor.InitParams
		calls := stubMonitorInit(t, func(p monitor.InitParams) error {
			got = p
			return nil
		}, nil)

		if err := runMonitorInit(); err != nil {
			t.Fatalf("monitor init: %v", err)
		}
		if *calls != 1 {
			t.Errorf("timer enabled %d times, want 1", *calls)
		}
		if got.URL != "https://monitor.example/api/monitoring" || got.APIKey != "key" || got.ServerID != "srv-1" {
			t.Errorf("monitor.Init got %+v, want the flags", got)
		}
	})
	t.Run("setup refused", func(t *testing.T) {
		refused := errors.New("--cacert cannot be combined with --insecure")
		calls := stubMonitorInit(t, func(monitor.InitParams) error {
			return refused
		}, nil)

		if err := runMonitorInit(); !errors.Is(err, refused) {
			t.Errorf("monitor init = %v, want the error of monitor.Init", err)
		}
		if *calls != 0 {
			t.Errorf("timer enabled %d times after a refused setup, want 0", *calls)
		}
	})
	t.Run("timer cannot be enabled", func(t *testing.T) {
		calls := stubMonitorInit(t, func(monitor.InitParams) error { return nil },
			errors.New("systemctl enable --now adminhelper-agent.timer: exit status 1"))

		if err := runMonitorInit(); err != nil {
			t.Errorf("monitor init = %v, want nil: the setup stands", err)
		}
		if *calls != 1 {
			t.Errorf("timer enabled %d times, want 1", *calls)
		}
	})
}
