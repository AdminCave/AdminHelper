// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package push

import (
	"bytes"
	"encoding/pem"
	"net/http"
	"net/http/httptest"
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

// The re-provisioning watch-list preservation (6.15): a token rotation passes an empty services
// string and must NOT wipe the configured SERVICES list — a documented, previously error-prone edge.
func TestPreserveServicesKeepsWatchListOnRotation(t *testing.T) {
	t.Setenv("ADMINHELPER_MONITOR_DIR", t.TempDir())

	// A non-empty list is passed through unchanged.
	if got := preserveServices("nginx,redis"); got != "nginx,redis" {
		t.Fatalf("non-empty services should pass through, got %q", got)
	}

	// Seed the persisted config with a watch list, then a rotation with empty services keeps it.
	if err := config.WriteKeyValue(config.MonitorConfFile(), []config.KeyValue{
		{Key: "MONITOR_URL", Value: "https://x"},
		{Key: "API_KEY", Value: "k"},
		{Key: "SERVER_ID", Value: "srv"},
		{Key: "SERVICES", Value: "nginx,redis"},
	}); err != nil {
		t.Fatal(err)
	}
	if got := preserveServices(""); got != "nginx,redis" {
		t.Fatalf("empty services wiped the configured watch list: %q", got)
	}
}

func TestPreserveServicesEmptyWhenNoConfig(t *testing.T) {
	t.Setenv("ADMINHELPER_MONITOR_DIR", t.TempDir())
	// No persisted config -> empty stays empty (no crash, no spurious list).
	if got := preserveServices(""); got != "" {
		t.Fatalf("empty services with no config should stay empty, got %q", got)
	}
}
