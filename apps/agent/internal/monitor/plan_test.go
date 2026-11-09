// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"adminhelper-agent/internal/config"
	"adminhelper-agent/internal/credentials"
	"adminhelper-agent/internal/probe"
)

const planOneProbe = `{"plan_version": 1, "catalog_version": "c1", "scan": false, "discovery": {"markers": []},
	"probes": [{"id": "chk-1", "sensor": "fake", "interval_s": 600, "timeout_s": 5, "target": null,
	"params": {}, "fields": ["status"], "credential": null}]}`

// planServer answers the plan GET with status and body and counts the requests; every other request
// is answered 200.
func planServer(t *testing.T, status *atomic.Int32, body *atomic.Value) (*httptest.Server, *atomic.Int32) {
	t.Helper()
	var gets atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			w.WriteHeader(http.StatusOK)
			return
		}
		gets.Add(1)
		w.WriteHeader(int(status.Load()))
		_, _ = w.Write([]byte(body.Load().(string)))
	}))
	t.Cleanup(srv.Close)
	return srv, &gets
}

func monitorConfig(url string) *config.MonitorConfig {
	return &config.MonitorConfig{MonitorURL: url, APIKey: "agent-key", ServerID: "srv-1"}
}

func TestCurrentPlanFetchesAndSavesThePlan(t *testing.T) {
	t.Setenv("ADMINHELPER_MONITOR_DIR", t.TempDir())
	var got *http.Request
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		got = r.Clone(context.Background())
		_, _ = w.Write([]byte(planOneProbe))
	}))
	defer srv.Close()
	cfg := monitorConfig(srv.URL)
	cfg.ServerID = "srv 1/x"
	planPath := config.MonitorPlanFile()

	plan := currentPlan(context.Background(), cfg, planPath)

	if len(plan.Probes) != 1 || plan.Probes[0].ID != "chk-1" || plan.Probes[0].IntervalS != 600 || plan.CatalogVersion != "c1" {
		t.Fatalf("plan = %+v, want the one probe sent", plan)
	}
	if got == nil || got.Method != http.MethodGet || got.URL.EscapedPath() != "/agent/srv%201%2Fx/plan" {
		t.Fatalf("request = %v, want GET /agent/srv%%201%%2Fx/plan", got)
	}
	if got.Header.Get("X-API-Key") != "agent-key" {
		t.Errorf("X-API-Key = %q, want the agent's key", got.Header.Get("X-API-Key"))
	}
	for name := range got.Header {
		if name != "X-Api-Key" && name != "User-Agent" && name != "Accept-Encoding" {
			t.Errorf("the plan request carries header %s, want only the agent's key", name)
		}
	}
	data, err := os.ReadFile(planPath)
	if err != nil {
		t.Fatalf("the plan was not saved: %v", err)
	}
	if saved, err := parsePlan(data); err != nil || !reflect.DeepEqual(saved, plan) {
		t.Fatalf("saved plan = %+v (%v), want %+v", saved, err, plan)
	}
	if runtime.GOOS != "windows" {
		if info, err := os.Stat(planPath); err != nil || info.Mode().Perm() != 0600 {
			t.Fatalf("plan file: %v, %v; want mode 600", info, err)
		}
	}
}

