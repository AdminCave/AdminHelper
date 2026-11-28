// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"context"
	"os/exec"
	"reflect"
	"testing"
	"time"

	"adminhelper-agent/internal/discovery"
	"adminhelper-agent/internal/probe"
)

// stubReportHost stubs the collectors that do real, slow, host-dependent I/O so a test exercises the
// report assembly, not the host (6.18): the 1s CPU sample, the docker/pvesh/zpool/smartctl
// subprocess calls, the system state, the host facts lookups and the load gate's reading. Without
// this the "unit" test sleeps >=1s and its result/duration depend on the host.
func stubReportHost(t *testing.T) {
	t.Helper()
	oldInterval := cpuSampleInterval
	cpuSampleInterval = 0
	oldPlugins := pluginCollectors
	pluginCollectors.docker = func(context.Context) *DockerBlock { return nil }
	pluginCollectors.proxmox = func(context.Context, *backupIndexCheck, time.Time) (*ProxmoxBlock, *backupIndexCheck) {
		return nil, nil
	}
	pluginCollectors.zfs = func(context.Context) *ZFSBlock { return nil }
	pluginCollectors.smart = func(context.Context) ([]SmartDisk, string) { return nil, "not_installed" }
	oldSvc := serviceHealthCollector
	serviceHealthCollector = func(context.Context, *serviceCache, time.Time) (*ServiceHealth, *serviceCache) {
		return &ServiceHealth{}, nil
	}
	oldSystemState := systemStateCollector
	systemStateCollector = func(_ context.Context, st reportState) (*SystemState, reportState) { return nil, st }
	oldHostFacts := hostFactsCalls
	hostFactsCalls.platform = func() (string, string, string, error) { return "", "", "", nil }
	hostFactsCalls.virtualization = func() (string, string, error) { return "", "", nil }
	hostFactsCalls.lookPath = func(string) (string, error) { return "", exec.ErrNotFound }
	oldDiscovery := runDiscovery
	runDiscovery = func(context.Context, []probe.Marker) discovery.Inventory {
		t.Error("a discovery ran, want none")
		return discovery.Inventory{}
	}
	// The host's own load must not shed the collectors a test looks at.
	oldReadLoad := readLoad
	readLoad = func(*Resources, *cpuSample, *cpuSample) loadReading { return loadReading{} }
	t.Cleanup(func() {
		readLoad = oldReadLoad
		runDiscovery = oldDiscovery
		cpuSampleInterval = oldInterval
		pluginCollectors = oldPlugins
		serviceHealthCollector = oldSvc
		systemStateCollector = oldSystemState
		hostFactsCalls = oldHostFacts
	})
}

func TestBuildReportBasics(t *testing.T) {
	stubReportHost(t)

	report := BuildReport(nil)

	if got := report.ReportVersion; got != 4 {
		t.Errorf("report_version = %v, erwartet 4", got)
	}

	if _, err := time.Parse("2006-01-02T15:04:05Z", report.Timestamp); err != nil {
		t.Errorf("timestamp %q nicht im erwarteten Format: %v", report.Timestamp, err)
	}

	if report.Resources == nil {
		t.Fatal("resources fehlt")
	}

	wire := reportWire(t, report)
	if _, ok := wire["uptime_seconds"]; !ok {
		t.Error("uptime_seconds fehlt")
	}
	if report.Systemd == nil {
		t.Error("systemd fehlt")
	}
	// Without watched services there must be no legacy "services" key.
	if _, ok := wire["services"]; ok {
		t.Error("services gesetzt, obwohl keine Service-Namen uebergeben wurden")
	}
}

// smartWire is the report's smart and smart_absent keys as the monitoring service receives them (see
// dockerWire); only those, so the host's own resource values cannot break the encoding.
func smartWire(t *testing.T, report *Report) map[string]any {
	t.Helper()
	keys := map[string]any{}
	for k, v := range reportWire(t, report) {
		if k == "smart" || k == "smart_absent" {
			keys[k] = v
		}
	}
	return keys
}

// reportWire is the report as the monitoring service decodes it.
func reportWire(t *testing.T, report *Report) map[string]any {
	t.Helper()
	return dockerWire(t, report)
}

