// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"math"
	"time"
)

// The load gate: a host under load sheds the optional collectors, the probe phase and a discovery, so
// the monitoring takes nothing from the services it watches when they need it most. It sheds from the
// second run in a row with a reading over a limit and measures everything again in the third run in a
// row without one.
const (
	shedLoadPerCPU      = 2.0
	shedIowaitPercent   = 25.0
	shedMemAvailPercent = 10.0
	shedEnter           = 2
	shedLeave           = 3
)

// shedReason is the reason of a collector the load gate held back, in self.collectors.
const shedReason = "load"

// loadShed is the load gate's state, kept in the report state.
type loadShed struct {
	Active bool `json:"active,omitempty"`
	// Since is when the shedding began (Unix seconds).
	Since int64 `json:"since,omitempty"`
	// Hits and Clean count the runs in a row over and under the limits.
	Hits  int `json:"hits,omitempty"`
	Clean int `json:"clean,omitempty"`
}

// after is s once a run read the load as over a limit or not, at now.
func (s loadShed) after(over bool, now time.Time) loadShed {
	if !s.Active {
		if !over {
			return loadShed{}
		}
		s.Hits++
		if s.Hits >= shedEnter {
			return loadShed{Active: true, Since: now.Unix()}
		}
		return s
	}
	if over {
		s.Clean = 0
		return s
	}
	s.Clean++
	if s.Clean >= shedLeave {
		return loadShed{}
	}
	return s
}

// block is the report's self.load_shed block: the state after this run and what this run read.
func (s loadShed) block(r loadReading) map[string]any {
	b := map[string]any{"active": s.Active, "over": r.over(), "values": r.values()}
	if s.Active && s.Since > 0 {
		b["since"] = time.Unix(s.Since, 0).UTC().Format("2006-01-02T15:04:05Z")
	}
	return b
}

// loadReading is what the load gate reads in one run; a value it could not read is nil and counts as
// under its limit.
type loadReading struct {
	LoadPerCPU   *float64
	Iowait       *float64
	MemAvailable *float64
}

// over names the readings over their limit, in a fixed order; empty, never nil, for none.
func (r loadReading) over() []string {
	over := []string{}
	if r.LoadPerCPU != nil && *r.LoadPerCPU >= shedLoadPerCPU {
		over = append(over, "load")
	}
	if r.Iowait != nil && *r.Iowait >= shedIowaitPercent {
		over = append(over, "iowait")
	}
	if r.MemAvailable != nil && *r.MemAvailable < shedMemAvailPercent {
		over = append(over, "memory")
	}
	return over
}

// values are the readings that could be read.
func (r loadReading) values() map[string]float64 {
	v := map[string]float64{}
	if r.LoadPerCPU != nil {
		v["load_per_cpu"] = *r.LoadPerCPU
	}
	if r.Iowait != nil {
		v["iowait_percent"] = *r.Iowait
	}
	if r.MemAvailable != nil {
		v["mem_available_percent"] = *r.MemAvailable
	}
	return v
}

// readLoad reads the load gate's values; a seam for the tests, whose host load must not decide them.
var readLoad = loadReadingOf

// loadReadingOf reads the load gate's values from this run's resources block and the CPU counters of
// the last and this run. The load per CPU is left out in a container, where load_1m is the host's and
// cpu_count may be the container's (as the monitoring service rates agent_resources), and where there
// is no load or CPU count (Windows). The available memory is 100 - memory_percent: gopsutil counts
// the available memory as unused on Linux, FreeBSD and Windows.
func loadReadingOf(resources map[string]any, prevCPU, curCPU *cpuSample) loadReading {
	var r loadReading
	if l, ok := resources["load_1m"].(float64); ok {
		if n, ok := resources["cpu_count"].(int); ok && n > 0 && !inContainer() {
			v := round2(l / float64(n))
			r.LoadPerCPU = &v
		}
	}
	if used, ok := resources["memory_percent"].(float64); ok {
		v := round1(100 - used)
		r.MemAvailable = &v
	}
	r.Iowait = iowaitPercentSince(prevCPU, curCPU)
	return r
}

// iowaitPercentSince is the share of the CPU time spent waiting for I/O between the two samples, in
// the window cpuPercentSince measures in, limited to 0-100 (gopsutil: the counter can decrease,
// cpu/ex_linux.go). nil when either sample has no I/O wait counter (a counter of 0: not Linux, a
// state saved before the counter was kept, or a host that never waited) or the window is not open.
func iowaitPercentSince(prev, cur *cpuSample) *float64 {
	if prev == nil || cur == nil || prev.Iowait == 0 || cur.Iowait == 0 || !cpuWindowOpen(prev, *cur) {
		return nil
	}
	v := round1(math.Min(100, math.Max(0, (cur.Iowait-prev.Iowait)/(cur.Total-prev.Total)*100)))
	return &v
}
