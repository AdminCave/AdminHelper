// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"encoding/csv"
	"errors"
	"fmt"
	"math"
	"os/exec"
	"strconv"
	"strings"
)

// bindStatus reads whether named answers its control channel, how many zones it serves and how many
// recursive clients it has against its limit. A named that does not answer is a value (running
// false), not an error. It asks `rndc status` alone, never `rndc stats`, which writes the statistics
// file, and reports no zone name.
//
// bin/named/server.c, named_server_status: "number of zones: %u (%u automatic)", "recursive clients:
// %u/%u/%u" (used, soft, max) and "server is up and running".
func bindStatus(ctx context.Context, _ Target) (map[string]any, error) {
	out, err := runTool(ctx, toolTimeout, "rndc", "status")
	switch {
	case errors.Is(err, exec.ErrNotFound):
		return nil, fmt.Errorf("%w: rndc is not installed", ErrUnsupported)
	case ctx.Err() != nil:
		return nil, ctx.Err()
	case err != nil:
		return map[string]any{"running": false}, nil
	}
	values := map[string]any{"running": false}
	for line := range strings.Lines(string(out)) {
		line = strings.TrimSpace(line)
		switch {
		case line == "server is up and running":
			values["running"] = true
		case strings.HasPrefix(line, "number of zones: "):
			n, _, _ := strings.Cut(strings.TrimPrefix(line, "number of zones: "), " ")
			zones, err := strconv.Atoi(n)
			if err != nil || zones < 0 {
				return nil, errors.New("rndc: a zone count of another form")
			}
			values["zones"] = zones
		case strings.HasPrefix(line, "recursive clients: "):
			parts := strings.Split(strings.TrimPrefix(line, "recursive clients: "), "/")
			if len(parts) != 3 {
				return nil, errors.New("rndc: a client count of another form")
			}
			used, err1 := strconv.Atoi(parts[0])
			limit, err2 := strconv.Atoi(parts[2])
			if err1 != nil || err2 != nil || used < 0 || limit < 0 {
				return nil, errors.New("rndc: a client count of another form")
			}
			values["recursive_clients"], values["recursive_limit"] = used, limit
		}
	}
	if _, ok := values["zones"]; !ok {
		return nil, errors.New("rndc: a status of another form")
	}
	return values, nil
}

// unboundStats reads Unbound's counters since its start: queries, requests dropped because the
// request list was full, and, with extended statistics on (statistics-extended), the share of
// answers that were SERVFAIL. It asks `unbound-control stats_noreset` alone, never `stats`, which
// resets the counters the operator's own statistics rely on.
//
// daemon/remote.c prints one "name=value" per line; print_stats gives "total.num.queries" and
// "total.requestlist.exceeded", print_ext (only with stat-extended) "num.answer.rcode.SERVFAIL".
func unboundStats(ctx context.Context, _ Target) (map[string]any, error) {
	out, err := runAppTool(ctx, "unbound-control", "stats_noreset")
	if err != nil {
		return nil, err
	}
	counters := map[string]float64{}
	for line := range strings.Lines(string(out)) {
		name, value, ok := strings.Cut(strings.TrimSpace(line), "=")
		if !ok {
			continue
		}
		if name == "total.num.queries" || name == "total.requestlist.exceeded" || name == "num.answer.rcode.SERVFAIL" {
			n, err := strconv.ParseFloat(value, 64)
			if err != nil || n < 0 {
				return nil, errors.New("unbound-control: a counter of another form")
			}
			counters[name] = n
		}
	}
	queries, ok1 := counters["total.num.queries"]
	exceeded, ok2 := counters["total.requestlist.exceeded"]
	if !ok1 || !ok2 {
		return nil, errors.New("unbound-control: statistics of another form")
	}
	values := map[string]any{"queries": int64(queries), "requestlist_exceeded": int64(exceeded)}
	if servfail, ok := counters["num.answer.rcode.SERVFAIL"]; ok && queries > 0 {
		values["servfail_pct"] = math.Round(servfail/queries*1000) / 10
	}
	return values, nil
}

// chronyTracking reads whether chronyd is synchronised, its stratum and how far the system clock is
// off NTP time. It asks `chronyc -c tracking` alone, never makestep or burst, which change the clock
// or its polling.
//
// chronyc's client.c, process_cmd_tracking: in CSV mode one line of reference ID, name, stratum,
// reference time, system time offset (seconds, positive without "+"), last offset, RMS offset,
// frequency, residual frequency, skew, root delay, root dispersion, update interval, leap status as
// a word ("Normal", "Insert second", "Delete second", "Not synchronised").
func chronyTracking(ctx context.Context, _ Target) (map[string]any, error) {
	out, err := runAppTool(ctx, "chronyc", "-c", "tracking")
	if err != nil {
		return nil, err
	}
	fields, err := csv.NewReader(strings.NewReader(string(out))).Read()
	if err != nil || len(fields) != 14 {
		return nil, errors.New("chronyc: a tracking report of another form")
	}
	stratum, err1 := strconv.Atoi(fields[2])
	offset, err2 := strconv.ParseFloat(fields[4], 64)
	if err1 != nil || err2 != nil || stratum < 0 {
		return nil, errors.New("chronyc: a tracking report of another form")
	}
	leap := fields[13]
	return map[string]any{
		"synced":        leap != "Not synchronised" && leap != "Invalid",
		"stratum":       stratum,
		"offset_abs_ms": math.Round(math.Abs(offset)*1e6) / 1e3,
	}, nil
}

// ntpsecStatus reads whether ntpd is synchronised, its stratum and its combined offset. It asks
// `ntpq -c "rv 0 leap,stratum,offset"` for these three system variables alone.
//
// NTPsec's ntpq.html: readvar's names are comma-separated, time values in milliseconds; leap is the
// leap indicator 0-3, 3 (alarm) while unsynchronised. pylib/util.py's cook prints "name=value"
// joined by ", " and leap as two bits ("00" … "11"); a plain digit is taken as well.
func ntpsecStatus(ctx context.Context, _ Target) (map[string]any, error) {
	out, err := runAppTool(ctx, "ntpq", "-c", "rv 0 leap,stratum,offset")
	if err != nil {
		return nil, err
	}
	vars := map[string]string{}
	for item := range strings.SplitSeq(strings.ReplaceAll(string(out), "\n", ","), ",") {
		name, value, ok := strings.Cut(strings.TrimSpace(item), "=")
		if ok {
			vars[name] = strings.Trim(value, `"`)
		}
	}
	leap, ok := map[string]int{"00": 0, "01": 1, "10": 2, "11": 3, "0": 0, "1": 1, "2": 2, "3": 3}[vars["leap"]]
	stratum, err1 := strconv.Atoi(vars["stratum"])
	offset, err2 := strconv.ParseFloat(vars["offset"], 64)
	if !ok || err1 != nil || err2 != nil || stratum < 0 {
		return nil, errors.New("ntpq: system variables of another form")
	}
	return map[string]any{
		"synced":        leap != 3 && stratum < 16,
		"stratum":       stratum,
		"offset_abs_ms": math.Round(math.Abs(offset)*1e3) / 1e3,
	}, nil
}
