// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"reflect"
	"sync/atomic"
	"testing"
	"time"

	"github.com/shirou/gopsutil/v4/cpu"

	"adminhelper-agent/internal/config"
	"adminhelper-agent/internal/credentials"
	"adminhelper-agent/internal/discovery"
	"adminhelper-agent/internal/probe"
)

func ptr(v float64) *float64 { return &v }

func TestLoadShedEntersOnTheSecondRunOverAndLeavesOnTheThirdRunUnder(t *testing.T) {
	base := time.Unix(1_700_000_000, 0)
	steps := []struct {
		over bool
		want loadShed
	}{
		{true, loadShed{Hits: 1}},
		// One run under the limits in between starts the count anew.
		{false, loadShed{}},
		{true, loadShed{Hits: 1}},
		{true, loadShed{Active: true, Since: base.Add(3 * time.Minute).Unix()}},
		{false, loadShed{Active: true, Since: base.Add(3 * time.Minute).Unix(), Clean: 1}},
		{false, loadShed{Active: true, Since: base.Add(3 * time.Minute).Unix(), Clean: 2}},
		// A run over the limits while shedding starts the way out anew.
		{true, loadShed{Active: true, Since: base.Add(3 * time.Minute).Unix()}},
		{false, loadShed{Active: true, Since: base.Add(3 * time.Minute).Unix(), Clean: 1}},
		{false, loadShed{Active: true, Since: base.Add(3 * time.Minute).Unix(), Clean: 2}},
		{false, loadShed{}},
	}
	var s loadShed
	for i, step := range steps {
		s = s.after(step.over, base.Add(time.Duration(i)*time.Minute))
		if s != step.want {
			t.Fatalf("step %d (over %v): %+v, want %+v", i, step.over, s, step.want)
		}
	}
}

func TestLoadReadingOverNamesTheReadingsAtTheirLimits(t *testing.T) {
	cases := []struct {
		name string
		r    loadReading
		want []string
	}{
		{"nothing read", loadReading{}, []string{}},
		{"all under", loadReading{LoadPerCPU: ptr(1.99), Iowait: ptr(24.9), MemAvailable: ptr(10)}, []string{}},
		{"load at its limit", loadReading{LoadPerCPU: ptr(2)}, []string{"load"}},
		{"iowait at its limit", loadReading{Iowait: ptr(25)}, []string{"iowait"}},
		{"memory under its limit", loadReading{MemAvailable: ptr(9.9)}, []string{"memory"}},
		{"all over, in order", loadReading{LoadPerCPU: ptr(4), Iowait: ptr(60), MemAvailable: ptr(2)}, []string{"load", "iowait", "memory"}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := tc.r.over(); got == nil || !reflect.DeepEqual(got, tc.want) {
				t.Errorf("over() = %#v, want %#v", got, tc.want)
			}
		})
	}
}

func TestLoadReadingOfReadsTheResourcesAndTheCPUWindow(t *testing.T) {
	stubReportHost(t)
	stubResources(t, "linux")
	// The CPU count as collectSwapAndCPUCount reports it, so a change of its type breaks this test.
	resources := collectSwapAndCPUCount()
	resources["load_1m"] = 20.0
	resources["memory_percent"] = 92.5
	prev := &cpuSample{Unix: 1_700_000_000, Total: 1000, Iowait: 50}
	cur := &cpuSample{Unix: 1_700_000_300, Total: 1400, Iowait: 150}

	r := loadReadingOf(resources, prev, cur)
	if want := (loadReading{LoadPerCPU: ptr(2.5), Iowait: ptr(25), MemAvailable: ptr(7.5)}); !reflect.DeepEqual(r, want) {
		t.Fatalf("reading = %v, want %v", r.values(), want.values())
	}
	if got := (loadShed{}).block(r); !reflect.DeepEqual(got, map[string]any{
		"active": false,
		"over":   []string{"load", "iowait", "memory"},
		"values": map[string]float64{"load_per_cpu": 2.5, "iowait_percent": 25, "mem_available_percent": 7.5},
	}) {
		t.Errorf("block = %#v", got)
	}

	// In a container the load is the host's: not read.
	hostFactsCalls.virtualization = func() (string, string, error) { return "lxc", "guest", nil }
	if r := loadReadingOf(resources, prev, cur); r.LoadPerCPU != nil || r.MemAvailable == nil {
		t.Errorf("in a container: %v, want no load per CPU and the memory", r.values())
	}
	hostFactsCalls.virtualization = func() (string, string, error) { return "kvm", "guest", nil }
	if r := loadReadingOf(resources, prev, cur); r.LoadPerCPU == nil {
		t.Error("in a VM: no load per CPU, want it read")
	}

	// Windows sends no load and no CPU count; a missing value is not read.
	if r := loadReadingOf(map[string]any{"memory_percent": 40.0}, nil, cur); r.LoadPerCPU != nil || r.Iowait != nil || *r.MemAvailable != 60 {
		t.Errorf("without load, CPU count and a CPU window: %v, want the memory only", r.values())
	}
	if r := loadReadingOf(map[string]any{"load_1m": 3.0}, prev, cur); r.LoadPerCPU != nil || r.MemAvailable != nil {
		t.Errorf("without a CPU count and memory: %v, want neither load nor memory", r.values())
	}
	if got := (loadShed{}).block(loadReading{}); !reflect.DeepEqual(got, map[string]any{
		"active": false, "over": []string{}, "values": map[string]float64{},
	}) {
		t.Errorf("block of an empty reading = %#v", got)
	}
}

