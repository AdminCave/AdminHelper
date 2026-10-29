// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os/exec"
	"reflect"
	"sync/atomic"
	"testing"
	"time"

	"adminhelper-agent/internal/config"
)

// stubReportHost stubs the collectors that do real, slow, host-dependent I/O so a test exercises the
// report assembly, not the host (6.18): the 1s CPU sample, the docker/pvesh/zpool/smartctl
// subprocess calls, the system state and the host facts lookups. Without this the "unit" test sleeps
// >=1s and its result/duration depend on the host.
func stubReportHost(t *testing.T) {
	t.Helper()
	oldInterval := cpuSampleInterval
	cpuSampleInterval = 0
	oldPlugins := pluginCollectors
	pluginCollectors.docker = func(context.Context) map[string]any { return nil }
	pluginCollectors.proxmox = func(context.Context) map[string]any { return nil }
	pluginCollectors.zfs = func(context.Context) map[string]any { return nil }
	pluginCollectors.smart = func(context.Context) ([]SmartDisk, string) { return nil, "not_installed" }
	oldSvc := serviceHealthCollector
	serviceHealthCollector = func(context.Context) map[string]any { return map[string]any{} }
	oldSystemState := systemStateCollector
	systemStateCollector = func(_ context.Context, st reportState) (map[string]any, reportState) { return nil, st }
	oldHostFacts := hostFactsCalls
	hostFactsCalls.platform = func() (string, string, string, error) { return "", "", "", nil }
	hostFactsCalls.virtualization = func() (string, string, error) { return "", "", nil }
	hostFactsCalls.lookPath = func(string) (string, error) { return "", exec.ErrNotFound }
	t.Cleanup(func() {
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

	if got := report["report_version"]; got != 3 {
		t.Errorf("report_version = %v, erwartet 3", got)
	}

	ts, ok := report["timestamp"].(string)
	if !ok {
		t.Fatalf("timestamp fehlt oder ist kein String: %v", report["timestamp"])
	}
	if _, err := time.Parse("2006-01-02T15:04:05Z", ts); err != nil {
		t.Errorf("timestamp %q nicht im erwarteten Format: %v", ts, err)
	}

	resources, ok := report["resources"].(map[string]any)
	if !ok {
		t.Fatalf("resources fehlt oder hat falschen Typ: %v", report["resources"])
	}
	if _, ok := resources["cpu_percent"]; !ok {
		t.Error("resources.cpu_percent fehlt")
	}

	if _, ok := report["uptime_seconds"]; !ok {
		t.Error("uptime_seconds fehlt")
	}
	if _, ok := report["systemd"]; !ok {
		t.Error("systemd fehlt")
	}
	// Without watched services there must be no legacy "services" key.
	if _, ok := report["services"]; ok {
		t.Error("services gesetzt, obwohl keine Service-Namen uebergeben wurden")
	}
}

// smartWire is the report's smart and smart_absent keys as the monitoring service receives them (see
// dockerWire); only those, so the host's own resource values cannot break the encoding.
func smartWire(t *testing.T, report map[string]any) map[string]any {
	t.Helper()
	keys := map[string]any{}
	for _, k := range []string{"smart", "smart_absent"} {
		if v, ok := report[k]; ok {
			keys[k] = v
		}
	}
	return dockerWire(t, keys)
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
	buildReportWithState(ctx, nil, reportState{}, time.Now())
	if got == nil || got.Value(ctxKey{}) != t.Name() {
		t.Errorf("smart collector got context %v, want the report's", got)
	}
}

func TestBuildReportPassesItsContextToTheSystemState(t *testing.T) {
	type ctxKey struct{}
	stubReportHost(t)
	var got context.Context
	systemStateCollector = func(ctx context.Context, st reportState) (map[string]any, reportState) {
		got = ctx
		return nil, st
	}
	ctx := context.WithValue(context.Background(), ctxKey{}, t.Name())
	buildReportWithState(ctx, nil, reportState{}, time.Now())
	if got == nil || got.Value(ctxKey{}) != t.Name() {
		t.Errorf("system state collector got context %v, want the report's", got)
	}
}

func TestBuildReportSystemState(t *testing.T) {
	// The key comes only with a field: a block without one (nothing measured) is no block.
	for name, tc := range map[string]struct {
		block map[string]any
		want  bool
	}{
		"with a field": {map[string]any{"oom_kills": uint64(2)}, true},
		"empty block":  {map[string]any{}, false},
		"no block":     {nil, false},
	} {
		t.Run(name, func(t *testing.T) {
			stubReportHost(t)
			systemStateCollector = func(_ context.Context, st reportState) (map[string]any, reportState) { return tc.block, st }
			got, ok := BuildReport(nil)["system_state"]
			if ok != tc.want || (ok && !reflect.DeepEqual(got, tc.block)) {
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
	systemStateCollector = func(_ context.Context, st reportState) (map[string]any, reportState) {
		handed = append(handed, st)
		st.OOMKill = &measured
		return map[string]any{"oom_kills": measured - saved}, st
	}

	prevCPU := &cpuSample{Unix: now.Add(-5 * time.Minute).Unix(), Total: 1000, Busy: 200}
	report, next := buildReportWithState(context.Background(), nil, reportState{CPU: prevCPU, OOMKill: &saved}, now)
	if len(handed) != 1 || handed[0].OOMKill == nil || *handed[0].OOMKill != saved {
		t.Fatalf("collector got %+v, want the saved counter %d", handed, saved)
	}
	if next.OOMKill == nil || *next.OOMKill != measured {
		t.Errorf("next oom_kill = %v, want %d from the collector", next.OOMKill, measured)
	}
	if want := (cpuSample{Unix: now.Unix(), Total: 1400, Busy: 300}); next.CPU == nil || *next.CPU != want {
		t.Errorf("next cpu = %+v, want the new sample %+v", next.CPU, want)
	}
	wire := dockerWire(t, map[string]any{"system_state": report["system_state"]})
	if want := map[string]any{"system_state": map[string]any{"oom_kills": 2.0}}; !reflect.DeepEqual(wire, want) {
		t.Errorf("report = %v, want %v", wire, want)
	}

	handed = nil
	BuildReport(nil)
	if len(handed) != 1 || handed[0].OOMKill != nil || handed[0].CPU != nil {
		t.Errorf("BuildReport handed the collector %+v, want the empty state", handed)
	}
}

// shortenRetryDelay shrinks the push retry backoff for the test duration.
func shortenRetryDelay(t *testing.T) {
	t.Helper()
	orig := pushRetryDelay
	pushRetryDelay = time.Millisecond
	t.Cleanup(func() { pushRetryDelay = orig })
}

func TestPushReportSuccessNoRetry(t *testing.T) {
	shortenRetryDelay(t)
	var attempts atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		attempts.Add(1)
		if r.Header.Get("X-API-Key") != "key" {
			t.Errorf("X-API-Key = %q, erwartet %q", r.Header.Get("X-API-Key"), "key")
		}
		w.WriteHeader(http.StatusOK)
	}))
	defer srv.Close()

	if err := PushReport(context.Background(), PushReportParams{URL: srv.URL, APIKey: "key", ServerID: "srv-1", Report: map[string]any{"a": 1}}); err != nil {
		t.Fatalf("PushReport: %v", err)
	}
	if got := attempts.Load(); got != 1 {
		t.Errorf("attempts = %d, erwartet 1 (kein Retry bei Erfolg)", got)
	}
}

func TestPushReportRetriesOnceOnTransientError(t *testing.T) {
	shortenRetryDelay(t)
	var attempts atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if attempts.Add(1) == 1 {
			w.WriteHeader(http.StatusInternalServerError)
			return
		}
		w.WriteHeader(http.StatusOK)
	}))
	defer srv.Close()

	if err := PushReport(context.Background(), PushReportParams{URL: srv.URL, APIKey: "key", ServerID: "srv-1", Report: map[string]any{"a": 1}}); err != nil {
		t.Fatalf("PushReport nach Retry: %v", err)
	}
	if got := attempts.Load(); got != 2 {
		t.Errorf("attempts = %d, erwartet 2 (genau ein Retry)", got)
	}
}

