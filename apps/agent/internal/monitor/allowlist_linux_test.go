// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package monitor

import (
	"context"
	"fmt"
	"reflect"
	"testing"
)

// TestAllowlistTakesTheSystemctlProperties ties the property lists of services_linux.go to the list:
// a property added there without an entry would refuse every show call.
func TestAllowlistTakesTheSystemctlProperties(t *testing.T) {
	for _, props := range []string{aliasProps, watchedProps, enabledInactiveProps} {
		if !commandAllowed("systemctl", []string{"show", "-p", props, "--", "nginx.service"}) {
			t.Errorf("show -p %s refused", props)
		}
	}
}

// TestWatchedServicesSkipAnInvalidName: a watched name outside the unit class is reported not running
// without asking, and the others still get their status (the allowlist refused the whole batch, and
// every watched unit passed for down). The fake systemctl refuses as runTimed would.
func TestWatchedServicesSkipAnInvalidName(t *testing.T) {
	old := runSystemctl
	t.Cleanup(func() { runSystemctl = old })
	var calls [][]string
	runSystemctl = func(_ context.Context, args ...string) ([]byte, error) {
		calls = append(calls, args)
		if !commandAllowed("systemctl", args) {
			return nil, fmt.Errorf("systemctl: %w", errCommandNotAllowed)
		}
		return []byte("Id=systemd-journald.service\nNames=systemd-journald.service\nActiveState=active\nMainPID=600\n"), nil
	}
	got := collectWatchedServices(context.Background(), []string{"my svc", "systemd-journald", "a/b"})
	want := []map[string]any{
		{"name": "my svc", "running": false, "pid": nil},
		{"name": "systemd-journald", "running": true, "pid": "600"},
		{"name": "a/b", "running": false, "pid": nil},
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("collectWatchedServices = %v, want %v", got, want)
	}
	if len(calls) != 1 || !commandAllowed("systemctl", calls[0]) {
		t.Errorf("systemctl calls = %q, want one allowed batch", calls)
	}
	runSystemctl = func(context.Context, ...string) ([]byte, error) {
		t.Error("systemctl asked for invalid names only")
		return nil, nil
	}
	if got := collectWatchedServices(context.Background(), []string{"--help"}); len(got) != 1 || got[0]["running"] != false {
		t.Errorf("collectWatchedServices(--help) = %v", got)
	}
}
