// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"bytes"
	"context"
	"encoding/json"
	"encoding/pem"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"sync/atomic"
	"testing"
	"time"

	"github.com/shirou/gopsutil/v4/cpu"

	"adminhelper-agent/internal/config"
)

// sampledCPU is what the stubbed 1s sample reports, so a result tells the sample from an average.
const sampledCPU = 77.0

// cpuStub stands in for cpuCalls: times returns *times (an error while nil), the 1s sample returns
// sampledCPU and counts its calls.
type cpuStub struct {
	times   *cpu.TimesStat
	samples int
}

func stubCPU(t *testing.T) *cpuStub {
	t.Helper()
	s := &cpuStub{}
	old := cpuCalls
	cpuCalls.times = func(bool) ([]cpu.TimesStat, error) {
		if s.times == nil {
			return nil, errors.New("cpu times unreadable")
		}
		return []cpu.TimesStat{*s.times}, nil
	}
	cpuCalls.percent = func(time.Duration, bool) ([]float64, error) {
		s.samples++
		return []float64{sampledCPU}, nil
	}
	t.Cleanup(func() { cpuCalls = old })
	return s
}

// cpuTimes is a host's counters without guest time, so total and busy are the same on every OS.
func cpuTimes(busy, idle float64) *cpu.TimesStat {
	return &cpu.TimesStat{CPU: "cpu-total", User: busy, Idle: idle}
}

func TestReportStateCPUShare(t *testing.T) {
	prev := &cpuSample{Unix: 1_700_000_000, Total: 1000, Busy: 200}
	cases := []struct {
		name string
		cur  cpuSample
		want float64
	}{
		{"a quarter busy", cpuSample{Unix: prev.Unix + 300, Total: 1400, Busy: 300}, 25},
		{"idle window", cpuSample{Unix: prev.Unix + 300, Total: 1400, Busy: 200}, 0},
		{"busy counter went back: 0", cpuSample{Unix: prev.Unix + 300, Total: 1400, Busy: 150}, 0},
		{"busy grew more than the total: 100", cpuSample{Unix: prev.Unix + 300, Total: 1100, Busy: 400}, 100},
		{"exactly 15 min old", cpuSample{Unix: prev.Unix + 900, Total: 1400, Busy: 300}, 25},
	}
	for _, c := range cases {
		got, ok := cpuPercentSince(prev, c.cur)
		if !ok || got != c.want {
			t.Errorf("%s: cpuPercentSince = %v, %v; want %v, true", c.name, got, ok, c.want)
		}
	}
}

func TestReportStateCPUBusyTimes(t *testing.T) {
	ts := cpu.TimesStat{User: 40, Nice: 5, System: 10, Idle: 100, Iowait: 20, Irq: 2, Softirq: 3, Steal: 1,
		Guest: 8, GuestNice: 2}
	// gopsutil's getAllBusy leaves the guest times out of the total on Linux only.
	wantTotal := 191.0
	if runtime.GOOS == "linux" {
		wantTotal = 181
	}
	total, busy := cpuBusyTimes(ts)
	if total != wantTotal || busy != wantTotal-120 {
		t.Errorf("cpuBusyTimes = %v, %v; want %v, %v", total, busy, wantTotal, wantTotal-120)
	}
}

func TestReportStateCPUFallback(t *testing.T) {
	now := time.Unix(1_700_000_000, 0)
	corrupt := filepath.Join(t.TempDir(), ".report-state.json")
	if err := os.WriteFile(corrupt, []byte("{kaputt"), 0600); err != nil {
		t.Fatal(err)
	}
	cases := []struct {
		name string
		prev *cpuSample
	}{
		{"no state", nil},
		{"corrupt state file", loadReportState(corrupt).CPU},
		{"16 min old", &cpuSample{Unix: now.Add(-16 * time.Minute).Unix(), Total: 1000, Busy: 200}},
		{"from the future", &cpuSample{Unix: now.Add(time.Minute).Unix(), Total: 1000, Busy: 200}},
		{"smaller total (reboot)", &cpuSample{Unix: now.Add(-5 * time.Minute).Unix(), Total: 5000, Busy: 900}},
		{"unchanged total", &cpuSample{Unix: now.Add(-5 * time.Minute).Unix(), Total: 1400, Busy: 200}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			s := stubCPU(t)
			s.times = cpuTimes(300, 1100)
			got, next := collectCPUSince(c.prev, now)
			if got != sampledCPU || s.samples != 1 {
				t.Errorf("cpu = %v after %d samples, want the 1s sample %v", got, s.samples, sampledCPU)
			}
			// The fallback still saves the current times, so the next run can average again.
			want := cpuSample{Unix: now.Unix(), Total: 1400, Busy: 300}
			if next == nil || *next != want {
				t.Errorf("next sample = %+v, want %+v", next, want)
			}
		})
	}
}

