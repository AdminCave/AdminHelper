// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"context"
	"io/fs"
	"os"
	"os/exec"
	"reflect"
	"testing"
	"time"
)

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

func TestAliasAndWatchScQueryError(t *testing.T) {
	// A failed `sc query` must not read as all OK: the block names the failure in a short reason
	// (never the error text, which can carry the sc path), ignores any output and carries no counts,
	// which would claim 0 of 0. The exit-status reason is the same helper the Linux tests cover.
	for name, err := range map[string]error{
		"not found":      &exec.Error{Name: "sc", Err: exec.ErrNotFound},
		"not executable": &fs.PathError{Op: "fork/exec", Path: `C:\Windows\System32\sc.exe`, Err: fs.ErrPermission},
	} {
		t.Run(name, func(t *testing.T) {
			got := scServiceHealth([]byte(scFixture), err)
			if got["error"] != "sc query failed: sc did not start" {
				t.Errorf("error = %q, want %q", got["error"], "sc query failed: sc did not start")
			}
			if c, ok := got["counts"]; ok {
				t.Errorf("counts = %v, want none without sc query", c)
			}
			if all := got["all_services"].([]ServiceEntry); len(all) != 0 {
				t.Errorf("all_services = %v, want none", all)
			}
		})
	}
	// sc answered: inventory and counts, no error.
	got := scServiceHealth([]byte(scFixture), nil)
	if _, ok := got["error"]; ok {
		t.Errorf("error = %q, want none", got["error"])
	}
	if !reflect.DeepEqual(got["counts"], map[string]int{"active": 1, "total": 2}) {
		t.Errorf("counts = %v, want active 1 of 2", got["counts"])
	}
	if all := got["all_services"].([]ServiceEntry); len(all) != 2 {
		t.Errorf("all_services = %v, want both services", all)
	}
}

func TestScServiceHealthTimedOut(t *testing.T) {
	// A hung sc that the timeout ends must say so: exec reports the ended call as an ExitError
	// ("exit status 1" on Windows, "signal: killed" on Linux), which would pass a hang off as a
	// failing sc. A real child process goes through runWithTimeout, the runner the collector uses.
	old := pluginTimeout
	t.Cleanup(func() { pluginTimeout = old })
	pluginTimeout = 100 * time.Millisecond
	t.Setenv(dockerHelperEnv, "hang")
	start := time.Now()
	out, err := runWithTimeout(context.Background(), os.Args[0], "-test.run=^TestHelperDockerProcess$")
	if elapsed := time.Since(start); elapsed > 30*time.Second {
		t.Errorf("runWithTimeout returned after %s, the timeout did not stop the hung call", elapsed)
	}
	got := scServiceHealth(out, err)
	if want := "sc query failed: timed out after 100ms"; got["error"] != want {
		t.Errorf("error = %q, want %q", got["error"], want)
	}
	if c, ok := got["counts"]; ok {
		t.Errorf("counts = %v, want none without sc query", c)
	}
	if all := got["all_services"].([]ServiceEntry); len(all) != 0 {
		t.Errorf("all_services = %v, want none", all)
	}
}
