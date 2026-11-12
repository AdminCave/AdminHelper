// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"context"
	"time"

	"adminhelper-agent/internal/execx"
)

// The self-throttle of the optional collectors: two runs in a row with a time-limit hit double a
// collector's factor, three without halve it; with factor n it runs every n-th run.
const (
	throttleHits      = 2
	throttleClean     = 3
	maxThrottleFactor = 8
)

// probesCollector is the name of the probe phase among the collectors.
const probesCollector = "probes"

// collectorStat is one collector's entry in the report's self.collectors block: what it cost this run.
type collectorStat struct {
	DurationMS int64 `json:"duration_ms"`
	// CPUMS is the CPU time of the agent and of the tools it ran and waited for (Windows: the agent's
	// own only).
	CPUMS int64 `json:"cpu_ms"`
	// Timeouts is how often the collector hit a time limit: its tools that their own timeout ended,
	// for the probe phase the due probes the run's time did not leave room for.
	Timeouts int `json:"timeouts"`
	// Factor is the self-throttle's factor after this run, 1 for a collector that always runs.
	Factor int `json:"factor"`
	// Throttled means the collector did not run this time: its block is left out of the report, and the
	// monitoring service keeps the state of the checks that live on it.
	Throttled bool `json:"throttled"`
	// Reason is why a throttled collector did not run when it is not its own throttle: shedReason for
	// the load gate.
	Reason string `json:"reason,omitempty"`
}

// throttle is the self-throttle of one optional collector, kept in the report state.
type throttle struct {
	Factor int `json:"factor,omitempty"`
	// Hits and Clean count the runs in a row with and without a time-limit hit.
	Hits  int `json:"hits,omitempty"`
	Clean int `json:"clean,omitempty"`
	// Skipped counts the runs the throttle held the collector back since it last ran.
	Skipped int `json:"skipped,omitempty"`
}

// factor is t's factor, held to 1..maxThrottleFactor whatever the state file says.
func (t throttle) factor() int {
	return min(max(t.Factor, 1), maxThrottleFactor)
}

// holdsBack says whether the collector skips this run: with factor n it runs once in n runs.
func (t throttle) holdsBack() bool {
	return t.Skipped+1 < t.factor()
}

// after is t once the collector ran, with or without a time-limit hit.
func (t throttle) after(hit bool) throttle {
	t.Factor = t.factor()
	t.Skipped = 0
	if hit {
		t.Clean = 0
		t.Hits++
		if t.Hits >= throttleHits {
			t.Factor = min(t.Factor*2, maxThrottleFactor)
			t.Hits = 0
		}
		return t
	}
	t.Hits = 0
	t.Clean++
	if t.Clean >= throttleClean {
		t.Factor = max(t.Factor/2, 1)
		t.Clean = 0
	}
	return t
}

// selfMeasure measures the collectors of one report and throttles the optional ones against prev,
// their throttles as the last saved report state left them.
type selfMeasure struct {
	prev  map[string]throttle
	next  map[string]throttle
	stats map[string]collectorStat
	// shedding is set by the load gate: the optional collectors do not run.
	shedding bool
}

func newSelfMeasure(prev map[string]throttle) *selfMeasure {
	return &selfMeasure{prev: prev, next: map[string]throttle{}, stats: map[string]collectorStat{}}
}

// core runs a core collector in the measuring frame. A core collector carries the base checks and
// always runs.
func (m *selfMeasure) core(ctx context.Context, name string, collect func(context.Context)) {
	m.stats[name] = measured(ctx, collect)
}

// optional runs an optional collector in the measuring frame unless the load gate or its throttle holds
// it back this run, and says whether it ran. A tool its own timeout ended is a time-limit hit.
func (m *selfMeasure) optional(ctx context.Context, name string, collect func(context.Context)) bool {
	if m.shedding {
		m.shed(name)
		return false
	}
	t := m.prev[name]
	if t.holdsBack() {
		t.Skipped++
		m.next[name] = t
		m.stats[name] = collectorStat{Factor: t.factor(), Throttled: true}
		return false
	}
	st := measured(ctx, collect)
	m.record(name, st, st.Timeouts)
	return true
}

// shed holds name back for the load gate. Its throttle stays as the last run left it: what the
// collector costs is measured again once it runs.
func (m *selfMeasure) shed(name string) {
	t, ok := m.prev[name]
	if ok {
		m.next[name] = t
	}
	m.stats[name] = collectorStat{Factor: t.factor(), Throttled: true, Reason: shedReason}
}

// record keeps st as name's entry with hits time-limit hits and moves name's throttle on by them.
func (m *selfMeasure) record(name string, st collectorStat, hits int) {
	t := m.prev[name].after(hits > 0)
	st.Timeouts = hits
	st.Factor = t.Factor
	m.next[name] = t
	m.stats[name] = st
}

// measured runs collect and returns its duration, its CPU time and its tools that hit their timeout.
// The collectors run one after the other, so the process's CPU time between two reads is collect's.
func measured(ctx context.Context, collect func(context.Context)) collectorStat {
	ctx, timeouts := execx.CountTimeouts(ctx)
	cpu := processCPUTime()
	began := time.Now()
	collect(ctx)
	return collectorStat{
		DurationMS: time.Since(began).Milliseconds(),
		CPUMS:      (processCPUTime() - cpu).Milliseconds(),
		Timeouts:   int(timeouts.Load()),
		Factor:     1,
	}
}
