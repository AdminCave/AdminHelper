// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"context"
	"errors"
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
	got, _ := parseScQuery(scFixture)
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
	if got, _ := parseScQuery(""); len(got) != 0 {
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
			got := scServiceHealth([]byte(scFixture), err, nil)
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
	got := scServiceHealth([]byte(scFixture), nil, nil)
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
	// failing sc. A real child process goes through execTimed under pluginTimeout, as runWithTimeout runs sc.
	old := pluginTimeout
	t.Cleanup(func() { pluginTimeout = old })
	pluginTimeout = 100 * time.Millisecond
	t.Setenv(dockerHelperEnv, "hang")
	start := time.Now()
	out, err := execTimed(context.Background(), pluginTimeout, nil, os.Args[0], "-test.run=^TestHelperDockerProcess$")
	if elapsed := time.Since(start); elapsed > 30*time.Second {
		t.Errorf("execTimed returned after %s, the timeout did not stop the hung call", elapsed)
	}
	got := scServiceHealth(out, err, nil)
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

// scExitFixture is `sc query state= all` as Windows prints it, with display names and exit codes: a
// crashed service (1067), one never started since boot (1077), one with its own code (1066 and
// SERVICE_EXIT_CODE), one stopped cleanly (0), one that failed to start (1053) and two running.
const scExitFixture = "SERVICE_NAME: Dnscache\r\n" +
	"DISPLAY_NAME: DNS Client\r\n" +
	"        TYPE               : 20  WIN32_SHARE_PROCESS\r\n" +
	"        STATE              : 4  RUNNING\r\n" +
	"                                (NOT_STOPPABLE, NOT_PAUSABLE, IGNORES_SHUTDOWN)\r\n" +
	"        WIN32_EXIT_CODE    : 0  (0x0)\r\n" +
	"        SERVICE_EXIT_CODE  : 0  (0x0)\r\n" +
	"        CHECKPOINT         : 0x0\r\n" +
	"        WAIT_HINT          : 0x0\r\n" +
	"\r\n" +
	"SERVICE_NAME: Spooler\r\n" +
	"DISPLAY_NAME: Print Spooler\r\n" +
	"        TYPE               : 110  WIN32_OWN_PROCESS  (interactive)\r\n" +
	"        STATE              : 1  STOPPED\r\n" +
	"        WIN32_EXIT_CODE    : 1067  (0x42b)\r\n" +
	"        SERVICE_EXIT_CODE  : 0  (0x0)\r\n" +
	"\r\n" +
	"SERVICE_NAME: AppMgmt\r\n" +
	"DISPLAY_NAME: Application Management\r\n" +
	"        STATE              : 1  STOPPED\r\n" +
	"        WIN32_EXIT_CODE    : 1077  (0x435)\r\n" +
	"        SERVICE_EXIT_CODE  : 0  (0x0)\r\n" +
	"\r\n" +
	"SERVICE_NAME: MyAgent\r\n" +
	"DISPLAY_NAME: My Backup Agent\r\n" +
	"        STATE              : 1  STOPPED\r\n" +
	"        WIN32_EXIT_CODE    : 1066  (0x42a)\r\n" +
	"        SERVICE_EXIT_CODE  : 3  (0x3)\r\n" +
	"\r\n" +
	"SERVICE_NAME: W32Time\r\n" +
	"DISPLAY_NAME: Windows Time\r\n" +
	"        STATE              : 1  STOPPED\r\n" +
	"        WIN32_EXIT_CODE    : 0  (0x0)\r\n" +
	"        SERVICE_EXIT_CODE  : 0  (0x0)\r\n" +
	"\r\n" +
	"SERVICE_NAME: BadSvc\r\n" +
	"DISPLAY_NAME: Bad Service\r\n" +
	"        STATE              : 1  STOPPED\r\n" +
	"        WIN32_EXIT_CODE    : 1053  (0x41d)\r\n" +
	"        SERVICE_EXIT_CODE  : 0  (0x0)\r\n" +
	"\r\n" +
	"SERVICE_NAME: wuauserv\r\n" +
	"DISPLAY_NAME: Windows Update\r\n" +
	"        STATE              : 4  RUNNING\r\n" +
	"        WIN32_EXIT_CODE    : 0  (0x0)\r\n" +
	"        SERVICE_EXIT_CODE  : 0  (0x0)\r\n"

func TestScServiceHealthExitAndCrashes(t *testing.T) {
	// The crash events name Spooler by its display name (twice, the older one second), MyAgent by its
	// service name in another case and wuauserv, which runs again; BadSvc has an exit but no event.
	events := scmEventXML("7031", "2026-11-12T10:00:00.1234567Z", "Print Spooler") +
		scmEventXML("7034", "2026-11-12T09:00:00.0000000Z", "Print Spooler") + "\r\n" +
		scmEventXML("7034", "2026-11-12T08:30:15.9876543Z", "myagent") +
		scmEventXML("7031", "2026-11-12T07:00:00.0000000Z", "Windows Update")
	calls := 0
	got := scServiceHealth([]byte(scExitFixture), nil, func() ([]byte, error) {
		calls++
		return []byte(events), nil
	})
	want := []ServiceEntry{
		{"unit": "Dnscache", "active_state": "active", "enabled_state": "unknown"},
		{"unit": "Spooler", "active_state": "inactive", "enabled_state": "unknown",
			"exit": "win32=1067", "result": "crashed", "since": "2026-11-12T10:00:00Z"},
		{"unit": "AppMgmt", "active_state": "inactive", "enabled_state": "unknown"},
		{"unit": "MyAgent", "active_state": "inactive", "enabled_state": "unknown",
			"exit": "service=3", "result": "crashed", "since": "2026-11-12T08:30:15Z"},
		{"unit": "W32Time", "active_state": "inactive", "enabled_state": "unknown"},
		{"unit": "BadSvc", "active_state": "inactive", "enabled_state": "unknown", "exit": "win32=1053"},
		{"unit": "wuauserv", "active_state": "active", "enabled_state": "unknown"},
	}
	if !reflect.DeepEqual(got["all_services"], want) {
		t.Errorf("all_services = %v\nwant %v", got["all_services"], want)
	}
	if calls != 1 {
		t.Errorf("crash events read %d times, want once", calls)
	}
	if !reflect.DeepEqual(got["counts"], map[string]int{"active": 2, "total": 7}) {
		t.Errorf("counts = %v, want active 2 of 7", got["counts"])
	}
	// No new failed: a crashed Windows service stays inactive, as before.
	if f := got["failed"].([]string); len(f) != 0 {
		t.Errorf("failed = %v, want none", f)
	}
}

func TestScServiceHealthReadsEventsOnlyForAnExit(t *testing.T) {
	// Nothing stopped with an error (only 0 and 1077, and a running service): wevtutil never runs.
	clean := "SERVICE_NAME: AppMgmt\r\n        STATE              : 1  STOPPED\r\n" +
		"        WIN32_EXIT_CODE    : 1077  (0x435)\r\n" +
		"SERVICE_NAME: W32Time\r\n        STATE              : 1  STOPPED\r\n" +
		"        WIN32_EXIT_CODE    : 0  (0x0)\r\n" +
		"SERVICE_NAME: Busy\r\n        STATE              : 4  RUNNING\r\n" +
		"        WIN32_EXIT_CODE    : 1067  (0x42b)\r\n"
	for name, out := range map[string]string{"clean": clean, "without codes": scFixture} {
		got := scServiceHealth([]byte(out), nil, func() ([]byte, error) {
			t.Errorf("%s: crash events read without a stopped service with an exit", name)
			return nil, nil
		})
		for _, svc := range got["all_services"].([]ServiceEntry) {
			if svc["exit"] != "" || svc["result"] != "" {
				t.Errorf("%s: %v carries exit or result", name, svc)
			}
		}
	}
}

func TestScServiceHealthCrashEventsFail(t *testing.T) {
	// A failed wevtutil leaves the exits from sc query and adds neither result, since nor an error.
	got := scServiceHealth([]byte(scExitFixture), nil, func() ([]byte, error) {
		return []byte(scmEventXML("7031", "2026-11-12T10:00:00Z", "Print Spooler")), errors.New("exit status 5")
	})
	if _, ok := got["error"]; ok {
		t.Errorf("error = %q, want none", got["error"])
	}
	exits := 0
	for _, svc := range got["all_services"].([]ServiceEntry) {
		if svc["result"] != "" || svc["since"] != "" {
			t.Errorf("%v carries result or since without events", svc)
		}
		if svc["exit"] != "" {
			exits++
		}
	}
	if exits != 3 {
		t.Errorf("%d services with exit, want 3 (Spooler, MyAgent, BadSvc)", exits)
	}
}

func TestParseScQueryNames(t *testing.T) {
	_, byName := parseScQuery(scExitFixture)
	for name, want := range map[string]string{
		"spooler": "Spooler", "print spooler": "Spooler", "myagent": "MyAgent", "my backup agent": "MyAgent",
	} {
		if byName[name] != want {
			t.Errorf("byName[%q] = %q, want %q", name, byName[name], want)
		}
	}
	if len(byName) != 14 {
		t.Errorf("byName has %d names, want 14 (7 services, 7 display names)", len(byName))
	}
}

func TestWindowsExit(t *testing.T) {
	for _, c := range []struct{ win32, specific, want string }{
		{"0", "0", ""},
		{"", "", ""},
		{"1077", "0", ""},
		{"1067", "0", "win32=1067"},
		{"1053", "", "win32=1053"},
		{"1066", "3", "service=3"},
		{"1066", "0", "win32=1066"},
		{"1066", "", "win32=1066"},
	} {
		if got := windowsExit(c.win32, c.specific); got != c.want {
			t.Errorf("windowsExit(%q, %q) = %q, want %q", c.win32, c.specific, got, c.want)
		}
	}
}

func TestScCode(t *testing.T) {
	for line, want := range map[string]string{
		"WIN32_EXIT_CODE    : 1067  (0x42b)": "1067",
		"SERVICE_EXIT_CODE  : 0  (0x0)":      "0",
		"WIN32_EXIT_CODE    :":               "",
		"WIN32_EXIT_CODE    : 0x42b":         "",
		"WIN32_EXIT_CODE":                    "",
	} {
		if got := scCode(line); got != want {
			t.Errorf("scCode(%q) = %q, want %q", line, got, want)
		}
	}
}
