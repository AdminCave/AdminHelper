// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package monitor

import (
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

// stubVMStat points vmstatPath at a file holding content for the duration of the test.
func stubVMStat(t *testing.T, content string) {
	t.Helper()
	path := filepath.Join(t.TempDir(), "vmstat")
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
	old := vmstatPath
	vmstatPath = path
	t.Cleanup(func() { vmstatPath = old })
}

// vmstatWithOOMKill is /proc/vmstat cut down to the counter and two neighbours.
func vmstatWithOOMKill(n uint64) string {
	return fmt.Sprintf("pgmajfault 1042\noom_kill %d\nnuma_hit 77\n", n)
}

func TestSystemStateParseOOMKill(t *testing.T) {
	cases := []struct {
		name   string
		vmstat string
		want   uint64
		ok     bool
	}{
		{"among other counters", vmstatWithOOMKill(3), 3, true},
		{"zero", "oom_kill 0\n", 0, true},
		{"no oom_kill line (kernel before 4.13)", "pgmajfault 1042\nnuma_hit 77\n", 0, false},
		{"empty", "", 0, false},
		{"not a number", "oom_kill many\n", 0, false},
		{"negative", "oom_kill -1\n", 0, false},
		{"no value", "oom_kill\n", 0, false},
		{"only a similar name", "oom_kill_total 7\n", 0, false},
	}
	for _, c := range cases {
		got, ok := parseOOMKill([]byte(c.vmstat))
		if got != c.want || ok != c.ok {
			t.Errorf("%s: parseOOMKill = %d, %v; want %d, %v", c.name, got, ok, c.want, c.ok)
		}
	}
}

func TestSystemStateOOMFirstRun(t *testing.T) {
	// The first run has no counter to count from: no field, but the counter goes into the state, also a
	// 0 through the state file, so the second run reports the kills since the first.
	stubVMStat(t, vmstatWithOOMKill(0))
	block, next := collectSystemState(reportState{})
	if len(block) != 0 {
		t.Errorf("first run block = %v, want no field", block)
	}
	if next.OOMKill == nil || *next.OOMKill != 0 {
		t.Fatalf("first run state oom_kill = %v, want the counter 0", next.OOMKill)
	}

	path := filepath.Join(t.TempDir(), ".report-state.json")
	if err := saveReportState(path, next); err != nil {
		t.Fatal(err)
	}
	stubVMStat(t, vmstatWithOOMKill(2))
	block, next = collectSystemState(loadReportState(path))
	if got, want := dockerWire(t, block), map[string]any{"oom_kills": 2.0}; !reflect.DeepEqual(got, want) {
		t.Errorf("second run block = %v, want %v", got, want)
	}
	if next.OOMKill == nil || *next.OOMKill != 2 {
		t.Errorf("second run state oom_kill = %v, want 2", next.OOMKill)
	}
}

func TestSystemStateOOMKills(t *testing.T) {
	cases := []struct {
		name         string
		saved, count uint64
		want         uint64
	}{
		{"growth", 5, 7, 2},
		{"no new kills", 7, 7, 0},
		{"smaller counter after a reboot", 10, 3, 3},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			stubVMStat(t, vmstatWithOOMKill(c.count))
			cpu := &cpuSample{Unix: 1_700_000_000, Total: 1000, Busy: 200}
			saved := c.saved
			block, next := collectSystemState(reportState{CPU: cpu, OOMKill: &saved})
			if want := map[string]any{"oom_kills": c.want}; !reflect.DeepEqual(block, want) {
				t.Errorf("block = %v, want %v", block, want)
			}
			if next.OOMKill == nil || *next.OOMKill != c.count {
				t.Errorf("state oom_kill = %v, want the counter %d", next.OOMKill, c.count)
			}
			if next.CPU != cpu {
				t.Errorf("state cpu = %+v, want it handed on unchanged", next.CPU)
			}
		})
	}
}

func TestSystemStateOOMUnreadable(t *testing.T) {
	// Without a counter there is no field, the saved counter stays the base for the next report, and
	// the log names why.
	cases := []struct {
		name string
		stub func(t *testing.T)
		log  string
	}{
		{"no /proc/vmstat", func(t *testing.T) {
			old := vmstatPath
			vmstatPath = filepath.Join(t.TempDir(), "missing")
			t.Cleanup(func() { vmstatPath = old })
		}, "no such file or directory, oom_kills left out"},
		{"no oom_kill line", func(t *testing.T) { stubVMStat(t, "pgmajfault 1042\n") },
			"no readable oom_kill counter in /proc/vmstat, oom_kills left out"},
		{"broken number", func(t *testing.T) { stubVMStat(t, "oom_kill 1x\n") },
			"no readable oom_kill counter in /proc/vmstat, oom_kills left out"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			c.stub(t)
			logs := captureWarnings(t)
			saved := uint64(4)
			block, next := collectSystemState(reportState{OOMKill: &saved})
			if len(block) != 0 {
				t.Errorf("block = %v, want no field", block)
			}
			if next.OOMKill == nil || *next.OOMKill != 4 {
				t.Errorf("state oom_kill = %v, want the saved 4 kept", next.OOMKill)
			}
			if !strings.Contains(logs.String(), c.log) {
				t.Errorf("log = %q, want it to name %q", logs.String(), c.log)
			}
		})
	}
}