func TestBuildReportSmartAbsent(t *testing.T) {
	// Through the real collectSmart with only smartctl faked: the reason it finds is what the
	// monitoring service receives as smart_absent.reason, and there is no smart key.
	cases := []struct {
		reason string
		stub   func(t *testing.T)
	}{
		{"not_installed", func(t *testing.T) {
			stubSmartctl(t, dockerReply{}, nil)
			smartctlCLI.lookPath = func(string) (string, error) { return "", exec.ErrNotFound }
		}},
		{"scan_failed", func(t *testing.T) { stubSmartctl(t, dockerReply{err: context.DeadlineExceeded}, nil) }},
		{"no_devices", func(t *testing.T) { stubSmartctl(t, dockerReply{out: `{"devices":[]}`}, nil) }},
	}
	for _, c := range cases {
		t.Run(c.reason, func(t *testing.T) {
			stubReportHost(t)
			pluginCollectors.smart = collectSmart
			c.stub(t)
			got := smartWire(t, BuildReport(nil))
			want := map[string]any{"smart_absent": map[string]any{"reason": c.reason}}
			if !reflect.DeepEqual(got, want) {
				t.Errorf("report smart keys = %v, want %v", got, want)
			}
		})
	}
}

func TestBuildReportSmartDisks(t *testing.T) {
	stubReportHost(t)
	pluginCollectors.smart = collectSmart
	stubSmartctl(t, dockerReply{out: smartScanFixture}, map[string]dockerReply{
		"/dev/sda":   {out: ataFixture},
		"/dev/nvme0": {out: nvmeFixture},
	})
	got := smartWire(t, BuildReport(nil))
	if disks, _ := got["smart"].([]any); len(disks) != 2 {
		t.Errorf("smart = %#v, want both disks", got["smart"])
	}
	if absent, ok := got["smart_absent"]; ok {
		t.Errorf("smart_absent = %v, want none with disks", absent)
	}
}

func TestBuildReportPassesItsContextToSmart(t *testing.T) {
	type ctxKey struct{}
	stubReportHost(t)
	var got context.Context
	pluginCollectors.smart = func(ctx context.Context) ([]SmartDisk, string) {
		got = ctx
		return nil, "not_installed"
	}
	ctx := context.WithValue(context.Background(), ctxKey{}, t.Name())
	buildReportWithState(ctx, nil, nil, reportState{}, time.Now())
	if got == nil || got.Value(ctxKey{}) != t.Name() {
		t.Errorf("smart collector got context %v, want the report's", got)
	}
}

func TestBuildReportPassesItsContextToTheSystemState(t *testing.T) {
	type ctxKey struct{}
	stubReportHost(t)
	var got context.Context
	systemStateCollector = func(ctx context.Context, st reportState) (*SystemState, reportState) {
		got = ctx
		return nil, st
	}
	ctx := context.WithValue(context.Background(), ctxKey{}, t.Name())
	buildReportWithState(ctx, nil, nil, reportState{}, time.Now())
	if got == nil || got.Value(ctxKey{}) != t.Name() {
		t.Errorf("system state collector got context %v, want the report's", got)
	}
}

func TestBuildReportSystemState(t *testing.T) {
	// The key comes only with a field: a block without one (nothing measured) is no block.
	for name, tc := range map[string]struct {
		block *SystemState
		want  bool
	}{
		"with a field": {&SystemState{OOMKills: new(uint64(2))}, true},
		"empty block":  {&SystemState{}, false},
		"no block":     {nil, false},
	} {
		t.Run(name, func(t *testing.T) {
			stubReportHost(t)
			systemStateCollector = func(_ context.Context, st reportState) (*SystemState, reportState) { return tc.block, st }
			got := BuildReport(nil).SystemState
			if ok := got != nil; ok != tc.want || (ok && !reflect.DeepEqual(got, tc.block)) {
				t.Errorf("system_state = %v (present %v), want %v (present %v)", got, ok, tc.block, tc.want)
			}
		})
	}
}

