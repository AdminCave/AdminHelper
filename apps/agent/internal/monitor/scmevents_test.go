// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"reflect"
	"testing"
	"time"
)

// scmEventXML is one event of the Service Control Manager as `wevtutil qe … /f:xml` prints it: no root
// element around the events, single-quoted attributes, the namespace on Event. Which name param1
// carries is checked on Windows (scmevents_windows_test.go).
func scmEventXML(id, systemTime, param1 string) string {
	return "<Event xmlns='http://schemas.microsoft.com/win/2004/08/events/event'><System>" +
		"<Provider Name='Service Control Manager' Guid='{555908d1-a6d7-4695-8e1e-26931d2012f4}'" +
		" EventSourceName='Service Control Manager'/><EventID Qualifiers='49152'>" + id + "</EventID>" +
		"<Version>0</Version><Level>2</Level><Task>0</Task><Opcode>0</Opcode>" +
		"<Keywords>0x8080000000000000</Keywords><TimeCreated SystemTime='" + systemTime + "'/>" +
		"<EventRecordID>4711</EventRecordID><Correlation/><Execution ProcessID='668' ThreadID='4120'/>" +
		"<Channel>System</Channel><Computer>WIN-TEST</Computer><Security/></System><EventData>" +
		"<Data Name='param1'>" + param1 + "</Data><Data Name='param2'>1</Data>" +
		"<Data Name='param3'>60000</Data><Data Name='param4'>1</Data>" +
		"<Data Name='param5'>Restart the service</Data></EventData></Event>"
}

func TestParseScmCrashes(t *testing.T) {
	at := func(s string) time.Time {
		v, err := time.Parse(time.RFC3339Nano, s)
		if err != nil {
			t.Fatal(err)
		}
		return v
	}
	out := scmEventXML("7034", "2026-11-12T08:00:00.0000000Z", "Print Spooler") + "\r\n" +
		// The later crash comes second: the latest one counts, whatever the order.
		scmEventXML("7031", "2026-11-12T09:30:00.5000000Z", "PRINT SPOOLER") +
		// Another event of the provider, a crash without a readable time and one without param1.
		scmEventXML("7036", "2026-11-12T10:00:00.0000000Z", "Windows Update") +
		scmEventXML("7034", "yesterday", "DNS Client") +
		"<Event><System><EventID>7031</EventID><TimeCreated SystemTime='2026-11-12T10:00:00Z'/></System>" +
		"<EventData><Data Name='param2'>Lonely</Data></EventData></Event>" +
		scmEventXML("7031", "2026-11-12T07:00:00Z", " My Backup Agent ") +
		// Broken XML ends the read; the events before it stay.
		"<Event><System><EventID>7031</Event>" +
		scmEventXML("7031", "2026-11-12T11:00:00Z", "Lost Service")
	want := map[string]time.Time{
		"print spooler":   at("2026-11-12T09:30:00.5Z"),
		"my backup agent": at("2026-11-12T07:00:00Z"),
	}
	if got := parseScmCrashes([]byte(out)); !reflect.DeepEqual(got, want) {
		t.Errorf("parseScmCrashes = %v\nwant %v", got, want)
	}
	for _, empty := range []string{"", "\r\n", "not xml"} {
		if got := parseScmCrashes([]byte(empty)); len(got) != 0 {
			t.Errorf("parseScmCrashes(%q) = %v, want none", empty, got)
		}
	}
}

func TestAddScmCrashes(t *testing.T) {
	// One service named by both of its names takes the later crash; a name sc query does not list
	// changes nothing.
	services := []ServiceEntry{
		{"unit": "Spooler", "active_state": "inactive", "enabled_state": "unknown", "exit": "win32=1067"},
		{"unit": "Gone", "active_state": "inactive", "enabled_state": "unknown", "exit": "win32=1067"},
	}
	byName := map[string]string{"spooler": "Spooler", "print spooler": "Spooler", "gone": "Gone"}
	crashes := map[string]time.Time{
		"spooler":       time.Date(2026, 11, 12, 9, 0, 0, 0, time.UTC),
		"print spooler": time.Date(2026, 11, 12, 11, 0, 0, 0, time.FixedZone("CET", 3600)),
		"unknown":       time.Date(2026, 11, 12, 12, 0, 0, 0, time.UTC),
	}
	addScmCrashes(services, byName, crashes)
	want := []ServiceEntry{
		{"unit": "Spooler", "active_state": "inactive", "enabled_state": "unknown", "exit": "win32=1067",
			"result": "crashed", "since": "2026-11-12T10:00:00Z"},
		{"unit": "Gone", "active_state": "inactive", "enabled_state": "unknown", "exit": "win32=1067"},
	}
	if !reflect.DeepEqual(services, want) {
		t.Errorf("services = %v\nwant %v", services, want)
	}
}
