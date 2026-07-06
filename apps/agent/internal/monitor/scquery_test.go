// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import "testing"

// Realistic `sc query state= all` output: CRLF line endings, indented property lines, two records.
const scFixture = "SERVICE_NAME: Dnscache\r\n" +
	"        TYPE               : 20  WIN32_SHARE_PROCESS\r\n" +
	"        STATE              : 4  RUNNING\r\n" +
	"\r\n" +
	"SERVICE_NAME: Spooler\r\n" +
	"        STATE              : 1  STOPPED\r\n"

func TestParseScQueryKeepsLastService(t *testing.T) {
	got := parseScQuery(scFixture)
	if len(got) != 2 {
		t.Fatalf("want 2 services, got %d: %v", len(got), got)
	}
	if got[0]["unit"] != "Dnscache" || got[0]["active_state"] != "active" {
		t.Errorf("Dnscache: %v", got[0])
	}
	// The flush after the loop must emit the LAST service — the off-by-one the flush exists to guard.
	if got[1]["unit"] != "Spooler" || got[1]["active_state"] != "inactive" {
		t.Errorf("Spooler (last service dropped?): %v", got[1])
	}
}

func TestParseScQueryEmpty(t *testing.T) {
	if got := parseScQuery(""); len(got) != 0 {
		t.Errorf("empty input should yield no services, got %v", got)
	}
}

func TestMapWindowsServiceStates(t *testing.T) {
	cases := map[string]string{
		"RUNNING":       "active",
		"STOPPED":       "inactive",
		"PAUSED":        "inactive",
		"START_PENDING": "activating",
		"STOP_PENDING":  "activating",
		"WEIRD":         "unknown",
	}
	for state, want := range cases {
		if got := mapWindowsService("svc", state)["active_state"]; got != want {
			t.Errorf("%s -> %s, want %s", state, got, want)
		}
	}
}