func TestCurrentPlanKeepsTheSavedPlan(t *testing.T) {
	cases := []struct {
		name   string
		status int
		body   string
		down   bool
	}{
		{name: "404 from a monitoring service without the route", status: http.StatusNotFound, body: `{"detail":"Not Found"}`},
		{name: "server error", status: http.StatusServiceUnavailable, body: "down"},
		{name: "unreachable", down: true},
		{name: "an unknown plan version", status: http.StatusOK, body: `{"plan_version": 2, "probes": []}`},
		{name: "not JSON", status: http.StatusOK, body: "<html>"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			t.Setenv("ADMINHELPER_MONITOR_DIR", t.TempDir())
			planPath := config.MonitorPlanFile()
			if err := os.WriteFile(planPath, []byte(planOneProbe), 0o600); err != nil {
				t.Fatal(err)
			}
			var status atomic.Int32
			status.Store(int32(tc.status))
			var body atomic.Value
			body.Store(tc.body)
			srv, gets := planServer(t, &status, &body)
			if tc.down {
				srv.Close()
			}

			plan := currentPlan(context.Background(), monitorConfig(srv.URL), planPath)

			if len(plan.Probes) != 1 || plan.Probes[0].ID != "chk-1" {
				t.Fatalf("plan = %+v, want the saved one", plan)
			}
			if !tc.down && gets.Load() != 1 {
				t.Errorf("%d plan requests, want 1", gets.Load())
			}
			if data, _ := os.ReadFile(planPath); string(data) != planOneProbe {
				t.Errorf("the saved plan changed to %s", data)
			}
		})
	}
}

func TestCurrentPlanWithoutASavedPlanRunsNoProbe(t *testing.T) {
	t.Setenv("ADMINHELPER_MONITOR_DIR", t.TempDir())
	var status atomic.Int32
	status.Store(http.StatusNotFound)
	var body atomic.Value
	body.Store("")
	srv, _ := planServer(t, &status, &body)
	planPath := config.MonitorPlanFile()

	plan := currentPlan(context.Background(), monitorConfig(srv.URL), planPath)

	if len(plan.Probes) != 0 {
		t.Fatalf("plan = %+v, want no probe", plan)
	}
	if _, err := os.Stat(planPath); !os.IsNotExist(err) {
		t.Errorf("a plan file was written: %v", err)
	}
}

func TestLoadPlanOfABrokenFileRunsNoProbe(t *testing.T) {
	path := filepath.Join(t.TempDir(), ".plan.json")
	if err := os.WriteFile(path, []byte(`{"plan_version": 1, "probes": [`), 0o600); err != nil {
		t.Fatal(err)
	}

	if plan := loadPlan(path); len(plan.Probes) != 0 {
		t.Fatalf("plan = %+v, want no probe", plan)
	}
}

func TestParsePlanHoldsTheProbesToTheAgentsBounds(t *testing.T) {
	probes := []string{
		`{"id": "fast", "sensor": "s", "interval_s": 60, "timeout_s": 0}`,
		`{"id": "slow", "sensor": "s", "interval_s": 3600, "timeout_s": 99}`,
		`{"id": "neg", "sensor": "s", "interval_s": -5, "timeout_s": -1}`,
		`{"id": "ok.1:x_y-z", "sensor": "s", "interval_s": 300, "timeout_s": 30}`,
		`{"id": "fast", "sensor": "other", "interval_s": 900, "timeout_s": 5}`,
		`{"id": "", "sensor": "s"}`,
		`{"id": "a b", "sensor": "s"}`,
		`{"id": "../x", "sensor": "s"}`,
		`{"id": "x\u0000", "sensor": "s"}`,
		fmt.Sprintf(`{"id": %q, "sensor": "s"}`, strings.Repeat("a", 129)),
		fmt.Sprintf(`{"id": %q, "sensor": "s"}`, strings.Repeat("b", 128)),
	}
	plan, err := parsePlan([]byte(`{"plan_version": 1, "probes": [` + strings.Join(probes, ",") + `]}`))
	if err != nil {
		t.Fatal(err)
	}

	type bounds struct {
		id                string
		sensor            string
		interval, timeout int
	}
	var got []bounds
	for _, p := range plan.Probes {
		got = append(got, bounds{p.ID, p.Sensor, p.IntervalS, p.TimeoutS})
	}
	want := []bounds{
		{"fast", "s", 300, 10},
		{"slow", "s", 3600, 30},
		{"neg", "s", 300, 10},
		{"ok.1:x_y-z", "s", 300, 30},
		{strings.Repeat("b", 128), "s", 300, 10},
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("probes = %v\nwant %v", got, want)
	}
}

