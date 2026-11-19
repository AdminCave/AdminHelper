// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"context"
	"sort"
	"time"

	"github.com/shirou/gopsutil/v4/process"
)

const (
	// topProcessesFrom is the CPU or memory share from which the report names the busiest processes.
	topProcessesFrom = 80.0
	// topProcessesCount is how many processes each list names.
	topProcessesCount = 5
	// topProcessesGap is the time between the two readings the CPU shares are measured over.
	topProcessesGap = time.Second
)

// processReading is what one reading tells of a process: its name, the CPU seconds it used so far and
// its resident memory in bytes. The name is gopsutil's: comm, or where comm is cut to 15 characters the
// base of argv[0] if that starts with comm; never a path or an argument.
type processReading struct {
	name string
	cpu  float64
	rss  uint64
}

// readProcesses reads every process it can, by pid; a seam for the tests. A process that ends or
// cannot be read while it reads is left out.
var readProcesses = func(ctx context.Context) map[int32]processReading {
	procs, err := process.ProcessesWithContext(ctx)
	if err != nil {
		return nil
	}
	out := make(map[int32]processReading, len(procs))
	for _, p := range procs {
		if ctx.Err() != nil {
			break
		}
		name, err := p.NameWithContext(ctx)
		if err != nil || name == "" {
			continue
		}
		times, err := p.TimesWithContext(ctx)
		if err != nil {
			continue
		}
		mem, err := p.MemoryInfoWithContext(ctx)
		if err != nil {
			continue
		}
		out[p.Pid] = processReading{name: name, cpu: times.User + times.System, rss: mem.RSS}
	}
	return out
}

// waitProcessGap waits topProcessesGap, false if ctx ended first; a seam for the tests.
var waitProcessGap = func(ctx context.Context) bool {
	t := time.NewTimer(topProcessesGap)
	defer t.Stop()
	select {
	case <-t.C:
		return true
	case <-ctx.Done():
		return false
	}
}

// processClock is the clock the gap between the readings is measured with; a seam for the tests.
var processClock = time.Now

// collectTopProcesses is the resources block's top_processes: the topProcessesCount processes with
// the highest CPU share over topProcessesGap and those with the most resident memory, each busiest
// first. Only a process with a pid from 1 that both readings found under the same name counts. Nil
// when neither list has an entry or ctx ends before the second reading.
func collectTopProcesses(ctx context.Context) map[string]any {
	// A reading takes time of its own, longest under load; a process is read about this far apart in
	// both, so the shares divide by it and not by the gap alone.
	start := processClock()
	first := readProcesses(ctx)
	if len(first) == 0 || !waitProcessGap(ctx) {
		return nil
	}
	elapsed := processClock().Sub(start)
	second := readProcesses(ctx)
	if elapsed <= 0 {
		return nil
	}

	type entry struct {
		pid  int32
		name string
		cpu  float64
		rss  uint64
	}
	var entries []entry
	for pid, b := range second {
		a, ok := first[pid]
		if pid < 1 || !ok || a.name != b.name {
			continue
		}
		cpu := (b.cpu - a.cpu) / elapsed.Seconds() * 100
		if cpu < 0 {
			cpu = 0
		}
		entries = append(entries, entry{pid: pid, name: b.name, cpu: cpu, rss: b.rss})
	}
	if len(entries) == 0 {
		return nil
	}

	// The pid breaks ties, so equal readings give the same list each time.
	sort.Slice(entries, func(i, j int) bool {
		if entries[i].cpu != entries[j].cpu {
			return entries[i].cpu > entries[j].cpu
		}
		return entries[i].pid < entries[j].pid
	})
	var cpu []map[string]any
	for _, e := range entries[:min(topProcessesCount, len(entries))] {
		cpu = append(cpu, map[string]any{"pid": e.pid, "name": e.name, "cpu_pct": round1(e.cpu)})
	}
	sort.Slice(entries, func(i, j int) bool {
		if entries[i].rss != entries[j].rss {
			return entries[i].rss > entries[j].rss
		}
		return entries[i].pid < entries[j].pid
	})
	var memory []map[string]any
	for _, e := range entries[:min(topProcessesCount, len(entries))] {
		memory = append(memory, map[string]any{"pid": e.pid, "name": e.name, "rss": e.rss})
	}
	return map[string]any{"cpu": cpu, "memory": memory}
}

// underLoad says whether the resources block's CPU or memory share reaches topProcessesFrom.
func underLoad(resources map[string]any) bool {
	for _, key := range []string{"cpu_percent", "memory_percent"} {
		if v, ok := resources[key].(float64); ok && v >= topProcessesFrom {
			return true
		}
	}
	return false
}