func TestPushReportFailsAfterSingleRetry(t *testing.T) {
	shortenRetryDelay(t)
	var attempts atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		attempts.Add(1)
		w.WriteHeader(http.StatusBadGateway)
	}))
	defer srv.Close()

	err := PushReport(context.Background(), PushReportParams{URL: srv.URL, APIKey: "key", ServerID: "srv-1", Report: map[string]any{"a": 1}})
	if err == nil {
		t.Fatal("PushReport erwartete Fehler, bekam keinen")
	}
	if got := attempts.Load(); got != 2 {
		t.Errorf("attempts = %d, erwartet 2 (genau ein Retry, kein Loop)", got)
	}
}

func TestPushReportAbortsInFlightRequestOnContextCancel(t *testing.T) {
	// The handler hangs on its request's ctx. Without 2.67 (ctx reaching the
	// request) the client would block until its own 15s timeout; cancelling
	// mid-flight must abort the in-flight request itself, so PushReport returns
	// promptly. The long backoff would also stall a stray retry, so returning
	// fast proves the ctx short-circuits both the request and the retry.
	orig := pushRetryDelay
	pushRetryDelay = 30 * time.Second
	t.Cleanup(func() { pushRetryDelay = orig })

	ctx, cancel := context.WithCancel(context.Background())
	var attempts atomic.Int32
	reached := make(chan struct{})
	release := make(chan struct{})
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if attempts.Add(1) == 1 {
			close(reached)
		}
		<-release // block until the test releases the handler
	}))
	defer srv.Close()
	defer close(release) // let the blocked handler finish so srv.Close() returns

	go func() {
		<-reached
		cancel()
	}()

	start := time.Now()
	if err := PushReport(ctx, PushReportParams{URL: srv.URL, APIKey: "key", ServerID: "srv-1", Report: map[string]any{"a": 1}}); err == nil {
		t.Fatal("PushReport erwartete ctx-Fehler nach Cancel")
	}
	if elapsed := time.Since(start); elapsed > 5*time.Second {
		t.Errorf("PushReport blockierte %v — der in-flight-Request wurde nicht abgebrochen", elapsed)
	}
	if got := attempts.Load(); got != 1 {
		t.Errorf("attempts = %d, erwartet 1 (kein Retry)", got)
	}
}