func TestParsePlanTakesAtMostMaxPlanProbes(t *testing.T) {
	probes := make([]string, 0, maxPlanProbes+10)
	for i := range maxPlanProbes + 10 {
		probes = append(probes, fmt.Sprintf(`{"id": "p%d", "sensor": "s"}`, i))
	}

	plan, err := parsePlan([]byte(`{"plan_version": 1, "probes": [` + strings.Join(probes, ",") + `]}`))

	if err != nil || len(plan.Probes) != maxPlanProbes || plan.Probes[maxPlanProbes-1].ID != fmt.Sprintf("p%d", maxPlanProbes-1) {
		t.Fatalf("parsePlan: %d probes (%v), want the first %d", len(plan.Probes), err, maxPlanProbes)
	}
}

func TestProbeDue(t *testing.T) {
	now := time.Unix(1762700000, 0)
	p := probe.Probe{ID: "c", IntervalS: 300}
	cases := []struct {
		age  time.Duration
		want bool
	}{
		{age: 0, want: false},
		{age: 239 * time.Second, want: false},
		// The slack: a 300 s probe is due again in the next run even when this one started late.
		{age: 240 * time.Second, want: true},
		{age: time.Hour, want: true},
		// A result from the future: the clock went back.
		{age: -time.Second, want: true},
	}
	for _, tc := range cases {
		res := probe.Result{TS: now.Add(-tc.age).Unix()}
		if got := probeDue(p, res, now, 1); got != tc.want {
			t.Errorf("age %s: due = %v, want %v", tc.age, got, tc.want)
		}
	}
	slow := probe.Probe{ID: "c", IntervalS: 3600}
	if probeDue(slow, probe.Result{TS: now.Add(-50 * time.Minute).Unix()}, now, 1) {
		t.Error("a 1 h probe 50 min after its run is due, want not yet")
	}
	// The probe phase's self-throttle stretches the interval, the slack stays.
	if probeDue(p, probe.Result{TS: now.Add(-400 * time.Second).Unix()}, now, 2) {
		t.Error("a 300 s probe at factor 2 is due 400 s after its run, want not yet")
	}
	if !probeDue(p, probe.Result{TS: now.Add(-540 * time.Second).Unix()}, now, 2) {
		t.Error("a 300 s probe at factor 2 is not due 540 s after its run, want due")
	}
}

// stubRunProbe replaces runProbe; run returns the result of p and records the order of the calls.
func stubRunProbe(t *testing.T, run func(ctx context.Context, p probe.Probe, start time.Time, acc *probe.Access) probe.Result) *[]string {
	t.Helper()
	var calls []string
	old := runProbe
	runProbe = func(ctx context.Context, p probe.Probe, start time.Time, acc *probe.Access) probe.Result {
		calls = append(calls, p.ID)
		return run(ctx, p, start, acc)
	}
	t.Cleanup(func() { runProbe = old })
	return &calls
}

func okResult(_ context.Context, _ probe.Probe, start time.Time, _ *probe.Access) probe.Result {
	return probe.Result{TS: start.Unix(), Status: probe.StatusOK, Values: map[string]any{"v": 1}}
}

