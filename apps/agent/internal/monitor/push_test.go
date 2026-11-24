// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The end-to-end tests of package push: they drive Init and Push from outside, beside the
// collector stubs of package monitor (export_test.go).
package monitor_test

import (
	"bytes"
	"context"
	"encoding/pem"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"adminhelper-agent/internal/config"
	"adminhelper-agent/internal/monitor"
	"adminhelper-agent/internal/monitor/push"
	"adminhelper-agent/internal/monitor/send"
)

// shortenRetryDelay shrinks the push retry backoff for the test duration.
func shortenRetryDelay(t *testing.T) {
	t.Helper()
	orig := send.RetryDelay
	send.RetryDelay = time.Millisecond
	t.Cleanup(func() { send.RetryDelay = orig })
}

func TestPushBudgetKeepsThePushReserve(t *testing.T) {
	monitor.StubReportHost(t)
	t.Setenv("ADMINHELPER_MONITOR_DIR", t.TempDir())
	oldReserve := push.Reserve
	push.Reserve = 300 * time.Millisecond
	t.Cleanup(func() { push.Reserve = oldReserve })
	// A collector that hangs until its context ends: only the collection deadline
	// push.Reserve before the run's deadline leaves the push its time.
	monitor.StubDockerCollector(func(ctx context.Context) *monitor.DockerBlock {
		<-ctx.Done()
		return nil
	})

	received := make(chan time.Time, 2)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Only the report counts: the plan GET comes before the collection.
		if r.Method == http.MethodPost {
			received <- time.Now()
		}
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
	if err := push.Push(ctx); err != nil {
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

// Push end to end: over TLS against the pinned CACERT of monitor.conf, a lost push leaves the CPU
// window as the last push left it, and the next push that goes through moves it.
func TestPushKeepsTheStateThroughALostPush(t *testing.T) {
	monitor.StubReportHost(t)
	shortenRetryDelay(t)
	setCPU := monitor.StubCPU(t)
	t.Setenv("ADMINHELPER_MONITOR_DIR", t.TempDir())
	var status, posts atomic.Int32
	status.Store(http.StatusOK)
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodGet {
			w.WriteHeader(http.StatusNotFound)
			return
		}
		posts.Add(1)
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

	setCPU(200, 800)
	if err := push.Push(context.Background()); err != nil || posts.Load() != 1 {
		t.Fatalf("first push: err %v after %d posts, want one report through the pinned CA", err, posts.Load())
	}
	if st := monitor.LoadReportState(statePath).CPU; st == nil || st.Total != 1000 {
		t.Fatalf("state cpu after the first push = %+v, want total 1000", st)
	}

	status.Store(http.StatusBadGateway)
	setCPU(300, 1100)
	if err := push.Push(context.Background()); err == nil {
		t.Fatal("push against 502: want an error")
	}
	if st := monitor.LoadReportState(statePath).CPU; st == nil || st.Total != 1000 {
		t.Fatalf("state cpu after a lost push = %+v, want it as the first push left it", st)
	}

	status.Store(http.StatusOK)
	setCPU(600, 1800)
	if err := push.Push(context.Background()); err != nil {
		t.Fatal(err)
	}
	if st := monitor.LoadReportState(statePath).CPU; st == nil || st.Total != 2400 {
		t.Fatalf("state cpu after the next push = %+v, want total 2400", st)
	}
}

// initTrustEnv points Init at an empty monitor dir, stubs the report collectors and shortens
// the push backoff.
func initTrustEnv(t *testing.T) {
	t.Helper()
	t.Setenv("ADMINHELPER_MONITOR_DIR", t.TempDir())
	monitor.StubReportHost(t)
	shortenRetryDelay(t)
}

// assertNothingStored fails for a monitor.conf or ca.crt that a refused Init left behind.
func assertNothingStored(t *testing.T) {
	t.Helper()
	for _, f := range []string{config.MonitorConfFile(), config.MonitorCACert()} {
		if _, err := os.Stat(f); !errors.Is(err, os.ErrNotExist) {
			t.Errorf("%s exists after the refused call (stat: %v)", f, err)
		}
	}
}

func TestMonitorInitTrustRefusesCACertWithInsecure(t *testing.T) {
	initTrustEnv(t)
	cacert := filepath.Join(t.TempDir(), "ca.pem")
	if err := os.WriteFile(cacert, []byte("-----BEGIN CERTIFICATE-----\nY2E=\n-----END CERTIFICATE-----\n"), 0o600); err != nil {
		t.Fatal(err)
	}

	err := push.Init(push.InitParams{URL: "https://127.0.0.1:1", APIKey: "key", ServerID: "srv-1",
		TLS: config.TLSOpts{CACert: cacert, Insecure: true}})
	if err == nil || !strings.Contains(err.Error(), "--cacert") || !strings.Contains(err.Error(), "--insecure") {
		t.Errorf("Init = %v, want an error naming --cacert and --insecure", err)
	}
	assertNothingStored(t)
}

func TestMonitorInitTrustBlindInsecureWithoutACertificateFails(t *testing.T) {
	initTrustEnv(t)

	// A closed port: there is no certificate to pin.
	err := push.Init(push.InitParams{URL: "https://127.0.0.1:1", APIKey: "key", ServerID: "srv-1",
		TLS: config.TLSOpts{Insecure: true}})
	if err == nil {
		t.Error("Init with a blind --insecure and no certificate to pin succeeded, want an error")
	}
	assertNothingStored(t)
}

// The counterpart of the failing blind --insecure: with a certificate to pin, Init stores it
// as the trust and never INSECURE, and the test push already verifies against the pin.
func TestMonitorInitTrustBlindInsecurePinsThePresentedCertificate(t *testing.T) {
	var pushes atomic.Int32
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/agent/srv-1/report" {
			pushes.Add(1)
		}
	}))
	defer srv.Close()
	initTrustEnv(t)

	if err := push.Init(push.InitParams{URL: srv.URL, APIKey: "key", ServerID: "srv-1",
		TLS: config.TLSOpts{Insecure: true}}); err != nil {
		t.Fatalf("Init: %v", err)
	}
	kv, err := config.LoadKeyValue(config.MonitorConfFile())
	if err != nil {
		t.Fatal(err)
	}
	if kv["CACERT"] != config.MonitorCACert() {
		t.Errorf("CACERT = %q, want the pinned %q", kv["CACERT"], config.MonitorCACert())
	}
	if v, ok := kv["INSECURE"]; ok {
		t.Errorf("monitor.conf stores INSECURE=%q, want no INSECURE", v)
	}
	pinned, err := os.ReadFile(config.MonitorCACert())
	if err != nil {
		t.Fatal(err)
	}
	if want := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: srv.Certificate().Raw}); !bytes.Equal(pinned, want) {
		t.Errorf("pinned ca.crt = %q, want the presented certificate", pinned)
	}
	if n := pushes.Load(); n == 0 {
		t.Error("no test push reached the server, want one verified against the pin")
	}
}
