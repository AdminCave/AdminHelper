// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"bytes"
	"encoding/xml"
	"strings"
	"time"
)

// scmCrashQuery selects the Service Control Manager's events 7031 and 7034 (a service terminated
// unexpectedly, with and without a recovery action) of the last 24 hours; timediff counts
// milliseconds (Windows Event Log XPath subset).
const scmCrashQuery = "*[System[Provider[@Name='Service Control Manager'] and (EventID=7031 or EventID=7034)" +
	" and TimeCreated[timediff(@SystemTime) <= 86400000]]]"

// scmCrashArgs is the one wevtutil call of the agent: the System log, newest first, as XML, at most
// 50 events. A service crashing in a loop can push the others' events out of those 50; they then
// keep their exit and only miss result and since.
var scmCrashArgs = []string{"qe", "System", "/q:" + scmCrashQuery, "/c:50", "/rd:true", "/f:xml"}

// scmEvent is the part of one event's XML the parser reads.
type scmEvent struct {
	EventID     string `xml:"System>EventID"`
	TimeCreated struct {
		SystemTime string `xml:"SystemTime,attr"`
	} `xml:"System>TimeCreated"`
	Data []struct {
		Name  string `xml:"Name,attr"`
		Value string `xml:",chardata"`
	} `xml:"EventData>Data"`
}

// parseScmCrashes reads the output of the scmCrashArgs call, a sequence of <Event> elements without a
// root, into the time of the latest crash per service, keyed by the event's param1 in lower case.
// Which name param1 carries is not documented (scServiceHealth matches it against both); an event of
// another ID, without param1 or with an unreadable time is skipped, and broken XML ends the read with
// the events before it.
func parseScmCrashes(out []byte) map[string]time.Time {
	crashes := map[string]time.Time{}
	d := xml.NewDecoder(bytes.NewReader(out))
	for {
		var ev scmEvent
		if d.Decode(&ev) != nil {
			return crashes
		}
		if ev.EventID != "7031" && ev.EventID != "7034" {
			continue
		}
		at, err := time.Parse(time.RFC3339Nano, ev.TimeCreated.SystemTime)
		if err != nil {
			continue
		}
		for _, data := range ev.Data {
			name := strings.ToLower(strings.TrimSpace(data.Value))
			if data.Name != "param1" || name == "" {
				continue
			}
			if at.After(crashes[name]) {
				crashes[name] = at
			}
		}
	}
}

// addScmCrashes marks the services that carry an exit and have a crash event: result crashed, since
// the time of the latest one. byName resolves a folded service or display name to the service name
// (parseScQuery); a running service with a crash event was restarted and stays as it is.
func addScmCrashes(services []ServiceEntry, byName map[string]string, crashes map[string]time.Time) {
	latest := map[string]time.Time{}
	for name, at := range crashes {
		if unit, ok := byName[name]; ok && at.After(latest[unit]) {
			latest[unit] = at
		}
	}
	for _, svc := range services {
		at, ok := latest[svc["unit"]]
		if !ok || svc["exit"] == "" {
			continue
		}
		svc["result"] = "crashed"
		svc["since"] = at.UTC().Truncate(time.Second).Format(time.RFC3339)
	}
}