func TestRunDueProbesRunsTheDueOnesOldestFirst(t *testing.T) {
	calls := stubRunProbe(t, okResult)
	now := time.Now()
	at := func(age time.Duration) probe.Result {
		return probe.Result{TS: now.Add(-age).Unix(), Status: probe.StatusError, Error: "old"}
	}
	probes := []probe.Probe{
		{ID: "recent", IntervalS: 300, TimeoutS: 1},
		{ID: "older", IntervalS: 300, TimeoutS: 1},
		{ID: "never", IntervalS: 300, TimeoutS: 1},
		{ID: "oldest", IntervalS: 300, TimeoutS: 1},
	}
	last := probe.Results{
		"recent": at(100 * time.Second),
		"older":  at(400 * time.Second),
		"oldest": at(4000 * time.Second),
		"gone":   at(time.Hour),
	}

	next, ran, postponed := runDueProbes(context.Background(), probes, last, 1, nil, now)

	if want := []string{"never", "oldest", "older"}; !reflect.DeepEqual(*calls, want) {
		t.Fatalf("ran %v, want %v", *calls, want)
	}
	if ran != 3 || postponed != 0 || len(next) != 4 {
		t.Fatalf("ran %d, postponed %d, %d results; want 3, none and one per probe of the plan", ran, postponed, len(next))
	}
	if !reflect.DeepEqual(next["recent"], last["recent"]) {
		t.Errorf("the probe not due has result %+v, want its last one", next["recent"])
	}
	if _, ok := next["gone"]; ok {
		t.Error("a result of a probe no longer in the plan was kept")
	}
	for _, id := range []string{"never", "oldest", "older"} {
		if next[id].Status != probe.StatusOK {
			t.Errorf("%s: result %+v, want the new one", id, next[id])
		}
	}
}

func TestRunDueProbesStartsAProbeOnlyWithItsWholeTimeoutLeft(t *testing.T) {
	calls := stubRunProbe(t, okResult)
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	old := probe.Result{TS: time.Now().Add(-time.Hour).Unix(), Status: probe.StatusOK}
	probes := []probe.Probe{
		{ID: "long", IntervalS: 300, TimeoutS: 10},
		{ID: "short", IntervalS: 300, TimeoutS: 1},
	}

	next, ran, postponed := runDueProbes(ctx, probes, probe.Results{"long": old}, 1, nil, time.Now())

	if !reflect.DeepEqual(*calls, []string{"short"}) || ran != 1 || postponed != 1 {
		t.Fatalf("ran %v (%d, %d postponed), want only the probe that fits and the other postponed", *calls, ran, postponed)
	}
	if !reflect.DeepEqual(next["long"], old) {
		t.Errorf("the postponed probe has result %+v, want its last one %+v", next["long"], old)
	}
	if !probeDue(probes[0], next["long"], time.Now(), 1) {
		t.Error("the postponed probe is not due for the next run")
	}
}

func TestRunDueProbesDropsAProbeTheRunEndedUnder(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	calls := stubRunProbe(t, func(ctx context.Context, p probe.Probe, start time.Time, _ *probe.Access) probe.Result {
		cancel()
		return probe.Result{TS: start.Unix(), Status: probe.StatusError, Error: "context canceled"}
	})
	old := probe.Result{TS: time.Now().Add(-time.Hour).Unix(), Status: probe.StatusOK}
	probes := []probe.Probe{
		{ID: "first", IntervalS: 300, TimeoutS: 1},
		{ID: "second", IntervalS: 300, TimeoutS: 1},
	}

	next, ran, postponed := runDueProbes(ctx, probes, probe.Results{"first": old}, 1, nil, time.Now())

	if !reflect.DeepEqual(*calls, []string{"second"}) || ran != 0 || postponed != 2 {
		t.Fatalf("ran %v (%d counted, %d postponed), want the never-run probe started, none counted, both postponed", *calls, ran, postponed)
	}
	if _, ok := next["second"]; ok {
		t.Errorf("the cut-short probe has result %+v, want none", next["second"])
	}
	if !reflect.DeepEqual(next["first"], old) {
		t.Errorf("the probe after it has result %+v, want its last one", next["first"])
	}
}

