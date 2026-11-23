// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"context"
	"errors"
	"fmt"
	"reflect"
	"strings"
	"testing"
)

// winEvent renders one event as wevtutil qe /f:RenderedXml prints it (namespace, RenderingInfo).
func winEvent(provider, id, at, level, msg string, data ...string) string {
	var d strings.Builder
	for i := 0; i+1 < len(data); i += 2 {
		fmt.Fprintf(&d, "<Data Name='%s'>%s</Data>", data[i], data[i+1])
	}
	return "<Event xmlns='http://schemas.microsoft.com/win/2004/08/events/event'><System>" +
		"<Provider Name='" + provider + "'/><EventID Qualifiers='16384'>" + id + "</EventID>" +
		"<TimeCreated SystemTime='" + at + "'/><Channel>System</Channel></System>" +
		"<EventData>" + d.String() + "</EventData>" +
		"<RenderingInfo Culture='en-US'><Message>" + msg + "</Message><Level>" + level + "</Level>" +
		"<Provider>" + provider + "</Provider></RenderingInfo></Event>\r\n"
}

const scQueryTwo = `
SERVICE_NAME: Spooler
DISPLAY_NAME: Print Spooler
        STATE              : 1  STOPPED
        WIN32_EXIT_CODE    : 1067  (0x42b)

SERVICE_NAME: MSSQLSERVER
DISPLAY_NAME: SQL Server (MSSQLSERVER)
        STATE              : 1  STOPPED
        WIN32_EXIT_CODE    : 1066  (0x42a)
        SERVICE_EXIT_CODE  : 17058  (0x42a2)
`

func TestParseWinLogEventsNamesTheServiceBySCMParam1OrProvider(t *testing.T) {
	out := winEvent("Service Control Manager", "7031", "2026-11-19T08:00:01.5Z", "Error",
		"The Print Spooler service terminated unexpectedly.", "param1", "Print Spooler", "param2", "1") +
		winEvent("MSSQLSERVER", "17058", "2026-11-19T08:00:02Z", "Error", "initerrlog: Could not open error log file") +
		winEvent("Service Control Manager", "7036", "2026-11-19T08:00:03Z", "Information", "no param1") +
		winEvent("Spooler", "1", "not a time", "Error", "skipped") +
		winEvent("Application Error", "1000", "2026-11-19T08:00:04Z", "Error", "") +
		"<Event><System><Provider"
	got := parseWinLogEvents([]byte(out))
	want := []winLogLine{
		{name: "print spooler", text: "2026-11-19T08:00:01Z Error Service Control Manager 7031: The Print Spooler service terminated unexpectedly."},
		{name: "mssqlserver", text: "2026-11-19T08:00:02Z Error MSSQLSERVER 17058: initerrlog: Could not open error log file"},
		{name: "application error", text: "2026-11-19T08:00:04Z Error Application Error 1000: "},
	}
	if len(got) != len(want) {
		t.Fatalf("parsed %d lines, want %d: %#v", len(got), len(want), got)
	}
	for i := range want {
		if got[i].name != want[i].name || got[i].text != want[i].text {
			t.Errorf("line %d = %q %q, want %q %q", i, got[i].name, got[i].text, want[i].name, want[i].text)
		}
	}
}

func TestParseWinLogEventsReadsPastBytesThatAreNoUTF8(t *testing.T) {
	// 0xE4 is "ä" in Windows-1252: "ausgef\xe4hrt" as a non-Unicode code page would print it.
	out := winEvent("Service Control Manager", "7036", "2026-11-19T08:00:01Z", "Information",
		"Dienst wird ausgef\xe4hrt.", "param1", "Spooler") +
		winEvent("MSSQLSERVER", "17058", "2026-11-19T08:00:02Z", "Error", "sql")
	got := parseWinLogEvents([]byte(out))
	if len(got) != 2 || got[0].text != "2026-11-19T08:00:01Z Information Service Control Manager 7036: Dienst wird ausgef\uFFFDhrt." ||
		got[1].name != "mssqlserver" {
		t.Fatalf("lines = %#v", got)
	}
}