func TestBuildReportSystemStateCarriesState(t *testing.T) {
	// The push path hands the collector the saved state and saves what it hands back, with the new CPU
	// sample in place of the saved one. monitor init's BuildReport hands it the empty state.
	stubReportHost(t)
	s := stubCPU(t)
	s.times = cpuTimes(300, 1100)
	now := time.Unix(1_700_000_000, 0)
	saved, measured := uint64(5), uint64(7)
	var handed []reportState
	systemStateCollector = func(_ context.Context, st reportState) (*SystemState, reportState) {
		handed = append(handed, st)
		st.OOMKill = &measured
		kills := measured - saved
		return &SystemState{OOMKills: &kills}, st
	}

	prevCPU := &cpuSample{Unix: now.Add(-5 * time.Minute).Unix(), Total: 1000, Busy: 200}
	report, next := buildReportWithState(context.Background(), nil, nil, reportState{CPU: prevCPU, OOMKill: &saved}, now)
	if len(handed) != 1 || handed[0].OOMKill == nil || *handed[0].OOMKill != saved {
		t.Fatalf("collector got %+v, want the saved counter %d", handed, saved)
	}
	if next.OOMKill == nil || *next.OOMKill != measured {
		t.Errorf("next oom_kill = %v, want %d from the collector", next.OOMKill, measured)
	}
	if want := (cpuSample{Unix: now.Unix(), Total: 1400, Busy: 300}); next.CPU == nil || *next.CPU != want {
		t.Errorf("next cpu = %+v, want the new sample %+v", next.CPU, want)
	}
	wire := dockerWire(t, map[string]any{"system_state": report.SystemState})
	if want := map[string]any{"system_state": map[string]any{"oom_kills": 2.0}}; !reflect.DeepEqual(wire, want) {
		t.Errorf("report = %v, want %v", wire, want)
	}

	handed = nil
	BuildReport(nil)
	if len(handed) != 1 || handed[0].OOMKill != nil || handed[0].CPU != nil {
		t.Errorf("BuildReport handed the collector %+v, want the empty state", handed)
	}
}

// stubDiscovery has runDiscovery answer inv and returns the markers of each discovery that ran.
func stubDiscovery(t *testing.T, inv discovery.Inventory) *[][]probe.Marker {
	t.Helper()
	var calls [][]probe.Marker
	old := runDiscovery
	runDiscovery = func(_ context.Context, markers []probe.Marker) discovery.Inventory {
		calls = append(calls, markers)
		return inv
	}
	t.Cleanup(func() { runDiscovery = old })
	return &calls
}

func TestBuildReportRunsADiscoveryOnlyWhenThePlanAsksForOne(t *testing.T) {
	stubReportHost(t)
	inv := discovery.Inventory{TS: 1, Markers: map[string]bool{"nginx": true}}
	calls := stubDiscovery(t, inv)
	markers := []probe.Marker{{ID: "nginx", Paths: []string{"/etc/nginx"}}}
	due := throttle{Factor: 2, Skipped: 1}

	// No discovery asked for: none runs, and its throttle stays as it was.
	for _, work := range []*probeWork{nil, {markers: markers}} {
		report, next := buildReportWithState(context.Background(), nil, work, reportState{Throttle: map[string]throttle{discoveryCollector: due}}, time.Now())
		if report.Discovery != nil || len(*calls) != 0 {
			t.Fatalf("work %+v: a discovery block, %d discoveries; want none", work, len(*calls))
		}
		if _, ok := selfStats(t, report)[discoveryCollector]; ok {
			t.Errorf("work %+v: a discovery stat, want none", work)
		}
		if next.Throttle[discoveryCollector] != due {
			t.Errorf("work %+v: discovery throttle %+v, want %+v kept", work, next.Throttle[discoveryCollector], due)
		}
	}

	// Asked for: it runs with the plan's markers, its block goes out and its run is measured.
	report, next := buildReportWithState(context.Background(), nil, &probeWork{scan: true, markers: markers},
		reportState{Throttle: map[string]throttle{discoveryCollector: due}}, time.Now())
	if !reflect.DeepEqual(*calls, [][]probe.Marker{markers}) {
		t.Fatalf("discoveries %v, want one with the plan's markers", *calls)
	}
	if got := report.Discovery; got == nil || !reflect.DeepEqual(*got, inv) {
		t.Errorf("discovery block = %#v, want the inventory", got)
	}
	if st, ok := selfStats(t, report)[discoveryCollector]; !ok || st.Throttled {
		t.Errorf("discovery stat = %+v (%v), want a run", st, ok)
	}
	if th := next.Throttle[discoveryCollector]; th.Skipped != 0 || th.Factor != 2 {
		t.Errorf("discovery throttle after its run = %+v, want factor 2, none skipped", th)
	}

	// Held back by its throttle: it waits for a later run.
	report, next = buildReportWithState(context.Background(), nil, &probeWork{scan: true, markers: markers},
		reportState{Throttle: map[string]throttle{discoveryCollector: {Factor: 2}}}, time.Now())
	if report.Discovery != nil || len(*calls) != 1 {
		t.Errorf("a throttled discovery ran (%d discoveries), want it held back", len(*calls))
	}
	if st := selfStats(t, report)[discoveryCollector]; !st.Throttled || next.Throttle[discoveryCollector].Skipped != 1 {
		t.Errorf("discovery stat %+v, throttle %+v: want it held back once", st, next.Throttle[discoveryCollector])
	}
}