func TestPushSendsTheProbesAndKeepsThemThroughALostPush(t *testing.T) {
	stubReportHost(t)
	shortenRetryDelay(t)
	s := stubCPU(t)
	t.Setenv("ADMINHELPER_MONITOR_DIR", t.TempDir())
	var runs atomic.Int32
	stubRunProbe(t, func(ctx context.Context, p probe.Probe, start time.Time, acc *probe.Access) probe.Result {
		runs.Add(1)
		return okResult(ctx, p, start, acc)
	})

	var planStatus, reportStatus atomic.Int32
	planStatus.Store(http.StatusNotFound)
	reportStatus.Store(http.StatusOK)
	var planBody atomic.Value
	planBody.Store(planOneProbe)
	type sent struct {
		Version int           `json:"report_version"`
		Probes  probe.Results `json:"probes"`
	}
	received := make(chan sent, 8)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodGet {
			w.WriteHeader(int(planStatus.Load()))
			_, _ = w.Write([]byte(planBody.Load().(string)))
			return
		}
		var body sent
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Errorf("report body: %v", err)
		}
		received <- body
		w.WriteHeader(int(reportStatus.Load()))
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
	push := func(busy, idle float64) (sent, error) {
		t.Helper()
		s.times = cpuTimes(busy, idle)
		err := Push(context.Background())
		var last sent
		for len(received) > 0 {
			last = <-received
		}
		return last, err
	}

	// 1) No plan yet: the report carries an empty probes block, the CPU counters are saved.
	got, err := push(200, 800)
	if err != nil || got.Version != 4 || got.Probes == nil || len(got.Probes) != 0 {
		t.Fatalf("push without a plan: err %v, report %+v; want version 4 and probes {}", err, got)
	}
	cpuBefore := loadReportState(statePath).CPU

	// 2) A plan, and the push is lost: the probe ran, its result is kept, the CPU window is not.
	planStatus.Store(http.StatusOK)
	reportStatus.Store(http.StatusBadGateway)
	got, err = push(300, 1100)
	if err == nil {
		t.Fatal("push against 502: want an error")
	}
	first, ok := got.Probes["chk-1"]
	if !ok || first.Status != probe.StatusOK || runs.Load() != 1 {
		t.Fatalf("lost push: report probes %+v after %d runs, want the probe's result", got.Probes, runs.Load())
	}
	st := loadReportState(statePath)
	if !reflect.DeepEqual(st.CPU, cpuBefore) {
		t.Errorf("state cpu after a lost push = %+v, want %+v", st.CPU, cpuBefore)
	}
	if kept, ok := st.Probes["chk-1"]; !ok || kept.TS != first.TS {
		t.Fatalf("state probes after a lost push = %+v, want the result sent", st.Probes)
	}
	// The self-throttle counts the run all the same: the second clean run of the probe phase.
	if th := st.Throttle[probesCollector]; th.Clean != 2 {
		t.Errorf("state throttle of the probes after a lost push = %+v, want the second clean run", th)
	}

	// 3) The next run, monitoring back: the probe is not due, its result goes out again with its time.
	reportStatus.Store(http.StatusOK)
	got, err = push(600, 1800)
	if err != nil || runs.Load() != 1 {
		t.Fatalf("push after the loss: err %v after %d probe runs, want no new run", err, runs.Load())
	}
	if again := got.Probes["chk-1"]; again.TS != first.TS || again.Status != probe.StatusOK {
		t.Fatalf("report probes = %+v, want the kept result at %d", got.Probes, first.TS)
	}
	if st := loadReportState(statePath); st.CPU == nil || st.CPU.Total != 2400 || st.Probes["chk-1"].TS != first.TS {
		t.Fatalf("state after the push = %+v, want the new CPU counters and the kept result", st)
	}

	// 4) The plan swaps the probe for another: the new one runs, the state keeps its result alone.
	planBody.Store(strings.ReplaceAll(planOneProbe, `"chk-1"`, `"chk-2"`))
	got, err = push(700, 1900)
	if err != nil || runs.Load() != 2 || len(got.Probes) != 1 || got.Probes["chk-2"].Status != probe.StatusOK {
		t.Fatalf("push with the new plan: err %v after %d runs, report probes %+v; want chk-2 alone", err, runs.Load(), got.Probes)
	}
	if st := loadReportState(statePath); len(st.Probes) != 1 || st.Probes["chk-2"].Status != probe.StatusOK {
		t.Fatalf("state probes after the push = %+v, want chk-2 alone", st.Probes)
	}
}

