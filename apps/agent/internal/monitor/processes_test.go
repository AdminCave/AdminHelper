// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"context"
	"reflect"
	"testing"
	"time"
)

// stubProcesses swaps the process readings for readings, one map per call in turn (the last again
// once they run out), and the gap for one that passes at once, or ends the context when gap is 0. Each
// reading moves the clock on by gap/2 and so does the wait: from the start of one reading to the start
// of the next is gap. It returns the number of readings taken.
func stubProcesses(t *testing.T, gap time.Duration, readings ...map[int32]processReading) *int {
	t.Helper()
	oldRead, oldWait, oldClock := readProcesses, waitProcessGap, processClock
	clock := time.Unix(1_800_000_000, 0)
	calls := 0
	readProcesses = func(context.Context) map[int32]processReading {
		r := readings[min(calls, len(readings)-1)]
		calls++
		clock = clock.Add(gap / 2)
		return r
	}
	waitProcessGap = func(context.Context) bool {
		clock = clock.Add(gap / 2)
		return gap > 0
	}
	processClock = func() time.Time { return clock }
	t.Cleanup(func() { readProcesses, waitProcessGap, processClock = oldRead, oldWait, oldClock })
	return &calls
}

func TestTopProcessesNameTheBusiestFiveOfEachList(t *testing.T) {
	const mib = 1 << 20
	first := map[int32]processReading{
		0:  {name: "idle", cpu: 0, rss: 0},
		1:  {name: "systemd", cpu: 10, rss: 12 * mib},
		11: {name: "postgres", cpu: 100, rss: 900 * mib},
		12: {name: "java", cpu: 200, rss: 2000 * mib},
		13: {name: "nginx", cpu: 50, rss: 30 * mib},
		14: {name: "php-fpm", cpu: 70, rss: 80 * mib},
		15: {name: "php-fpm", cpu: 70, rss: 80 * mib},
		16: {name: "rsync", cpu: 5, rss: 9000 * mib},
		17: {name: "old", cpu: 1, rss: 5000 * mib},
	}
	second := map[int32]processReading{
		0:  {name: "idle", cpu: 50, rss: 0},
		1:  {name: "systemd", cpu: 10.1, rss: 12 * mib},
		11: {name: "postgres", cpu: 101.5, rss: 950 * mib},
		12: {name: "java", cpu: 202, rss: 2100 * mib},
		13: {name: "nginx", cpu: 50.2, rss: 30 * mib},
		14: {name: "php-fpm", cpu: 70.5, rss: 80 * mib},
		15: {name: "php-fpm", cpu: 70.5, rss: 81 * mib},
		// 16 ended between the readings; 17 is a new process under a pid used before.
		17: {name: "new", cpu: 9, rss: 6000 * mib},
		18: {name: "late", cpu: 3, rss: 1},
	}
	stubProcesses(t, 2*time.Second, first, second)

	got := collectTopProcesses(context.Background())
	want := &TopProcesses{
		CPU: []ProcessCPU{
			{PID: 12, Name: "java", CPUPct: 100},
			{PID: 11, Name: "postgres", CPUPct: 75},
			{PID: 14, Name: "php-fpm", CPUPct: 25},
			{PID: 15, Name: "php-fpm", CPUPct: 25},
			{PID: 13, Name: "nginx", CPUPct: 10},
		},
		Memory: []ProcessMemory{
			{PID: 12, Name: "java", RSS: 2100 * mib},
			{PID: 11, Name: "postgres", RSS: 950 * mib},
			{PID: 15, Name: "php-fpm", RSS: 81 * mib},
			{PID: 14, Name: "php-fpm", RSS: 80 * mib},
			{PID: 13, Name: "nginx", RSS: 30 * mib},
		},
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("top processes =\n%v\nwant\n%v", wireValue(t, got), wireValue(t, want))
	}
}

func TestTopProcessesAreNoneWithoutTwoReadings(t *testing.T) {
	one := map[int32]processReading{7: {name: "java", cpu: 1, rss: 1}}
	for _, c := range []struct {
		name     string
		gap      time.Duration
		readings []map[int32]processReading
		calls    int
	}{
		{"no process readable", time.Second, []map[int32]processReading{{}}, 1},
		{"the context ends in the gap", 0, []map[int32]processReading{one}, 1},
		{"every process gone by the second reading", time.Second, []map[int32]processReading{one, {}}, 2},
	} {
		t.Run(c.name, func(t *testing.T) {
			calls := stubProcesses(t, c.gap, c.readings...)
			if got := collectTopProcesses(context.Background()); got != nil {
				t.Errorf("top processes = %v, want none", got)
			}
			if *calls != c.calls {
				t.Errorf("%d readings, want %d", *calls, c.calls)
			}
		})
	}
}

func TestUnderLoadFromEightyPercentCPUOrMemory(t *testing.T) {
	for _, c := range []struct {
		resources *Resources
		want      bool
	}{
		{&Resources{CPUPercent: 79.9, MemoryUsage: &MemoryUsage{MemoryPercent: 79.9}}, false},
		{&Resources{CPUPercent: 80.0, MemoryUsage: &MemoryUsage{MemoryPercent: 10.0}}, true},
		{&Resources{CPUPercent: 10.0, MemoryUsage: &MemoryUsage{MemoryPercent: 92.5}}, true},
		{&Resources{CPUPercent: 10.0}, false},
		{&Resources{}, false},
	} {
		if got := underLoad(c.resources); got != c.want {
			t.Errorf("underLoad(%v) = %v, want %v", wireValue(t, c.resources), got, c.want)
		}
	}
}

// The resources block carries the list exactly when it is under load; the CPU share is driven, the
// memory share is this host's.
func TestResourcesNameTheTopProcessesUnderLoad(t *testing.T) {
	now := time.Unix(1_800_000_000, 0)
	prev := &cpuSample{Unix: now.Add(-time.Minute).Unix(), Total: 1000, Busy: 200}
	reading := map[int32]processReading{7: {name: "java", cpu: 1, rss: 1}}
	for _, c := range []struct {
		name string
		busy float64
	}{
		{"90 % CPU", 560},
		{"25 % CPU", 300},
	} {
		t.Run(c.name, func(t *testing.T) {
			s := stubCPU(t)
			s.times = cpuTimes(c.busy, 1400-c.busy)
			calls := stubProcesses(t, time.Second, reading)
			resources, _ := collectResources(context.Background(), prev, now)
			has := resources.TopProcesses != nil
			if load := underLoad(resources); has != load || (*calls > 0) != load {
				t.Errorf("resources %v: top_processes %v after %d readings, want it %v",
					wireValue(t, resources), has, *calls, load)
			}
			if c.busy == 560 && !has {
				t.Errorf("at %v %% CPU no top_processes", resources.CPUPercent)
			}
		})
	}
}