func TestPushBudgetKeepsThePushReserve(t *testing.T) {
	stubReportHost(t)
	t.Setenv("ADMINHELPER_MONITOR_DIR", t.TempDir())
	oldReserve := pushReserve
	pushReserve = 300 * time.Millisecond
	t.Cleanup(func() { pushReserve = oldReserve })
	// A collector that hangs until its context ends: only the collection deadline
	// pushReserve before the run's deadline leaves the push its time.
	pluginCollectors.docker = func(ctx context.Context) map[string]any {
		<-ctx.Done()
		return nil
	}

	received := make(chan time.Time, 2)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		received <- time.Now()
		w.WriteHeader(http.StatusOK)
	}))
	defer srv.Close()
	if err := config.WriteKeyValue(config.MonitorConfFile(), []config.KeyValue{
		{Key: "MONITOR_URL", Value: srv.URL},
		{Key: "API_KEY", Value: "key"},
		{Key: "SERVER_ID", Value: "srv-1"},
	}); err != nil {
		t.Fatal(err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	deadline, _ := ctx.Deadline()
	if err := Push(ctx); err != nil {
		t.Fatalf("Push: %v", err)
	}
	select {
	case at := <-received:
		if !at.Before(deadline) {
			t.Fatalf("report received %s after the deadline", at.Sub(deadline))
		}
	default:
		t.Fatal("the server got no report")
	}
}
