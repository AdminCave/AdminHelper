// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"context"
	"encoding/json"
	"os"
	"runtime"
	"testing"
	"time"

	"adminhelper-agent/internal/probe"
)

func TestThrottleAfterDoublesOnTwoHitsAndHalvesOnThreeCleanRuns(t *testing.T) {
	var th throttle
	steps := []struct {
		hit  bool
		want throttle
	}{
		{hit: true, want: throttle{Factor: 1, Hits: 1}},
		{hit: true, want: throttle{Factor: 2}},
		{hit: true, want: throttle{Factor: 2, Hits: 1}},
		{hit: true, want: throttle{Factor: 4}},
		{hit: true, want: throttle{Factor: 4, Hits: 1}},
		{hit: true, want: throttle{Factor: 8}},
		// The cap.
		{hit: true, want: throttle{Factor: 8, Hits: 1}},
		{hit: true, want: throttle{Factor: 8}},
		// A clean run breaks the row of hits, a hit the row of clean runs.
		{hit: true, want: throttle{Factor: 8, Hits: 1}},
		{hit: false, want: throttle{Factor: 8, Clean: 1}},
		{hit: false, want: throttle{Factor: 8, Clean: 2}},
		{hit: true, want: throttle{Factor: 8, Hits: 1}},
		{hit: false, want: throttle{Factor: 8, Clean: 1}},
		{hit: false, want: throttle{Factor: 8, Clean: 2}},
		{hit: false, want: throttle{Factor: 4}},
		{hit: false, want: throttle{Factor: 4, Clean: 1}},
		{hit: false, want: throttle{Factor: 4, Clean: 2}},
		{hit: false, want: throttle{Factor: 2}},
		{hit: false, want: throttle{Factor: 2, Clean: 1}},
		{hit: false, want: throttle{Factor: 2, Clean: 2}},
		{hit: false, want: throttle{Factor: 1}},
		// The floor.
		{hit: false, want: throttle{Factor: 1, Clean: 1}},
		{hit: false, want: throttle{Factor: 1, Clean: 2}},
		{hit: false, want: throttle{Factor: 1}},
	}
	for i, s := range steps {
		th = th.after(s.hit)
		if th != s.want {
			t.Fatalf("step %d (hit %v): %+v, want %+v", i, s.hit, th, s.want)
		}
	}
	if got := (throttle{Factor: 2, Skipped: 1}).after(false); got.Skipped != 0 {
		t.Errorf("after a run Skipped = %d, want 0", got.Skipped)
	}
}

func TestThrottleFactorHoldsWhatTheStateFileSays(t *testing.T) {
	for in, want := range map[int]int{-3: 1, 0: 1, 1: 1, 4: 4, 8: 8, 100: 8} {
		if got := (throttle{Factor: in}).factor(); got != want {
			t.Errorf("factor %d read as %d, want %d", in, got, want)
		}
	}
	if got := (throttle{Factor: 100}).after(true).after(true); got.Factor != maxThrottleFactor {
		t.Errorf("a factor beyond the cap doubled to %d, want %d", got.Factor, maxThrottleFactor)
	}
}

func TestThrottleHoldsBackAllButEveryNthRun(t *testing.T) {
	for _, factor := range []int{1, 2, 4, 8} {
		th := throttle{Factor: factor}
		ran := 0
		for range 8 * factor {
			if th.holdsBack() {
				th.Skipped++
				continue
			}
			ran++
			th = th.after(true)
			th.Factor, th.Hits = factor, 0 // keep the factor; this counts the runs only
		}
		if ran != 8 {
			t.Errorf("factor %d: ran %d times in %d runs, want 8", factor, ran, 8*factor)
		}
	}
}

// selfStats is the self.collectors block of report.
func selfStats(t *testing.T, report map[string]any) map[string]collectorStat {
	t.Helper()
	self, ok := report["self"].(map[string]any)
	if !ok {
		t.Fatalf("report self = %#v, want a block", report["self"])
	}
	stats, ok := self["collectors"].(map[string]collectorStat)
	if !ok {
		t.Fatalf("self.collectors = %#v, want the collectors' stats", self["collectors"])
	}
	return stats
}