func TestIowaitPercentSince(t *testing.T) {
	prev := &cpuSample{Unix: 1_700_000_000, Total: 1000, Busy: 200, Iowait: 50}
	cases := []struct {
		name string
		prev *cpuSample
		cur  *cpuSample
		want *float64
	}{
		{"a quarter waiting", prev, &cpuSample{Unix: prev.Unix + 300, Total: 1400, Iowait: 150}, ptr(25)},
		{"counter went back: 0", prev, &cpuSample{Unix: prev.Unix + 300, Total: 1400, Iowait: 40}, ptr(0)},
		{"no wait counter before (old state)", &cpuSample{Unix: prev.Unix, Total: 1000}, &cpuSample{Unix: prev.Unix + 300, Total: 1400, Iowait: 150}, nil},
		{"no wait counter now (not Linux)", prev, &cpuSample{Unix: prev.Unix + 300, Total: 1400}, nil},
		{"no sample before", nil, &cpuSample{Unix: prev.Unix + 300, Total: 1400, Iowait: 150}, nil},
		{"no sample now", prev, nil, nil},
		{"16 min old", prev, &cpuSample{Unix: prev.Unix + 960, Total: 1400, Iowait: 150}, nil},
		{"total did not grow (reboot)", prev, &cpuSample{Unix: prev.Unix + 300, Total: 900, Iowait: 60}, nil},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := iowaitPercentSince(tc.prev, tc.cur)
			if (got == nil) != (tc.want == nil) || (got != nil && *got != *tc.want) {
				t.Errorf("iowait = %v, want %v", deref(got), deref(tc.want))
			}
		})
	}
}

func deref(v *float64) any {
	if v == nil {
		return nil
	}
	return *v
}

func TestCollectCPUSinceKeepsTheIowaitCounter(t *testing.T) {
	s := stubCPU(t)
	s.times = &cpu.TimesStat{CPU: "cpu-total", User: 300, Idle: 1000, Iowait: 100}
	now := time.Unix(1_700_000_300, 0)
	_, next := collectCPUSince(&cpuSample{Unix: 1_700_000_000, Total: 1000, Busy: 200}, now)
	if next == nil || next.Iowait != 100 || next.Busy != 300 {
		t.Fatalf("sample = %+v, want the iowait counter 100 kept apart from busy 300", next)
	}
}

// selfLoadShed is the report's self.load_shed block.
func selfLoadShed(t *testing.T, report map[string]any) map[string]any {
	t.Helper()
	block, ok := report["self"].(map[string]any)["load_shed"].(map[string]any)
	if !ok {
		t.Fatalf("self.load_shed = %#v, want a block", report["self"].(map[string]any)["load_shed"])
	}
	return block
}