const planCredentialProbe = `{"plan_version": 1, "catalog_version": "c1", "scan": false, "discovery": {"markers": []},
	"probes": [{"id": "chk-1", "sensor": "fake", "interval_s": 600, "timeout_s": 5, "target": null,
	"params": {}, "fields": ["status"], "credential": {"ref": "db", "use": "basic"}}]}`

func TestPushSendsTheStoredRefsAndKeepsTheBrakeUntilTheCredentialIsSetAnew(t *testing.T) {
	stubReportHost(t)
	shortenRetryDelay(t)
	stubCPU(t)
	t.Setenv("ADMINHELPER_MONITOR_DIR", t.TempDir())
	credPath := config.MonitorCredentialsFile()
	if err := credentials.Set(context.Background(), credPath, "db", "pw1"); err != nil {
		t.Fatal(err)
	}
	stored, err := credentials.Load(credPath)
	if err != nil {
		t.Fatal(err)
	}
	refusedID := stored["db"].ID
	var secrets []string
	stubRunProbe(t, func(_ context.Context, p probe.Probe, start time.Time, acc *probe.Access) probe.Result {
		// As probe.Run does on a 401: the brake takes the id of the credential the target refused.
		c := acc.Credentials[p.Credential.Ref]
		secrets = append(secrets, c.Secret)
		if acc.Brake == nil {
			acc.Brake = map[string]string{}
		}
		acc.Brake[p.Credential.Ref] = c.ID
		return probe.Result{TS: start.Unix(), Status: probe.StatusDenied, Values: map[string]any{}, Error: "HTTP 401"}
	})

	var reportStatus atomic.Int32
	reportStatus.Store(http.StatusBadGateway)
	received := make(chan map[string]json.RawMessage, 8)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodGet {
			_, _ = w.Write([]byte(planCredentialProbe))
			return
		}
		var body map[string]json.RawMessage
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Errorf("report body: %v", err)
		}
		received <- body
		w.WriteHeader(int(reportStatus.Load()))
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
	push := func() (map[string]json.RawMessage, error) {
		t.Helper()
		err := Push(context.Background())
		var last map[string]json.RawMessage
		for len(received) > 0 {
			last = <-received
		}
		return last, err
	}

	// 1) The push is lost: the probe ran with the stored secret, the report named the ref alone, and the
	// refused credential stays braked.
	got, err := push()
	if err == nil {
		t.Fatal("push against 502: want an error")
	}
	if len(secrets) != 1 || secrets[0] != "pw1" {
		t.Fatalf("the probe got %q, want the stored secret once", secrets)
	}
	if string(got["credentials"]) != `{"db":true}` {
		t.Errorf("report credentials = %s, want {\"db\":true}", got["credentials"])
	}
	if raw, _ := json.Marshal(got); strings.Contains(string(raw), "pw1") || strings.Contains(string(raw), refusedID) {
		t.Errorf("the report carries the secret or its id: %s", raw)
	}
	if st := loadReportState(statePath); !reflect.DeepEqual(st.Brake, map[string]string{"db": refusedID}) {
		t.Fatalf("state brake after a lost push = %v, want db at %s", st.Brake, refusedID)
	}

	// 2) The credentials cannot be read: no credentials block, and the brake stays.
	if err := os.WriteFile(credPath, []byte("not json"), 0o600); err != nil {
		t.Fatal(err)
	}
	reportStatus.Store(http.StatusOK)
	got, err = push()
	if err != nil {
		t.Fatal(err)
	}
	if block, ok := got["credentials"]; ok {
		t.Errorf("report credentials = %s with an unreadable store, want no block", block)
	}
	if st := loadReportState(statePath); !reflect.DeepEqual(st.Brake, map[string]string{"db": refusedID}) {
		t.Fatalf("state brake with an unreadable store = %v, want it kept", st.Brake)
	}

	// 3) The credential is set anew: its brake is done, though the probe is not due yet.
	if err := os.Remove(credPath); err != nil {
		t.Fatal(err)
	}
	if err := credentials.Set(context.Background(), credPath, "db", "pw2"); err != nil {
		t.Fatal(err)
	}
	got, err = push()
	if err != nil {
		t.Fatal(err)
	}
	if string(got["credentials"]) != `{"db":true}` || len(secrets) != 1 {
		t.Errorf("report credentials = %s after %d runs, want db and no new run", got["credentials"], len(secrets))
	}
	if st := loadReportState(statePath); st.Brake != nil {
		t.Fatalf("state brake after the credential was set anew = %v, want none", st.Brake)
	}
}