func TestBuildReportMeasuresEveryCollector(t *testing.T) {
	stubReportHost(t)
	pluginCollectors.docker = func(context.Context) map[string]any {
		time.Sleep(30 * time.Millisecond)
		return map[string]any{"available": true}
	}
	pluginCollectors.zfs = func(context.Context) map[string]any {
		// Busy until the process has used 50 ms of CPU time: what the frame must count.
		for start := processCPUTime(); processCPUTime()-start < 50*time.Millisecond; {
		}
		return nil
	}

	report, next := buildReportWithState(context.Background(), nil, nil, reportState{}, time.Now())

	stats := selfStats(t, report)
	names := []string{"resources", "system_state", "services", "docker", "proxmox", "zfs", "smart", probesCollector}
	if len(stats) != len(names) {
		t.Errorf("self.collectors has %d entries, want %d: %+v", len(stats), len(names), stats)
	}
	for _, name := range names {
		st, ok := stats[name]
		if !ok || st.Factor != 1 || st.Throttled || st.Timeouts != 0 {
			t.Errorf("%s: %+v (present %v), want measured at factor 1", name, st, ok)
		}
	}
	if d := stats["docker"].DurationMS; d < 30 {
		t.Errorf("docker duration_ms = %d, want at least the 30 ms it slept", d)
	}
	if c := stats["zfs"].CPUMS; c < 50 {
		t.Errorf("zfs cpu_ms = %d, want at least the 50 ms it burned", c)
	}
	// The optional collectors and the probe phase carry a throttle; the core collectors never do.
	for _, name := range []string{"docker", "proxmox", "zfs", "smart", probesCollector} {
		if th := next.Throttle[name]; th != (throttle{Factor: 1, Clean: 1}) {
			t.Errorf("throttle of %s = %+v, want one clean run", name, th)
		}
	}
	for _, name := range []string{"resources", "system_state", "services"} {
		if _, ok := next.Throttle[name]; ok {
			t.Errorf("the core collector %s has a throttle", name)
		}
	}
	data, err := json.Marshal(report["self"])
	if err != nil {
		t.Fatal(err)
	}
	var wire struct {
		Collectors map[string]map[string]any `json:"collectors"`
	}
	if err := json.Unmarshal(data, &wire); err != nil {
		t.Fatal(err)
	}
	for _, key := range []string{"duration_ms", "cpu_ms", "timeouts", "factor", "throttled"} {
		if _, ok := wire.Collectors["docker"][key]; !ok {
			t.Errorf("self.collectors.docker on the wire = %v, want the key %s", wire.Collectors["docker"], key)
		}
	}
}

func TestBuildReportCountsTheCPUTimeOfTheToolsItWaitedFor(t *testing.T) {
	stubReportHost(t)
	t.Setenv(dockerHelperEnv, "spin")
	pluginCollectors.proxmox = func(ctx context.Context, _ *backupIndexCheck, _ time.Time) (map[string]any, *backupIndexCheck) {
		if _, err := execTimed(ctx, time.Minute, nil, os.Args[0], "-test.run=^TestHelperDockerProcess$"); err != nil {
			t.Errorf("spinning helper: %v", err)
		}
		return nil, nil
	}

	report, _ := buildReportWithState(context.Background(), nil, nil, reportState{}, time.Now())

	c := selfStats(t, report)["proxmox"].CPUMS
	// Windows counts no CPU time of ended children to the agent; the tool's cost is then its wait.
	if runtime.GOOS != "windows" && c < spinCPU.Milliseconds() {
		t.Errorf("proxmox cpu_ms = %d, want at least the %d ms its tool burned", c, spinCPU.Milliseconds())
	}
}

func TestBuildReportThrottlesAnOptionalCollectorThatHitsItsTimeLimit(t *testing.T) {
	stubReportHost(t)
	t.Setenv(dockerHelperEnv, "hang")
	calls := 0
	pluginCollectors.docker = func(ctx context.Context) map[string]any {
		calls++
		_, err := execTimed(ctx, 50*time.Millisecond, nil, os.Args[0], "-test.run=^TestHelperDockerProcess$")
		return map[string]any{"available": false, "error": err.Error()}
	}
	var state reportState
	run := func() map[string]any {
		t.Helper()
		var report map[string]any
		report, state = buildReportWithState(context.Background(), nil, nil, state, time.Now())
		return report
	}

	// Two runs in a row with a hit double the factor.
	for i := 1; i <= 2; i++ {
		report := run()
		st := selfStats(t, report)["docker"]
		if calls != i || report["docker"] == nil || st.Timeouts != 1 || st.Throttled || st.Factor != i {
			t.Fatalf("run %d: %d calls, docker %v, stat %+v; want it run with a hit at factor %d", i, calls, report["docker"], st, i)
		}
	}

	// At factor 2 the next run leaves docker out, the one after runs it again.
	report := run()
	st := selfStats(t, report)["docker"]
	if calls != 2 || st != (collectorStat{Factor: 2, Throttled: true}) {
		t.Fatalf("throttled run: %d calls, stat %+v; want docker held back at factor 2", calls, st)
	}
	if _, ok := report["docker"]; ok {
		t.Error("the throttled docker block is in the report")
	}
	if th := state.Throttle["docker"]; th.Skipped != 1 || th.Factor != 2 {
		t.Errorf("throttle after the held-back run = %+v, want one run skipped at factor 2", th)
	}
	run()
	if calls != 3 {
		t.Fatalf("after the held-back run: %d calls, want docker run again", calls)
	}
	// The other optional collectors ran in every run, without a hit.
	if th := state.Throttle["zfs"]; th.Factor != 1 || th.Skipped != 0 {
		t.Errorf("zfs throttle = %+v, want it untouched by docker's hits", th)
	}
}