func TestWinServiceLogLinesResolvesOnlySCMNamesThroughSCQuery(t *testing.T) {
	// "Print Spooler" is the display name of Spooler: as an SCM param1 it is Spooler, as the source of
	// an Application event it is a service of its own.
	_, byName := parseScQuery(scQueryTwo)
	lines := parseWinLogEvents([]byte(
		winEvent("Service Control Manager", "7031", "2026-11-19T08:00:01Z", "Error", "scm", "param1", "Print Spooler") +
			winEvent("Print Spooler", "1", "2026-11-19T08:00:02Z", "Error", "app")))
	if got := winServiceLogLines(lines, byName, "Spooler"); len(got) != 1 || !strings.HasSuffix(got[0], ": scm") {
		t.Errorf("Spooler = %q, want the SCM line only", got)
	}
	if got := winServiceLogLines(lines, byName, "Print Spooler"); len(got) != 1 || !strings.HasSuffix(got[0], ": app") {
		t.Errorf("Print Spooler = %q, want the Application line only", got)
	}
}

func TestWinLogTextFallsBackToTheDataWithoutAMessage(t *testing.T) {
	out := winEvent("MyAgent", "3", "2026-11-19T08:00:00Z", "", "", "a", "disk full", "b", " ", "c", "C:")
	got := parseWinLogEvents([]byte(out))
	if len(got) != 1 || got[0].text != "2026-11-19T08:00:00Z - MyAgent 3: disk full C:" {
		t.Fatalf("lines = %#v", got)
	}
}

func TestWinServiceLogLinesKeepsTheServicesLastTenOldestFirstRedacted(t *testing.T) {
	_, byName := parseScQuery(scQueryTwo)
	var out strings.Builder
	// Newest first, as /rd:true prints them: 12 events of Spooler by display name, one by service name.
	for i := 12; i >= 1; i-- {
		out.WriteString(winEvent("Service Control Manager", "7031", fmt.Sprintf("2026-11-19T08:00:%02dZ", i), "Error",
			fmt.Sprintf("crash %d", i), "param1", "Print Spooler"))
	}
	out.WriteString(winEvent("Spooler", "9", "2026-11-19T07:59:00Z", "Warning",
		"connect to postgres://admin:hunter2@db.example.com:5432/app failed"))
	out.WriteString(winEvent("MSSQLSERVER", "17058", "2026-11-19T08:00:30Z", "Error", "sql"))
	lines := parseWinLogEvents([]byte(out.String()))

	got := winServiceLogLines(lines, byName, "Spooler")
	if len(got) != maxLogLines || !strings.HasSuffix(got[0], ": crash 3") || !strings.HasSuffix(got[9], ": crash 12") {
		t.Fatalf("Spooler lines = %q", got)
	}
	if got := winServiceLogLines(lines, byName, "MSSQLSERVER"); !reflect.DeepEqual(got,
		[]string{"2026-11-19T08:00:30Z Error MSSQLSERVER 17058: sql"}) {
		t.Errorf("MSSQLSERVER lines = %q", got)
	}

	// The redaction runs on each line: the oldest line of a service with few events.
	few := parseWinLogEvents([]byte(winEvent("Spooler", "9", "2026-11-19T07:59:00Z", "Warning",
		"connect to postgres://admin:hunter2@db.example.com:5432/app failed")))
	if got := winServiceLogLines(few, byName, "spooler"); len(got) != 1 ||
		got[0] != "2026-11-19T07:59:00Z Warning Spooler 9: connect to postgres://[REDACTED]@db.example.com:5432/app failed" {
		t.Errorf("redacted line = %q", got)
	}
	// Without sc query's names a display name matches nothing, the service name still matches.
	if got := winServiceLogLines(lines, nil, "Spooler"); len(got) != 1 || !strings.Contains(got[0], "Warning Spooler 9") {
		t.Errorf("without byName = %q", got)
	}
}

