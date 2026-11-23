// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package monitor

import (
	"context"
	"reflect"
	"testing"
	"time"
)

// The Windows block names its stopped automatic services with an exit as log_units, and their lines
// go out once per failure, keyed by the since of the SCM crash events.
func TestBuildReportSendsTheLinesOfStoppedAutomaticServicesOncePerFailure(t *testing.T) {
	stubReportHost(t)
	services := []ServiceEntry{
		{"unit": "Spooler", "active_state": "inactive", "enabled_state": "enabled", "exit": "1067", "since": "2026-11-19T08:00:00Z"},
		{"unit": "Manual", "active_state": "inactive", "enabled_state": "manual", "exit": "1"},
		{"unit": "W32Time", "active_state": "active", "enabled_state": "enabled"},
	}
	serviceHealthCollector = func(context.Context) *ServiceHealth {
		return &ServiceHealth{AllServices: append([]ServiceEntry{}, services...)}
	}
	old := serviceLogReader
	t.Cleanup(func() { serviceLogReader = old })
	var read []string
	serviceLogReader = func() func(context.Context, string) ([]string, bool) {
		return func(_ context.Context, unit string) ([]string, bool) {
			read = append(read, unit)
			return []string{"error of " + unit}, true
		}
	}
	work := &probeWork{serviceLogs: true}
	var state reportState
	run := func() map[string]any {
		t.Helper()
		read = nil
		var report map[string]any
		report, state = buildReportWithState(context.Background(), nil, work, state, time.Now())
		return report
	}

	report := run()
	svc, _ := report["systemd"].(*ServiceHealth)
	if !reflect.DeepEqual(svc.LogUnits, []string{"Spooler"}) {
		t.Fatalf("log_units = %#v, want [Spooler]", svc.LogUnits)
	}
	want := map[string]any{"Spooler": map[string]any{"since": "2026-11-19T08:00:00Z", "lines": []string{"error of Spooler"}}}
	if logs := failedLogs(t, report); !reflect.DeepEqual(logs, want) {
		t.Fatalf("failed_logs = %#v, want %#v", logs, want)
	}

	// Same failure: log_units again, nothing read, nothing sent.
	report = run()
	if svc, _ := report["systemd"].(*ServiceHealth); !reflect.DeepEqual(svc.LogUnits, []string{"Spooler"}) {
		t.Errorf("second run: log_units = %#v", svc.LogUnits)
	}
	if logs := failedLogs(t, report); logs != nil || len(read) != 0 {
		t.Fatalf("same failure: failed_logs %#v, read %v; want none", logs, read)
	}

	// Spooler crashes anew: its lines go out again.
	services[0]["since"] = "2026-11-19T09:00:00Z"
	if logs := failedLogs(t, run()); len(logs) != 1 || !reflect.DeepEqual(read, []string{"Spooler"}) {
		t.Fatalf("new crash: failed_logs %#v, read %v; want Spooler once", logs, read)
	}
}

// failedLogs is the failed_logs of the report's systemd block (as in servicelogs_linux_test.go).
func failedLogs(t *testing.T, report map[string]any) map[string]any {
	t.Helper()
	if svc, _ := report["systemd"].(*ServiceHealth); svc != nil {
		return svc.FailedLogs
	}
	return nil
}
