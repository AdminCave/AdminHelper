// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"bytes"
	"encoding/pem"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"

	"adminhelper-agent/internal/config"
)

// The blind --insecure init pins the presented server cert (TOFU) instead of
// persisting INSECURE=1 (3.2), so fetchServerCertPEM must return exactly the
// chain the server presented — otherwise the pin would trust the wrong cert.
func TestFetchServerCertPEMCapturesPresentedChain(t *testing.T) {
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {}))
	defer srv.Close()

	pemBytes, err := fetchServerCertPEM(srv.URL)
	if err != nil {
		t.Fatalf("fetchServerCertPEM: %v", err)
	}
	block, _ := pem.Decode(pemBytes)
	if block == nil {
		t.Fatal("no PEM block captured")
	}
	if !bytes.Equal(block.Bytes, srv.Certificate().Raw) {
		t.Fatal("captured cert does not match the server's presented cert")
	}
}

func TestFetchServerCertPEMUnreachable(t *testing.T) {
	// A closed port must surface an error, not a silent empty pin.
	if _, err := fetchServerCertPEM("https://127.0.0.1:1"); err == nil {
		t.Fatal("expected an error for an unreachable host")
	}
}

// initTrustEnv points Init at an empty monitor dir, stubs the report collectors, shortens
// the push backoff and puts timer in place of the service activation (systemctl on Linux).
func initTrustEnv(t *testing.T, timer func() error) {
	t.Helper()
	t.Setenv("ADMINHELPER_MONITOR_DIR", t.TempDir())
	stubReportHost(t)
	shortenRetryDelay(t)
	orig := enableTimer
	enableTimer = timer
	t.Cleanup(func() { enableTimer = orig })
}

// timerMustNotRun is the service activation of an Init call that has to stop earlier.
func timerMustNotRun(t *testing.T) func() error {
	return func() error {
		t.Error("Init activated the monitor service, want it to stop before")
		return nil
	}
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
	initTrustEnv(t, timerMustNotRun(t))
	cacert := filepath.Join(t.TempDir(), "ca.pem")
	if err := os.WriteFile(cacert, []byte("-----BEGIN CERTIFICATE-----\nY2E=\n-----END CERTIFICATE-----\n"), 0o600); err != nil {
		t.Fatal(err)
	}

	err := Init(InitParams{URL: "https://127.0.0.1:1", APIKey: "key", ServerID: "srv-1",
		TLS: config.TLSOpts{CACert: cacert, Insecure: true}})
	if err == nil || !strings.Contains(err.Error(), "--cacert") || !strings.Contains(err.Error(), "--insecure") {
		t.Errorf("Init = %v, want an error naming --cacert and --insecure", err)
	}
	assertNothingStored(t)
}

func TestMonitorInitTrustBlindInsecureWithoutACertificateFails(t *testing.T) {
	initTrustEnv(t, timerMustNotRun(t))

	// A closed port: there is no certificate to pin.
	err := Init(InitParams{URL: "https://127.0.0.1:1", APIKey: "key", ServerID: "srv-1",
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
	var enabled int
	initTrustEnv(t, func() error { enabled++; return nil })

	if err := Init(InitParams{URL: srv.URL, APIKey: "key", ServerID: "srv-1",
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
	if enabled != 1 {
		t.Errorf("monitor service activated %d times, want 1", enabled)
	}
}
