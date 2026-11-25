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

// LoadShedBlock is the report's self.load_shed block: the state after this run and what this run
// read; Since only while shedding.
type LoadShedBlock struct {
	Active bool        `json:"active"`
	Over   []string    `json:"over"`
	Values loadReading `json:"values"`
	Since  string      `json:"since,omitempty"`
}

// block is s's self.load_shed block for the reading r.
func (s loadShed) block(r loadReading) LoadShedBlock {
	b := LoadShedBlock{Active: s.Active, Over: r.over(), Values: r}
	if s.Active && s.Since > 0 {
		b.Since = time.Unix(s.Since, 0).UTC().Format("2006-01-02T15:04:05Z")
	}
	return b
}

// loadReading is what the load gate reads in one run; a value it could not read is nil, counts as
// under its limit and is left out of self.load_shed.values.
type loadReading struct {
	LoadPerCPU   *float64 `json:"load_per_cpu,omitempty"`
	Iowait       *float64 `json:"iowait_percent,omitempty"`
	MemAvailable *float64 `json:"mem_available_percent,omitempty"`
}

// arcAbove is the ARC above its minimum, the part the kernel gives back under pressure; 0 below it.
func arcAbove(size, cMin uint64) uint64 {
	if size <= cMin {
		return 0
	}
	return size - cMin
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

// readLoad reads the load gate's values; a seam for the tests, whose host load must not decide them.
var readLoad = loadReadingOf

// loadReadingOf reads the load gate's values from this run's resources block and the CPU counters of
// the last and this run. The load per CPU is left out in a container, where load_1m is the host's and
// cpu_count may be the container's (as the monitoring service rates agent_resources), and where there
// is no load or CPU count (Windows). The available memory is 100 - memory_percent, which collectMemory
// has already cleared of the ZFS ARC above its minimum (R-1688, R-1760).
func loadReadingOf(resources *Resources, prevCPU, curCPU *cpuSample) loadReading {
	var r loadReading
	if resources == nil {
		return r
	}
	if resources.LoadAverage != nil && resources.SwapAndCPUs != nil && resources.CPUCount != nil &&
		*resources.CPUCount > 0 && !inContainer() {
		v := round2(resources.Load1m / float64(*resources.CPUCount))
		r.LoadPerCPU = &v
	}
	if resources.MemoryUsage != nil {
		v := round1(100 - resources.MemoryPercent)
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
