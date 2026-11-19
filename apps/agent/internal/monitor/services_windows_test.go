// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package monitor

import "testing"

func TestReWinServiceNameRejectsOptionLikeNames(t *testing.T) {
	// 3.44: sc has no `--`, so a server-supplied name that looks like a query option
	// (type=, state=, bufsize=) must be rejected before it reaches `sc query`.
	valid := []string{"Spooler", "W32Time", "my.service", "svc_1", "svc-2", "MSSQL$SQLEXPRESS"}
	for _, n := range valid {
		if !reWinServiceName.MatchString(n) {
			t.Errorf("gueltiger Service-Name %q wurde abgelehnt", n)
		}
	}
	invalid := []string{"type= driver", "state= all", "bufsize= 100", "svc name", "a=b", "", `a\b`, "a/b"}
	for _, n := range invalid {
		if reWinServiceName.MatchString(n) {
			t.Errorf("option-aehnlicher Name %q wurde akzeptiert", n)
		}
	}
}

func TestServiceStartStatesReadsTheRegistry(t *testing.T) {
	// EventLog starts automatically on every Windows without a trigger; a service that does not
	// exist and a name with a path separator are left out.
	got := serviceStartStates([]string{"EventLog", "NoSuchService-AdminHelper", `EventLog\..\x`})
	if got["EventLog"] != "enabled" {
		t.Errorf("EventLog = %q, want enabled", got["EventLog"])
	}
	if len(got) != 1 {
		t.Errorf("start states = %v, want only EventLog", got)
	}
}
