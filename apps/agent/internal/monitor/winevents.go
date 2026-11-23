// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"bytes"
	"context"
	"encoding/xml"
	"sort"
	"strings"
	"time"
)

// The two event queries of a Windows service's error lines (R-1391), fixed so no service name enters
// a call: the Service Control Manager's events and the Application log's errors and warnings (Level
// 1-3) of the last 24 hours, newest first, at most 200 each, with the rendered message
// (wevtutil qe /f:RenderedXml). The reader picks each service's events from them.
const (
	scmLogQuery = "*[System[Provider[@Name='Service Control Manager']" +
		" and TimeCreated[timediff(@SystemTime) <= 86400000]]]"
	appLogQuery = "*[System[(Level=1 or Level=2 or Level=3)" +
		" and TimeCreated[timediff(@SystemTime) <= 86400000]]]"
)

var (
	scmLogArgs = []string{"qe", "System", "/q:" + scmLogQuery, "/c:200", "/rd:true", "/f:RenderedXml"}
	appLogArgs = []string{"qe", "Application", "/q:" + appLogQuery, "/c:200", "/rd:true", "/f:RenderedXml"}
)

// winLogEvent is the part of one rendered event the reader uses.
type winLogEvent struct {
	Provider struct {
		Name string `xml:"Name,attr"`
	} `xml:"System>Provider"`
	EventID     string `xml:"System>EventID"`
	TimeCreated struct {
		SystemTime string `xml:"SystemTime,attr"`
	} `xml:"System>TimeCreated"`
	Data []struct {
		Name  string `xml:"Name,attr"`
		Value string `xml:",chardata"`
	} `xml:"EventData>Data"`
	Level   string `xml:"RenderingInfo>Level"`
	Message string `xml:"RenderingInfo>Message"`
}

// winLogLine is one event as a line, with the time it is sorted by and the folded name of the service
// it belongs to: an SCM event's param1 (service or display name, not documented which; scm set), any
// other event's provider, which is the service name.
type winLogLine struct {
	at   time.Time
	name string
	scm  bool
	text string
}

// parseWinLogEvents reads the output of one query, a sequence of <Event> elements without a root, into
// lines. An SCM event without param1 or an event with an unreadable time is skipped, and broken XML
// ends the read with the events before it. Bytes that are no UTF-8 become U+FFFD first: the encoding
// wevtutil writes to a pipe is not documented, and the decoder would stop at the first such byte.
func parseWinLogEvents(out []byte) []winLogLine {
	var lines []winLogLine
	d := xml.NewDecoder(bytes.NewReader(bytes.ToValidUTF8(out, []byte("\uFFFD"))))
	for {
		var ev winLogEvent
		if d.Decode(&ev) != nil {
			return lines
		}
		at, err := time.Parse(time.RFC3339Nano, ev.TimeCreated.SystemTime)
		if err != nil {
			continue
		}
		name := ev.Provider.Name
		scm := name == "Service Control Manager"
		if scm {
			name = ""
			for _, data := range ev.Data {
				if data.Name == "param1" {
					name = data.Value
					break
				}
			}
		}
		name = strings.ToLower(strings.TrimSpace(name))
		if name == "" {
			continue
		}
		lines = append(lines, winLogLine{at: at, name: name, scm: scm, text: winLogText(ev, at)})
	}
}

// winLogText is an event as one line: time, level, source, event ID and the rendered message; without
// a message (no rendering for the event's provider) the data values stand in.
func winLogText(ev winLogEvent, at time.Time) string {
	msg := strings.TrimSpace(ev.Message)
	if msg == "" {
		values := make([]string, 0, len(ev.Data))
		for _, data := range ev.Data {
			if v := strings.TrimSpace(data.Value); v != "" {
				values = append(values, v)
			}
		}
		msg = strings.Join(values, " ")
	}
	level := strings.TrimSpace(ev.Level)
	if level == "" {
		level = "-"
	}
	return at.UTC().Truncate(time.Second).Format(time.RFC3339) + " " + level + " " + ev.Provider.Name + " " +
		strings.TrimSpace(ev.EventID) + ": " + msg
}

// winServiceLogLines are the last maxLogLines lines of unit among lines, oldest first, each through
// cleanLogLine. byName resolves an SCM line's name to its service (a folded service or display name
// → service name, parseScQuery); a name it does not know, and any other line's name, counts as the
// service name itself.
func winServiceLogLines(lines []winLogLine, byName map[string]string, unit string) []string {
	var own []winLogLine
	for _, l := range lines {
		owner, known := byName[l.name]
		if !known || !l.scm {
			owner = l.name
		}
		if strings.EqualFold(owner, unit) {
			own = append(own, l)
		}
	}
	sort.SliceStable(own, func(i, j int) bool { return own[i].at.Before(own[j].at) })
	if len(own) > maxLogLines {
		own = own[len(own)-maxLogLines:]
	}
	out := make([]string, len(own))
	for i, l := range own {
		out[i] = cleanLogLine(l.text)
	}
	return out
}

// windowsLogUnits are the services of the Windows block whose error lines are sent: the stopped
// "enabled" ones that carry an exit (an automatic service that ended with an error code), in the
// block's order, and the since of each from the SCM crash events ("" without one). The block lists
// them as log_units, since a Windows block never has failed ones.
func windowsLogUnits(systemd *ServiceHealth) ([]string, map[string]string) {
	units := []string{}
	since := map[string]string{}
	for _, svc := range systemd.AllServices {
		if svc["active_state"] != "inactive" || svc["enabled_state"] != "enabled" || svc["exit"] == "" {
			continue
		}
		units = append(units, svc["unit"])
		since[svc["unit"]] = svc["since"]
	}
	return units, since
}

// windowsLogReader is one run's reader of Windows error lines. The first read runs sc query (for the
// display names) and the two event queries through run; every read of the run picks from them. A run
// whose event queries both fail reads nothing, so its services are asked again in the next report;
// one failed query leaves the other's lines, and a failed sc query matches service names only.
func windowsLogReader(run func(ctx context.Context, name string, args ...string) ([]byte, error)) func(context.Context, string) ([]string, bool) {
	var (
		loaded bool
		ok     bool
		byName map[string]string
		lines  []winLogLine
	)
	return func(ctx context.Context, unit string) ([]string, bool) {
		if !loaded {
			loaded = true
			if out, err := run(ctx, "sc", "query", "state=", "all"); err == nil {
				_, byName = parseScQuery(string(out))
			} else {
				logger.Warnf("service logs: sc query failed, matching service names only: %s",
					commandFailure("sc", pluginTimeout, err))
			}
			for _, args := range [][]string{scmLogArgs, appLogArgs} {
				out, err := run(ctx, "wevtutil", args...)
				if err != nil {
					logger.Warnf("service logs: wevtutil qe %s failed: %s", args[1],
						commandFailure("wevtutil", pluginTimeout, err))
					continue
				}
				ok = true
				lines = append(lines, parseWinLogEvents(out)...)
			}
		}
		if !ok {
			return nil, false
		}
		return winServiceLogLines(lines, byName, unit), true
	}
}
