// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package monitor

import (
	"bytes"
	"context"
	"encoding/xml"
	"io"
	"strings"
	"testing"
	"time"
)

// TestScmCrashQueryRuns runs the agent's wevtutil call on this host: the allowlist takes it, wevtutil
// takes the XPath (an invalid query exits non-zero) and prints the events as XML the parser reads. A
// host without a crash in 24 hours prints nothing.
func TestScmCrashQueryRuns(t *testing.T) {
	out, err := runWithTimeout(context.Background(), "wevtutil", scmCrashArgs...)
	if err != nil {
		t.Fatalf("wevtutil %q: %v", scmCrashArgs, err)
	}
	trimmed := bytes.TrimSpace(out)
	if len(trimmed) == 0 {
		return
	}
	if !bytes.HasPrefix(trimmed, []byte("<Event")) {
		t.Fatalf("output does not start with <Event: %q", trimmed[:min(len(trimmed), 80)])
	}
	if crashes := parseScmCrashes(out); len(crashes) == 0 {
		t.Errorf("%d bytes of crash events, none parsed", len(out))
	}
}

// TestScmEventsNameServicesByDisplayName checks on this host what parseScQuery, parseScmCrashes and
// addScmCrashes assume: sc query lists display names, and the Service Control Manager's events carry
// EventID, TimeCreated/@SystemTime and a param1 that names the service by its display name. Crashes
// (7031/7034) are rare on a fresh host, so it reads the provider's state changes (7036), through
// execTimed: a call of this test, not of the agent.
func TestScmEventsNameServicesByDisplayName(t *testing.T) {
	ctx := context.Background()
	scOut, err := runWithTimeout(ctx, "sc", "query", "state=", "all")
	if err != nil {
		t.Fatalf("sc query: %v", err)
	}
	services, byName := parseScQuery(string(scOut))
	if len(services) == 0 || len(byName) <= len(services) {
		t.Fatalf("sc query listed %d services and %d names: no display names", len(services), len(byName))
	}
	out, err := execTimed(ctx, pluginTimeout, nil, "wevtutil", "qe", "System",
		"/q:*[System[Provider[@Name='Service Control Manager'] and EventID=7036]]", "/c:20", "/rd:true", "/f:xml")
	if err != nil {
		t.Fatalf("wevtutil: %v", err)
	}
	events, byDisplay := 0, 0
	d := xml.NewDecoder(bytes.NewReader(out))
	for {
		var ev scmEvent
		if err := d.Decode(&ev); err == io.EOF {
			break
		} else if err != nil {
			t.Fatalf("event %d: %v", events+1, err)
		}
		events++
		if ev.EventID != "7036" {
			t.Errorf("EventID = %q, want 7036", ev.EventID)
		}
		if _, err := time.Parse(time.RFC3339Nano, ev.TimeCreated.SystemTime); err != nil {
			t.Errorf("SystemTime %q: %v", ev.TimeCreated.SystemTime, err)
		}
		for _, data := range ev.Data {
			if unit, ok := byName[strings.ToLower(data.Value)]; ok && data.Name == "param1" &&
				!strings.EqualFold(unit, data.Value) {
				byDisplay++
			}
		}
	}
	if events == 0 {
		t.Fatal("no event 7036 of the Service Control Manager in the System log")
	}
	if byDisplay == 0 {
		t.Errorf("none of %d events 7036 names a service by its display name in param1", events)
	}
}