func TestReportStateCPUAverage(t *testing.T) {
	now := time.Unix(1_700_000_000, 0)
	s := stubCPU(t)
	s.times = cpuTimes(300, 1100)
	got, next := collectCPUSince(&cpuSample{Unix: now.Add(-5 * time.Minute).Unix(), Total: 1000, Busy: 200}, now)
	if got != 25 || s.samples != 0 {
		t.Errorf("cpu = %v after %d samples, want the average 25 without a sample", got, s.samples)
	}
	if want := (cpuSample{Unix: now.Unix(), Total: 1400, Busy: 300}); next == nil || *next != want {
		t.Errorf("next sample = %+v, want %+v", next, want)
	}
}

func TestReportStateCPUTimesUnreadable(t *testing.T) {
	now := time.Unix(1_700_000_000, 0)
	s := stubCPU(t)
	got, next := collectCPUSince(&cpuSample{Unix: now.Add(-5 * time.Minute).Unix(), Total: 1000, Busy: 200}, now)
	if got != sampledCPU || s.samples != 1 {
		t.Errorf("cpu = %v after %d samples, want the 1s sample %v", got, s.samples, sampledCPU)
	}
	if next != nil {
		t.Errorf("next sample = %+v, want none without CPU times", next)
	}
}

func TestReportStateRoundtrip(t *testing.T) {
	path := filepath.Join(t.TempDir(), ".report-state.json")
	if st := loadReportState(path); st.CPU != nil {
		t.Errorf("missing file: want the empty state, got %+v", st.CPU)
	}

	want := cpuSample{Unix: 1_700_000_000, Total: 1234.5, Busy: 321.25}
	if err := saveReportState(path, reportState{CPU: &want}); err != nil {
		t.Fatalf("saveReportState: %v", err)
	}
	if got := loadReportState(path); got.CPU == nil || *got.CPU != want {
		t.Errorf("roundtrip: got %+v, want %+v", got.CPU, want)
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if got := string(data); got != `{"cpu":{"unix":1700000000,"total":1234.5,"busy":321.25}}` {
		t.Errorf("file = %s, want the documented form", got)
	}
	// The state is the agent's own; nobody else needs to read it (POSIX only).
	if runtime.GOOS != "windows" {
		info, err := os.Stat(path)
		if err != nil {
			t.Fatal(err)
		}
		if perm := info.Mode().Perm(); perm != 0600 {
			t.Errorf("perm = %o, want 600", perm)
		}
	}

	if err := os.WriteFile(path, []byte("{kaputt"), 0600); err != nil {
		t.Fatal(err)
	}
	if st := loadReportState(path); st.CPU != nil {
		t.Errorf("corrupt file: want the empty state, got %+v", st.CPU)
	}
}

func TestReportStateOOMKillSource(t *testing.T) {
	// The state keeps where the OOM counter came from; a file from before the source was saved holds a
	// /proc/vmstat counter.
	path := filepath.Join(t.TempDir(), ".report-state.json")
	count := uint64(3)
	if err := saveReportState(path, reportState{OOMKill: &count, OOMKillSource: oomSourceCgroup}); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if got := string(data); got != `{"oom_kill":3,"oom_kill_source":"cgroup"}` {
		t.Errorf("file = %s, want the documented form", got)
	}
	if st := loadReportState(path); st.OOMKill == nil || *st.OOMKill != 3 || st.oomKillSource() != oomSourceCgroup {
		t.Errorf("roundtrip: oom_kill %v from %q, want 3 from %q", st.OOMKill, st.oomKillSource(), oomSourceCgroup)
	}

	if err := os.WriteFile(path, []byte(`{"oom_kill":5}`), 0600); err != nil {
		t.Fatal(err)
	}
	if st := loadReportState(path); st.OOMKill == nil || *st.OOMKill != 5 || st.oomKillSource() != oomSourceVMStat {
		t.Errorf("file without a source: oom_kill %v from %q, want 5 from %q", st.OOMKill, st.oomKillSource(),
			oomSourceVMStat)
	}
}

func TestReportStateNotUsedByBuildReport(t *testing.T) {
	// monitor init's test push builds its report with BuildReport: the 1s sample, even with a usable
	// state on disk, and the state stays as it was.
	stubReportHost(t)
	t.Setenv("ADMINHELPER_MONITOR_DIR", t.TempDir())
	path := config.MonitorReportStateFile()
	if err := saveReportState(path, reportState{CPU: &cpuSample{Unix: time.Now().Unix(), Total: 1000, Busy: 200}}); err != nil {
		t.Fatal(err)
	}
	before, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	s := stubCPU(t)
	s.times = cpuTimes(300, 1100)

	report := BuildReport(nil)
	if got := report["resources"].(map[string]any)["cpu_percent"]; got != sampledCPU || s.samples != 1 {
		t.Errorf("cpu_percent = %v after %d samples, want the 1s sample %v", got, s.samples, sampledCPU)
	}
	if after, _ := os.ReadFile(path); !bytes.Equal(after, before) {
		t.Errorf("state file changed to %s", after)
	}
}

func TestReportStatePushSavesOnlyAfterSuccess(t *testing.T) {
	stubReportHost(t)
	shortenRetryDelay(t)
	s := stubCPU(t)
	t.Setenv("ADMINHELPER_MONITOR_DIR", t.TempDir())

	var status atomic.Int32
	status.Store(http.StatusOK)
	received := make(chan float64, 8)
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Resources struct {
				CPUPercent float64 `json:"cpu_percent"`
			} `json:"resources"`
		}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Errorf("report body: %v", err)
		}
		received <- body.Resources.CPUPercent
		w.WriteHeader(int(status.Load()))
	}))
	defer srv.Close()
	caPath := config.MonitorCACert()
	if err := os.WriteFile(caPath, pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: srv.Certificate().Raw}), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := config.WriteKeyValue(config.MonitorConfFile(), []config.KeyValue{
		{Key: "MONITOR_URL", Value: srv.URL},
		{Key: "API_KEY", Value: "key"},
		{Key: "SERVER_ID", Value: "srv-1"},
		{Key: "CACERT", Value: caPath},
	}); err != nil {
		t.Fatal(err)
	}
	statePath := config.MonitorReportStateFile()

	// push runs one Push with the given CPU counters and returns the cpu_percent the server received
	// last and the error of Push.
	push := func(busy, idle float64) (float64, error) {
		t.Helper()
		s.times = cpuTimes(busy, idle)
		err := Push(context.Background())
		last := -1.0
		for len(received) > 0 {
			last = <-received
		}
		return last, err
	}
	savedCPU := func() *cpuSample {
		t.Helper()
		return loadReportState(statePath).CPU
	}

	// 1) No state yet: the 1s sample goes out and the counters are saved.
	before := time.Now().Unix()
	if got, err := push(200, 800); err != nil || got != sampledCPU {
		t.Fatalf("first push: err %v, cpu_percent %v; want the 1s sample %v", err, got, sampledCPU)
	}
	if st := savedCPU(); st == nil || st.Total != 1000 || st.Busy != 200 || st.Unix < before || st.Unix > time.Now().Unix() {
		t.Fatalf("state after the first push = %+v, want total 1000, busy 200 from now", st)
	}
	if runtime.GOOS != "windows" {
		if info, err := os.Stat(statePath); err != nil || info.Mode().Perm() != 0600 {
			t.Fatalf("state file: %v, %v; want mode 600", info, err)
		}
	}

	// 2) The next push averages since the saved counters, without a sample.
	if got, err := push(300, 1100); err != nil || got != 25 || s.samples != 1 {
		t.Fatalf("second push: err %v, cpu_percent %v after %d samples; want 25 from the state", err, got, s.samples)
	}
	if st := savedCPU(); st == nil || st.Total != 1400 || st.Busy != 300 {
		t.Fatalf("state after the second push = %+v, want total 1400, busy 300", st)
	}

	// 3) A lost push (both attempts fail) leaves the file as it was.
	saved, err := os.ReadFile(statePath)
	if err != nil {
		t.Fatal(err)
	}
	status.Store(http.StatusBadGateway)
	if _, err := push(900, 1500); err == nil {
		t.Fatal("push against 502: want an error")
	}
	if after, _ := os.ReadFile(statePath); !bytes.Equal(after, saved) {
		t.Fatalf("state file after a failed push = %s, want it unchanged %s", after, saved)
	}

	// 4) The next successful push measures since the last successful one: (600-300)/(2400-1400).
	status.Store(http.StatusOK)
	if got, err := push(600, 1800); err != nil || got != 30 {
		t.Fatalf("push after the failure: err %v, cpu_percent %v; want 30 since push 2", err, got)
	}
}