// planLogProbe is a plan with one probe of the counting sensor log.
const planLogProbe = `{"plan_version": 1, "catalog_version": "c1", "scan": false, "discovery": {"markers": []},
	"probes": [{"id": "chk-log", "sensor": "log", "interval_s": 600, "timeout_s": 5, "target": null,
	"params": {}, "fields": ["count"], "credential": null}]}`

func TestACountingProbesCursorOutlivesALostPushAndEndsWithItsProbe(t *testing.T) {
	stubReportHost(t)
	shortenRetryDelay(t)
	stubCPU(t)
	t.Setenv("ADMINHELPER_MONITOR_DIR", t.TempDir())
	var got []string
	stubRunProbe(t, func(_ context.Context, p probe.Probe, start time.Time, acc *probe.Access) probe.Result {
		// As probe.Run does for a counting sensor: the run gets the cursor the last one left and leaves its own.
		got = append(got, acc.Cursors[p.ID])
		if acc.Cursors == nil {
			acc.Cursors = map[string]string{}
		}
		acc.Cursors[p.ID] = fmt.Sprintf("c%d", len(got))
		return probe.Result{TS: start.Unix(), Status: probe.StatusOK, Values: map[string]any{"count": 0}}
	})

	var plan atomic.Value
	plan.Store(planLogProbe)
	var reportStatus atomic.Int32
	reportStatus.Store(http.StatusBadGateway)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodGet {
			_, _ = w.Write([]byte(plan.Load().(string)))
			return
		}
		w.WriteHeader(int(reportStatus.Load()))
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
	if err := saveReportState(statePath, reportState{Cursors: map[string]string{"chk-log": "c0", "gone": "c9"}}); err != nil {
		t.Fatal(err)
	}

	// 1) The push is lost: the probe counted from its stored cursor, and the cursor its run left stays
	// with its result. The cursor of a probe the plan no longer holds is done.
	if err := Push(context.Background()); err == nil {
		t.Fatal("push against 502: want an error")
	}
	if !reflect.DeepEqual(got, []string{"c0"}) {
		t.Fatalf("the probe ran from the cursors %q, want once from the stored c0", got)
	}
	st := loadReportState(statePath)
	if !reflect.DeepEqual(st.Cursors, map[string]string{"chk-log": "c1"}) {
		t.Fatalf("state cursors after a lost push = %v, want chk-log at c1 alone", st.Cursors)
	}
	if _, ok := st.Probes["chk-log"]; !ok {
		t.Fatalf("state probes after a lost push = %v, want the result the cursor goes with", st.Probes)
	}

	// 2) The probe measures with a sensor that does not count now: its cursor is done.
	plan.Store(strings.Replace(planLogProbe, `"sensor": "log"`, `"sensor": "fake"`, 1))
	reportStatus.Store(http.StatusOK)
	if err := Push(context.Background()); err != nil {
		t.Fatal(err)
	}
	if st := loadReportState(statePath); st.Cursors != nil {
		t.Fatalf("state cursors of a probe that no longer counts = %v, want none", st.Cursors)
	}
}
