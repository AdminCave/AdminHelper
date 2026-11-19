// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package monitor

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os/exec"
	"reflect"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"adminhelper-agent/internal/allowlist"
	"adminhelper-agent/internal/config"
)

// stubFailedUnits makes the systemd block report units as failed, each with its since from since
// ("" leaves it out of failed_details); details false sends no failed_details at all.
func stubFailedUnits(t *testing.T, failed *[]string, since map[string]string, details *bool) {
	t.Helper()
	serviceHealthCollector = func(context.Context) map[string]any {
		health := map[string]any{"failed": append([]string{}, *failed...)}
		if *details {
			d := []map[string]string{}
			for _, unit := range *failed {
				entry := map[string]string{"unit": unit}
				if since[unit] != "" {
					entry["since"] = since[unit]
				}
				d = append(d, entry)
			}
			health["failed_details"] = d
		}
		return health
	}
}

// stubServiceLogReader counts the units read; a unit in broken fails.
func stubServiceLogReader(t *testing.T, broken map[string]bool) *[]string {
	t.Helper()
	old := serviceLogReader
	t.Cleanup(func() { serviceLogReader = old })
	var read []string
	serviceLogReader = func() func(context.Context, string) ([]string, bool) {
		return func(_ context.Context, unit string) ([]string, bool) {
			read = append(read, unit)
			if broken[unit] {
				return nil, false
			}
			return []string{"error of " + unit}, true
		}
	}
	return &read
}

func failedLogs(t *testing.T, report map[string]any) map[string]any {
	t.Helper()
	svc, _ := report["systemd"].(map[string]any)
	logs, _ := svc["failed_logs"].(map[string]any)
	return logs
}

func TestBuildReportSendsTheErrorLinesOncePerFailure(t *testing.T) {
	stubReportHost(t)
	failed := []string{"a.service", "b.service"}
	since := map[string]string{"a.service": "2026-11-19T04:00:00Z", "b.service": "2026-11-19T04:01:00Z"}
	details := true
	stubFailedUnits(t, &failed, since, &details)
	read := stubServiceLogReader(t, nil)
	work := &probeWork{serviceLogs: true}
	var state reportState
	run := func() map[string]any {
		t.Helper()
		*read = nil
		var report map[string]any
		report, state = buildReportWithState(context.Background(), nil, work, state, time.Now())
		return report
	}

	// First run: both failures go out with their since, oldest line first.
	logs := failedLogs(t, run())
	want := map[string]any{
		"a.service": map[string]any{"since": since["a.service"], "lines": []string{"error of a.service"}},
		"b.service": map[string]any{"since": since["b.service"], "lines": []string{"error of b.service"}},
	}
	if !reflect.DeepEqual(logs, want) {
		t.Fatalf("failed_logs = %#v, want %#v", logs, want)
	}
	if st, ok := selfStats(t, run())[serviceLogsCollector]; !ok || st.Throttled {
		t.Errorf("service_logs stat = %+v (%v), want a run", st, ok)
	}

	// The failed units are the ones with lines: the block names no log_units (a Windows block does).
	if svc, _ := run()["systemd"].(map[string]any); svc["log_units"] != nil {
		t.Errorf("log_units = %#v, want none on Linux", svc["log_units"])
	}

	// Same failures: nothing read, nothing sent.
	if logs := failedLogs(t, run()); logs != nil || len(*read) != 0 {
		t.Fatalf("same failures: failed_logs %#v, read %v; want none", logs, *read)
	}

	// a fails anew (another since): only a goes out again.
	since["a.service"] = "2026-11-19T05:00:00Z"
	if logs := failedLogs(t, run()); len(logs) != 1 || logs["a.service"] == nil || !reflect.DeepEqual(*read, []string{"a.service"}) {
		t.Fatalf("a failed anew: failed_logs %#v, read %v; want a only", logs, *read)
	}

	// b recovers and fails again with the same since: its lines go out again.
	failed = []string{"a.service"}
	run()
	failed = []string{"a.service", "b.service"}
	if logs := failedLogs(t, run()); len(logs) != 1 || logs["b.service"] == nil {
		t.Fatalf("b failed again: failed_logs %#v, want b only", logs)
	}

	// A run without failed_details (the detail query failed) sends nothing twice, and nothing
	// when the details come back.
	details = false
	if logs := failedLogs(t, run()); logs != nil {
		t.Fatalf("without details: failed_logs %#v, want none", logs)
	}
	details = true
	if logs := failedLogs(t, run()); logs != nil {
		t.Fatalf("details back: failed_logs %#v, want none", logs)
	}
	if !reflect.DeepEqual(state.ServiceLogs, map[string]string{"a.service": since["a.service"], "b.service": since["b.service"]}) {
		t.Errorf("state = %v, want both failures with their since", state.ServiceLogs)
	}
}