func TestWindowsLogUnitsAreStoppedAutomaticServicesWithAnExit(t *testing.T) {
	block := &ServiceHealth{AllServices: []ServiceEntry{
		{"unit": "Spooler", "active_state": "inactive", "enabled_state": "enabled", "exit": "1067", "since": "2026-11-19T08:00:00Z"},
		{"unit": "Stopped", "active_state": "inactive", "enabled_state": "enabled"},
		{"unit": "Manual", "active_state": "inactive", "enabled_state": "manual", "exit": "1"},
		{"unit": "Running", "active_state": "active", "enabled_state": "enabled", "exit": "1"},
		{"unit": "MSSQLSERVER", "active_state": "inactive", "enabled_state": "enabled", "exit": "17058"},
	}}
	units, since := windowsLogUnits(block)
	if !reflect.DeepEqual(units, []string{"Spooler", "MSSQLSERVER"}) {
		t.Errorf("units = %v", units)
	}
	if !reflect.DeepEqual(since, map[string]string{"Spooler": "2026-11-19T08:00:00Z", "MSSQLSERVER": ""}) {
		t.Errorf("since = %v", since)
	}
	if units, _ := windowsLogUnits(&ServiceHealth{Error: "sc query failed"}); units == nil || len(units) != 0 {
		t.Errorf("block without services: units = %#v, want empty", units)
	}
}

// stubWinRun answers sc query and the two event queries; a key in fail fails its call ("sc",
// "System", "Application").
func stubWinRun(t *testing.T, events map[string]string, fail map[string]bool) (func(context.Context, string, ...string) ([]byte, error), *[]string) {
	t.Helper()
	var calls []string
	return func(_ context.Context, name string, args ...string) ([]byte, error) {
		if !commandAllowed(name, args) {
			t.Errorf("call not on the allowlist: %s %q", name, args)
		}
		key := name
		if name == "wevtutil" {
			key = args[1]
		}
		calls = append(calls, key)
		if fail[key] {
			return nil, errors.New("exit status 1")
		}
		if name == "sc" {
			return []byte(scQueryTwo), nil
		}
		return []byte(events[key]), nil
	}, &calls
}

func TestWindowsLogReaderQueriesOncePerRun(t *testing.T) {
	events := map[string]string{
		"System": winEvent("Service Control Manager", "7031", "2026-11-19T08:00:01Z", "Error",
			"The Print Spooler service terminated unexpectedly.", "param1", "Print Spooler"),
		"Application": winEvent("MSSQLSERVER", "17058", "2026-11-19T08:00:02Z", "Error", "sql"),
	}
	run, calls := stubWinRun(t, events, nil)
	read := windowsLogReader(run)
	spooler, ok1 := read(context.Background(), "Spooler")
	sql, ok2 := read(context.Background(), "MSSQLSERVER")
	if !ok1 || !ok2 || len(spooler) != 1 || len(sql) != 1 {
		t.Fatalf("Spooler %q %v, MSSQLSERVER %q %v", spooler, ok1, sql, ok2)
	}
	if !reflect.DeepEqual(*calls, []string{"sc", "System", "Application"}) {
		t.Errorf("calls = %v, want sc and the two queries once", *calls)
	}
	if got, ok := read(context.Background(), "Other"); !ok || len(got) != 0 {
		t.Errorf("a service without events = %q %v, want no lines but ok", got, ok)
	}
}

func TestWindowsLogReaderSurvivesFailedCalls(t *testing.T) {
	events := map[string]string{
		"System":      winEvent("Service Control Manager", "7031", "2026-11-19T08:00:01Z", "Error", "x", "param1", "Print Spooler"),
		"Application": winEvent("Spooler", "9", "2026-11-19T08:00:02Z", "Warning", "y"),
	}
	// One query failed: the other's lines.
	run, _ := stubWinRun(t, events, map[string]bool{"System": true})
	if got, ok := windowsLogReader(run)(context.Background(), "Spooler"); !ok || len(got) != 1 || !strings.HasSuffix(got[0], ": y") {
		t.Errorf("System failed: %q %v", got, ok)
	}
	// sc query failed: only the service name matches.
	run, _ = stubWinRun(t, events, map[string]bool{"sc": true})
	if got, ok := windowsLogReader(run)(context.Background(), "Spooler"); !ok || len(got) != 1 || !strings.HasSuffix(got[0], ": y") {
		t.Errorf("sc failed: %q %v", got, ok)
	}
	// Both queries failed: not read, asked again in the next report; the run queries once.
	run, calls := stubWinRun(t, events, map[string]bool{"System": true, "Application": true})
	read := windowsLogReader(run)
	if got, ok := read(context.Background(), "Spooler"); ok || got != nil {
		t.Errorf("both failed: %q %v, want not ok", got, ok)
	}
	read(context.Background(), "MSSQLSERVER")
	if len(*calls) != 3 {
		t.Errorf("calls = %v, want 3", *calls)
	}
}