func TestBuildReportShedsWhatFollowsTheCoreUnderLoad(t *testing.T) {
	stubReportHost(t)
	over := true
	readLoad = func(map[string]any, *cpuSample, *cpuSample) loadReading {
		if over {
			return loadReading{LoadPerCPU: ptr(3), MemAvailable: ptr(50)}
		}
		return loadReading{LoadPerCPU: ptr(0.5), MemAvailable: ptr(50)}
	}
	plugins := 0
	pluginCollectors.docker = func(context.Context) map[string]any { plugins++; return map[string]any{"available": true} }
	pluginCollectors.proxmox = func(_ context.Context, b *backupIndexCheck, _ time.Time) (map[string]any, *backupIndexCheck) {
		plugins++
		return map[string]any{"node": "n"}, b
	}
	pluginCollectors.zfs = func(context.Context) map[string]any { plugins++; return map[string]any{"pools": []any{}} }
	pluginCollectors.smart = func(context.Context) ([]SmartDisk, string) { plugins++; return nil, "not_installed" }
	probeCalls := stubRunProbe(t, okResult)
	discoveries := stubDiscovery(t, discovery.Inventory{})
	work := &probeWork{
		probes: []probe.Probe{{ID: "p", IntervalS: 300, TimeoutS: 1}},
		creds:  map[string]credentials.Credential{},
		scan:   true,
	}

	base := time.Now().Add(-time.Hour)
	var state reportState
	run := func(i int) map[string]any {
		t.Helper()
		// The probe is due in every run.
		if res, ok := state.Probes["p"]; ok {
			res.TS = time.Now().Add(-time.Hour).Unix()
			state.Probes["p"] = res
		}
		var report map[string]any
		report, state = buildReportWithState(context.Background(), nil, work, state, base.Add(time.Duration(i)*5*time.Minute))
		return report
	}
	measuredAll := func(i int, report map[string]any, want int) {
		t.Helper()
		if plugins != 4*want || len(*probeCalls) != want || len(*discoveries) != want {
			t.Fatalf("run %d: %d plugin calls, %d probes, %d discoveries; want every one run %d times", i, plugins, len(*probeCalls), len(*discoveries), want)
		}
		for name, st := range selfStats(t, report) {
			if st.Throttled || st.Reason != "" {
				t.Errorf("run %d: %s stat %+v, want it measured", i, name, st)
			}
		}
	}

	// 1) Over the limits once: everything runs.
	report := run(1)
	measuredAll(1, report, 1)
	if got := selfLoadShed(t, report); got["active"] != false || !reflect.DeepEqual(got["over"], []string{"load"}) {
		t.Errorf("run 1: load_shed %v, want inactive and over load", got)
	}

	// 2) Over the limits again: what follows the core waits.
	before := state
	report = run(2)
	if plugins != 4 || len(*probeCalls) != 1 || len(*discoveries) != 1 {
		t.Fatalf("run 2: %d plugin calls, %d probes, %d discoveries; want nothing after the core run", plugins, len(*probeCalls), len(*discoveries))
	}
	stats := selfStats(t, report)
	for _, name := range []string{"docker", "proxmox", "zfs", "smart", probesCollector, discoveryCollector} {
		if st := stats[name]; st != (collectorStat{Factor: 1, Throttled: true, Reason: shedReason}) {
			t.Errorf("run 2: %s stat %+v, want held back for the load", name, st)
		}
	}
	for _, name := range []string{"resources", "system_state", "services"} {
		if st, ok := stats[name]; !ok || st.Throttled || st.Reason != "" {
			t.Errorf("run 2: core %s stat %+v (present %v), want it measured", name, st, ok)
		}
	}
	for _, key := range []string{"docker", "proxmox", "zfs", "smart", "smart_absent", "discovery"} {
		if v, ok := report[key]; ok {
			t.Errorf("run 2: report %s = %v, want it left out", key, v)
		}
	}
	if got := report["probes"].(probe.Results)["p"]; got.TS != before.Probes["p"].TS || got.Status != probe.StatusOK {
		t.Errorf("run 2: report probes p = %+v, want the stored result", got)
	}
	if _, ok := report["credentials"]; !ok {
		t.Error("run 2: the credentials block is missing, want it sent as in every run")
	}
	if !reflect.DeepEqual(state.Throttle, before.Throttle) || !reflect.DeepEqual(state.Probes, before.Probes) {
		t.Errorf("run 2: throttle %+v, probes %+v; want both as the run before left them", state.Throttle, state.Probes)
	}
	since := base.Add(10 * time.Minute)
	if want := (loadShed{Active: true, Since: since.Unix()}); state.LoadShed != want {
		t.Errorf("run 2: state %+v, want %+v", state.LoadShed, want)
	}
	if got := selfLoadShed(t, report); !reflect.DeepEqual(got, map[string]any{
		"active": true,
		"since":  since.UTC().Format("2006-01-02T15:04:05Z"),
		"over":   []string{"load"},
		"values": map[string]float64{"load_per_cpu": 3, "mem_available_percent": 50},
	}) {
		t.Errorf("run 2: load_shed %#v", got)
	}
	wire, err := json.Marshal(report["self"])
	if err != nil {
		t.Fatal(err)
	}
	var self struct {
		Collectors map[string]map[string]any `json:"collectors"`
		LoadShed   map[string]any            `json:"load_shed"`
	}
	if err := json.Unmarshal(wire, &self); err != nil {
		t.Fatal(err)
	}
	if self.Collectors["docker"]["reason"] != "load" || self.LoadShed["active"] != true {
		t.Errorf("run 2 on the wire: %s, want reason load and an active load_shed", wire)
	}

	// 3) Two runs under the limits: still shedding.
	over = false
	for i := 3; i <= 4; i++ {
		report = run(i)
		if plugins != 4 || len(*probeCalls) != 1 || len(*discoveries) != 1 {
			t.Fatalf("run %d: something after the core ran, want it held back", i)
		}
		if got := selfLoadShed(t, report); got["active"] != true || !reflect.DeepEqual(got["over"], []string{}) {
			t.Errorf("run %d: load_shed %v, want active and over nothing", i, got)
		}
	}

	// 4) The third run under the limits measures everything again.
	report = run(5)
	measuredAll(5, report, 2)
	if got := selfLoadShed(t, report); got["active"] != false || got["since"] != nil {
		t.Errorf("run 5: load_shed %v, want inactive without since", got)
	}
	if state.LoadShed != (loadShed{}) {
		t.Errorf("run 5: state %+v, want none", state.LoadShed)
	}
}

