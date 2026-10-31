// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package frpc

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

// setSystemctlTimeout sets systemctlTimeout for one test.
func setSystemctlTimeout(t *testing.T, d time.Duration) {
	t.Helper()
	old := systemctlTimeout
	systemctlTimeout = d
	t.Cleanup(func() { systemctlTimeout = old })
}

// systemctlActions are the frpc service actions that run systemctl, each reduced to its error.
var systemctlActions = map[string]func(context.Context) error{
	"frpcActive":        func(ctx context.Context) error { _, err := frpcActive(ctx); return err },
	"restartFrpc":       restartFrpc,
	"disableFrpc":       disableFrpc,
	"enableFrpcService": enableFrpcService,
}

// endsWithin returns the error of call, and fails the test when call does not return within d.
func endsWithin(t *testing.T, d time.Duration, call func() error) error {
	t.Helper()
	res := make(chan error, 1)
	go func() { res <- call() }()
	select {
	case err := <-res:
		return err
	case <-time.After(d):
		t.Fatalf("the call did not return within %s", d)
		return nil
	}
}

// R-0638: a systemctl that does not answer (hung systemd or D-Bus) costs the sync its cap, not the
// run. Each call ends with context.DeadlineExceeded, not with the "signal: killed" of the kill.
func TestFrpcSystemctlTimesOut(t *testing.T) {
	fakeSystemctl(t, "exec /bin/sleep 30")
	setSystemctlTimeout(t, 200*time.Millisecond)
	for name, action := range systemctlActions {
		t.Run(name, func(t *testing.T) {
			err := endsWithin(t, 3*time.Second, func() error { return action(context.Background()) })
			if !errors.Is(err, context.DeadlineExceeded) {
				t.Errorf("%s = %v, want an error that wraps context.DeadlineExceeded", name, err)
			}
		})
	}
}

// R-0638: a systemctl call of the sync ends with the run's context, long before its cap.
func TestFrpcSystemctlEndsWithTheContext(t *testing.T) {
	fakeSystemctl(t, "exec /bin/sleep 30")
	setSystemctlTimeout(t, time.Minute)
	for name, action := range systemctlActions {
		t.Run(name, func(t *testing.T) {
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			timer := time.AfterFunc(100*time.Millisecond, cancel)
			defer timer.Stop()
			err := endsWithin(t, 3*time.Second, func() error { return action(ctx) })
			if !errors.Is(err, context.Canceled) {
				t.Errorf("%s = %v, want an error that wraps context.Canceled", name, err)
			}
		})
	}
}

// is-active answers with its exit status: 0 is a running frpc, any other a frpc that does not
// run. A call without an exit status (here: systemctl does not start) is an error, not a stopped
// frpc, for frpcActive as for frpcDown.
func TestFrpcSystemctlIsActiveExitStatus(t *testing.T) {
	for name, tc := range map[string]struct {
		script string
		active bool
	}{
		"exit 0": {"exit 0", true},
		"exit 3": {"exit 3", false},
	} {
		t.Run(name, func(t *testing.T) {
			fakeSystemctl(t, tc.script)
			if active, err := frpcActive(context.Background()); active != tc.active || err != nil {
				t.Errorf("frpcActive = %v, %v, want %v, nil", active, err, tc.active)
			}
			if down, err := frpcDown(context.Background()); down == tc.active || err != nil {
				t.Errorf("frpcDown = %v, %v, want %v, nil", down, err, !tc.active)
			}
		})
	}
	t.Run("not started", func(t *testing.T) {
		t.Setenv("PATH", t.TempDir())
		if _, err := frpcActive(context.Background()); err == nil {
			t.Error("frpcActive without a systemctl = nil error, want the failed start")
		}
		if _, err := frpcDown(context.Background()); err == nil {
			t.Error("frpcDown without a systemctl = nil error, want the failed start")
		}
	})
}

// R-0641: starting frpc is part of a run's sync, so it leaves adminhelper-agent.timer alone;
// enabled beside a `run` without --once, the timer would run every cycle a second time. Only the
// setup enables the timer (service.EnableTimer).
func TestFrpcEnableLeavesTheTimerAlone(t *testing.T) {
	calls := filepath.Join(t.TempDir(), "calls")
	fakeSystemctl(t, `printf '%s\n' "$*" >> '`+calls+`'`)

	if err := enableFrpcService(context.Background()); err != nil {
		t.Fatalf("enableFrpcService: %v", err)
	}
	got, err := os.ReadFile(calls)
	if err != nil {
		t.Fatal(err)
	}
	if want := "daemon-reload\nenable --now frpc.service\n"; string(got) != want {
		t.Errorf("systemctl calls = %q, want %q and no adminhelper-agent.timer", got, want)
	}
}