func TestBuildReportLeavesTheBlockOfAHeldBackCollectorOut(t *testing.T) {
	stubReportHost(t)
	called := false
	pluginCollectors.smart = func(context.Context) ([]SmartDisk, string) {
		called = true
		return nil, "not_installed"
	}
	prev := reportState{Throttle: map[string]throttle{
		"smart": {Factor: 2},
		// A throttle in the state never holds a core collector back.
		"services": {Factor: 8},
	}}

	report, next := buildReportWithState(context.Background(), nil, nil, prev, time.Now())

	if called {
		t.Error("the held-back smart collector ran")
	}
	for _, key := range []string{"smart", "smart_absent"} {
		if v, ok := report[key]; ok {
			t.Errorf("report %s = %v, want it left out with the held-back collector", key, v)
		}
	}
	stats := selfStats(t, report)
	if st := stats["smart"]; !st.Throttled || st.Factor != 2 {
		t.Errorf("smart stat = %+v, want throttled at factor 2", st)
	}
	if st := stats["services"]; st.Throttled || st.Factor != 1 || report["systemd"] == nil {
		t.Errorf("services stat = %+v, systemd %v; want the core collector run", st, report["systemd"])
	}
	if th := next.Throttle["smart"]; th != (throttle{Factor: 2, Skipped: 1}) {
		t.Errorf("smart throttle = %+v, want one run skipped at factor 2", th)
	}
}

func TestBuildReportThrottlesTheProbePhaseByThePostponedProbes(t *testing.T) {
	stubReportHost(t)
	calls := stubRunProbe(t, okResult)
	// A probe whose timeout the run never leaves room for is postponed in every run.
	long := []probe.Probe{{ID: "long", IntervalS: 300, TimeoutS: 600}}
	var state reportState
	for i := 1; i <= 2; i++ {
		ctx, cancel := context.WithTimeout(context.Background(), time.Minute)
		var report map[string]any
		report, state = buildReportWithState(ctx, nil, &probeWork{probes: long}, state, time.Now())
		cancel()
		st := selfStats(t, report)[probesCollector]
		if st.Timeouts != 1 || st.Factor != i || st.Throttled {
			t.Fatalf("run %d: probes stat %+v, want one postponed at factor %d", i, st, i)
		}
		if _, ok := report["probes"]; !ok {
			t.Fatalf("run %d: the probes block is missing, want it in every run", i)
		}
	}
	if len(*calls) != 0 {
		t.Fatalf("ran %v, want the long probe postponed", *calls)
	}

	// At factor 2 a 300 s probe is not due 400 s after its run; the phase still runs and reports.
	now := time.Now()
	state.Probes = probe.Results{"p": {TS: now.Add(-400 * time.Second).Unix(), Status: probe.StatusOK}}
	report, _ := buildReportWithState(context.Background(), nil, &probeWork{probes: []probe.Probe{{ID: "p", IntervalS: 300, TimeoutS: 1}}}, state, now)
	if len(*calls) != 0 {
		t.Errorf("ran %v at factor 2, want the probe not due yet", *calls)
	}
	if got := report["probes"].(probe.Results)["p"]; got.TS != state.Probes["p"].TS {
		t.Errorf("report probes p = %+v, want its last result", got)
	}
	if st := selfStats(t, report)[probesCollector]; st.Throttled || st.Timeouts != 0 {
		t.Errorf("probes stat = %+v, want a clean run that is never throttled", st)
	}
}