func TestBuildReportShedsNoThrottleItHasNot(t *testing.T) {
	stubReportHost(t)
	readLoad = func(map[string]any, *cpuSample, *cpuSample) loadReading {
		return loadReading{MemAvailable: ptr(3)}
	}
	prev := reportState{
		LoadShed: loadShed{Hits: 1},
		Throttle: map[string]throttle{"docker": {Factor: 4, Skipped: 1}},
	}

	report, next := buildReportWithState(context.Background(), nil, nil, prev, time.Now())

	if st := selfStats(t, report)["docker"]; st != (collectorStat{Factor: 4, Throttled: true, Reason: shedReason}) {
		t.Errorf("docker stat = %+v, want held back for the load at its factor", st)
	}
	if !reflect.DeepEqual(next.Throttle, prev.Throttle) {
		t.Errorf("throttle = %+v, want only docker's, unchanged", next.Throttle)
	}
	if got := selfLoadShed(t, report)["over"]; !reflect.DeepEqual(got, []string{"memory"}) {
		t.Errorf("over = %v, want memory", got)
	}
}

func TestPushKeepsTheLoadGateAfterALostPush(t *testing.T) {
	stubReportHost(t)
	shortenRetryDelay(t)
	stubCPU(t)
	t.Setenv("ADMINHELPER_MONITOR_DIR", t.TempDir())
	readLoad = func(map[string]any, *cpuSample, *cpuSample) loadReading {
		return loadReading{LoadPerCPU: ptr(5)}
	}

	var status atomic.Int32
	status.Store(http.StatusBadGateway)
	active := make(chan any, 8)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodGet {
			w.WriteHeader(http.StatusNotFound)
			return
		}
		var body struct {
			Self struct {
				LoadShed map[string]any `json:"load_shed"`
			} `json:"self"`
		}
		data, _ := io.ReadAll(r.Body)
		if err := json.Unmarshal(data, &body); err != nil {
			t.Errorf("report body: %v", err)
		}
		active <- body.Self.LoadShed["active"]
		w.WriteHeader(int(status.Load()))
	}))
	defer srv.Close()
	if err := config.WriteKeyValue(config.MonitorConfFile(), []config.KeyValue{
		{Key: "MONITOR_URL", Value: srv.URL},
		{Key: "API_KEY", Value: "key"},
		{Key: "SERVER_ID", Value: "srv-1"},
	}); err != nil {
		t.Fatal(err)
	}
	statePath := config.MonitorReportStateFile()

	// Two lost pushes over the limits: the second one sheds, and the state says so.
	for i := 1; i <= 2; i++ {
		if err := Push(context.Background()); err == nil {
			t.Fatalf("push %d against 502: want an error", i)
		}
	}
	if st := loadReportState(statePath).LoadShed; !st.Active || st.Since == 0 {
		t.Fatalf("state after two lost pushes = %+v, want shedding", st)
	}

	// The next push goes through, still shedding.
	status.Store(http.StatusOK)
	for len(active) > 0 {
		<-active
	}
	if err := Push(context.Background()); err != nil {
		t.Fatal(err)
	}
	if got := <-active; got != true {
		t.Errorf("load_shed.active sent = %v, want true", got)
	}
}