// The plan's switch reaches the pushed report, and a lost push sends the lines again.
func TestPushSendsTheErrorLinesThePlanAsksForAndAgainAfterALostPush(t *testing.T) {
	stubReportHost(t)
	shortenRetryDelay(t)
	s := stubCPU(t)
	t.Setenv("ADMINHELPER_MONITOR_DIR", t.TempDir())
	failed := []string{"a.service"}
	details := true
	stubFailedUnits(t, &failed, map[string]string{"a.service": "2026-11-19T04:00:00Z"}, &details)
	stubServiceLogReader(t, nil)

	const plan = `{"plan_version": 1, "catalog_version": "c1", "scan": false, "discovery": {"markers": []},
	"probes": [], "service_logs": true}`
	var reportStatus atomic.Int32
	type sent struct {
		Systemd struct {
			FailedLogs map[string]struct {
				Since string   `json:"since"`
				Lines []string `json:"lines"`
			} `json:"failed_logs"`
		} `json:"systemd"`
	}
	received := make(chan sent, 8)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodGet {
			_, _ = w.Write([]byte(plan))
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
	busy := 100.0
	push := func(status int) (sent, error) {
		t.Helper()
		reportStatus.Store(int32(status))
		busy += 100
		s.times = cpuTimes(busy, busy*4)
		err := Push(context.Background())
		var last sent
		for len(received) > 0 {
			last = <-received
		}
		return last, err
	}

	got, err := push(http.StatusBadGateway)
	if err == nil {
		t.Fatal("push against 502: want an error")
	}
	if l := got.Systemd.FailedLogs["a.service"]; l.Since != "2026-11-19T04:00:00Z" || !reflect.DeepEqual(l.Lines, []string{"error of a.service"}) {
		t.Fatalf("lost push: failed_logs %+v, want a.service with its lines", got.Systemd.FailedLogs)
	}
	got, err = push(http.StatusOK)
	if err != nil || got.Systemd.FailedLogs["a.service"].Lines == nil {
		t.Fatalf("push after the lost one: err %v, failed_logs %+v; want a.service again", err, got.Systemd.FailedLogs)
	}
	got, err = push(http.StatusOK)
	if err != nil || got.Systemd.FailedLogs != nil {
		t.Fatalf("push after a delivered one: err %v, failed_logs %+v; want none", err, got.Systemd.FailedLogs)
	}
}

func TestBuildReportSendsNoErrorLinesWithoutThePlanAskingForThem(t *testing.T) {
	stubReportHost(t)
	failed := []string{"a.service"}
	details := true
	stubFailedUnits(t, &failed, map[string]string{"a.service": "2026-11-19T04:00:00Z"}, &details)
	read := stubServiceLogReader(t, nil)
	due := throttle{Factor: 2, Skipped: 1}
	prev := reportState{
		ServiceLogs: map[string]string{"a.service": "2026-11-19T04:00:00Z"},
		Throttle:    map[string]throttle{serviceLogsCollector: due},
	}

	for _, work := range []*probeWork{nil, {}} {
		report, next := buildReportWithState(context.Background(), nil, work, prev, time.Now())
		if logs := failedLogs(t, report); logs != nil || len(*read) != 0 {
			t.Fatalf("work %+v: failed_logs %#v, read %v; want none", work, logs, *read)
		}
		// The switch off forgets what went out, so the lines go out anew once it is on again.
		if next.ServiceLogs != nil {
			t.Errorf("work %+v: state %v, want it empty", work, next.ServiceLogs)
		}
		if _, ok := selfStats(t, report)[serviceLogsCollector]; ok {
			t.Errorf("work %+v: a service_logs stat, want none", work)
		}
		if next.Throttle[serviceLogsCollector] != due {
			t.Errorf("work %+v: throttle %+v, want %+v kept", work, next.Throttle[serviceLogsCollector], due)
		}
	}
}

func TestBuildReportReadsNoErrorLinesUnderLoadOrThrottle(t *testing.T) {
	stubReportHost(t)
	failed := []string{"a.service", "b.service"}
	details := true
	stubFailedUnits(t, &failed, map[string]string{"a.service": "s1", "b.service": "s2"}, &details)
	read := stubServiceLogReader(t, nil)
	work := &probeWork{serviceLogs: true}
	// a went out before, c ended since.
	sent := map[string]string{"a.service": "s1", "c.service": "s3"}

	// Shed under load: nothing read, the failure that ended is forgotten all the same.
	readLoad = func(map[string]any, *cpuSample, *cpuSample) loadReading {
		return loadReading{LoadPerCPU: ptr(3), MemAvailable: ptr(50)}
	}
	prev := reportState{ServiceLogs: sent, LoadShed: loadShed{Active: true, Since: time.Now().Add(-time.Hour).Unix()}}
	report, next := buildReportWithState(context.Background(), nil, work, prev, time.Now())
	if logs := failedLogs(t, report); logs != nil || len(*read) != 0 {
		t.Fatalf("shed: failed_logs %#v, read %v; want none", logs, *read)
	}
	if !reflect.DeepEqual(next.ServiceLogs, map[string]string{"a.service": "s1"}) {
		t.Errorf("shed: state %v, want a only", next.ServiceLogs)
	}

	// Held back by its throttle: nothing read, b waits for a later run.
	readLoad = func(map[string]any, *cpuSample, *cpuSample) loadReading { return loadReading{} }
	prev = reportState{ServiceLogs: sent, Throttle: map[string]throttle{serviceLogsCollector: {Factor: 2}}}
	report, next = buildReportWithState(context.Background(), nil, work, prev, time.Now())
	if logs := failedLogs(t, report); logs != nil || len(*read) != 0 {
		t.Fatalf("throttled: failed_logs %#v, read %v; want none", logs, *read)
	}
	if st := selfStats(t, report)[serviceLogsCollector]; !st.Throttled || next.Throttle[serviceLogsCollector].Skipped != 1 {
		t.Errorf("stat %+v, throttle %+v: want it held back once", st, next.Throttle[serviceLogsCollector])
	}
}

func TestBuildReportSendsAtMostTwentyUnitsAndRetriesAFailedRead(t *testing.T) {
	stubReportHost(t)
	var failed []string
	for i := range 25 {
		failed = append(failed, fmt.Sprintf("u%02d.service", i))
	}
	details := true
	stubFailedUnits(t, &failed, map[string]string{}, &details)
	read := stubServiceLogReader(t, map[string]bool{"u03.service": true})
	work := &probeWork{serviceLogs: true}

	report, state := buildReportWithState(context.Background(), nil, work, reportState{}, time.Now())
	// u03 cannot be read: it does not count, so u20 makes the twentieth.
	if logs := failedLogs(t, report); len(logs) != maxLogUnits || logs["u03.service"] != nil || logs["u20.service"] == nil {
		t.Fatalf("first run: %d units (u03 %v, u20 %v), want 20 without u03", len(logs), logs["u03.service"], logs["u20.service"])
	}
	if len(*read) != 21 {
		t.Errorf("first run read %d units, want 21", len(*read))
	}

	*read = nil
	report, _ = buildReportWithState(context.Background(), nil, work, state, time.Now())
	want := []string{"u03.service", "u21.service", "u22.service", "u23.service", "u24.service"}
	if !reflect.DeepEqual(*read, want) || len(failedLogs(t, report)) != 4 {
		t.Fatalf("second run read %v (%d sent), want %v with u03 failing again", *read, len(failedLogs(t, report)), want)
	}
}

func TestReadServiceLogAsksTheJournalForTheUnitsLastTenEntries(t *testing.T) {
	old := journalCLI
	t.Cleanup(func() { journalCLI = old })
	journalCLI.lookPath = func(string) (string, error) { return "/usr/bin/journalctl", nil }
	var calls [][]string
	out := "first\n\nsecond\tline password=hunter2\n"
	journalCLI.run = func(_ context.Context, name string, args ...string) ([]byte, error) {
		calls = append(calls, append([]string{name}, args...))
		return []byte(out), nil
	}

	lines, ok := readServiceLog(context.Background(), "nginx.service")
	if !ok || !reflect.DeepEqual(lines, []string{"first", "second line password=[REDACTED]"}) {
		t.Fatalf("lines %q (%v), want two cleaned lines", lines, ok)
	}
	call := calls[0]
	if !reflect.DeepEqual(call, []string{"journalctl", "--no-pager", "--quiet", "--output=cat", "--unit=nginx.service", "--lines=10"}) {
		t.Fatalf("call %q", call)
	}
	if !allowlist.Allowed(call[0], call[1:]) {
		t.Errorf("the allowlist refuses %q", call)
	}

	// Outside the unit class no call goes out.
	calls = nil
	if _, ok := readServiceLog(context.Background(), "-a.service"); ok || len(calls) != 0 {
		t.Errorf("a name outside the unit class: ok %v, %d calls; want none", ok, len(calls))
	}

	// A failed call and a missing journalctl read nothing.
	journalCLI.run = func(context.Context, string, ...string) ([]byte, error) { return nil, errors.New("exit status 1") }
	if _, ok := readServiceLog(context.Background(), "nginx.service"); ok {
		t.Error("a failed call read lines")
	}
	journalCLI.lookPath = func(string) (string, error) { return "", exec.ErrNotFound }
	if _, ok := readServiceLog(context.Background(), "nginx.service"); ok {
		t.Error("without journalctl lines were read")
	}
}

func TestServiceLogLinesKeepsTheLastTenNonEmptyLines(t *testing.T) {
	var b strings.Builder
	for i := range 14 {
		fmt.Fprintf(&b, "line %d\n\n", i)
	}
	got := serviceLogLines([]byte(b.String()))
	if len(got) != maxLogLines || got[0] != "line 4" || got[9] != "line 13" {
		t.Fatalf("got %q", got)
	}
	if got := serviceLogLines(nil); got == nil || len(got) != 0 {
		t.Errorf("no output: %#v, want an empty list", got)
	}
}
