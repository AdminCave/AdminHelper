// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package frpc

import (
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"

	"adminhelper-agent/internal/config"
)

// setupSyncTest points FrpDir/MonitorDir at temp dirs, writes an adminhelper.conf targeting srvURL,
// and stubs the frpc restart. Returns a pointer to the restart counter.
func setupSyncTest(t *testing.T, srvURL string) *int {
	t.Helper()
	t.Setenv("ADMINHELPER_FRP_DIR", t.TempDir())
	t.Setenv("ADMINHELPER_MONITOR_DIR", t.TempDir()) // no PKI here -> legacy client
	conf := "ADMINHELPER_URL=" + srvURL + "\nAPI_KEY=k\nSERVER_ID=s\nINSECURE=1\n"
	if err := os.WriteFile(config.FrpAdminHelperConf(), []byte(conf), 0600); err != nil {
		t.Fatal(err)
	}
	restarts := 0
	orig := restartService
	restartService = func() error { restarts++; return nil }
	t.Cleanup(func() { restartService = orig })
	return &restarts
}

func TestSyncWritesConfigOnHashMismatch(t *testing.T) {
	toml := []byte("serverAddr = \"1.2.3.4\"\nserverPort = 7000\n") // no identity paths -> rewrite is a no-op
	hash := hashConfig(toml)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case strings.HasSuffix(r.URL.Path, "/config-hash"):
			_, _ = w.Write([]byte(`{"hash":"` + hash + `"}`))
		case strings.HasSuffix(r.URL.Path, "/config"):
			_, _ = w.Write(toml)
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	defer srv.Close()
	restarts := setupSyncTest(t, srv.URL)

	if err := Sync(); err != nil {
		t.Fatalf("Sync: %v", err)
	}
	if got, _ := os.ReadFile(config.FrpConfigFile()); string(got) != string(toml) {
		t.Errorf("frpc.toml = %q, want %q", got, toml)
	}
	if got, _ := os.ReadFile(config.FrpHashFile()); strings.TrimSpace(string(got)) != hash {
		t.Errorf("hash file = %q, want %q", got, hash)
	}
	if *restarts != 1 {
		t.Errorf("restarts = %d, want 1", *restarts)
	}
}

func TestSyncNoOpOnIdenticalHash(t *testing.T) {
	hash := hashConfig([]byte("x"))
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasSuffix(r.URL.Path, "/config-hash") {
			_, _ = w.Write([]byte(`{"hash":"` + hash + `"}`))
			return
		}
		t.Errorf("config endpoint must not be hit on identical hash: %s", r.URL.Path)
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer srv.Close()
	restarts := setupSyncTest(t, srv.URL)
	// Local hash already matches remote -> no fetch/write/restart.
	if err := os.WriteFile(config.FrpHashFile(), []byte(hash), 0644); err != nil {
		t.Fatal(err)
	}

	if err := Sync(); err != nil {
		t.Fatalf("Sync: %v", err)
	}
	if _, err := os.Stat(config.FrpConfigFile()); !os.IsNotExist(err) {
		t.Error("frpc.toml should not be written on identical hash")
	}
	if *restarts != 0 {
		t.Errorf("restarts = %d, want 0", *restarts)
	}
}

func TestSyncErrorsOnHashEndpoint500(t *testing.T) {
	// A persistently broken sync (rotated key, expired cert) must surface as an error, not silently
	// skip — a lasting silent skip would freeze every agent's tunnels (the 4.9 hardening).
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer srv.Close()
	restarts := setupSyncTest(t, srv.URL)

	if err := Sync(); err == nil {
		t.Error("Sync must error on a failing hash endpoint, not skip silently")
	}
	if *restarts != 0 {
		t.Errorf("restarts = %d, want 0", *restarts)
	}
}

func TestSyncErrorsOnConfigEndpoint500LeavesOldConfig(t *testing.T) {
	hash := hashConfig([]byte("new-content"))
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasSuffix(r.URL.Path, "/config-hash") {
			_, _ = w.Write([]byte(`{"hash":"` + hash + `"}`))
			return
		}
		w.WriteHeader(http.StatusInternalServerError) // config endpoint fails
	}))
	defer srv.Close()
	restarts := setupSyncTest(t, srv.URL)
	if err := os.WriteFile(config.FrpConfigFile(), []byte("OLD"), 0600); err != nil {
		t.Fatal(err)
	}

	if err := Sync(); err == nil {
		t.Error("Sync must error when the config endpoint fails")
	}
	if got, _ := os.ReadFile(config.FrpConfigFile()); string(got) != "OLD" {
		t.Errorf("frpc.toml = %q, want it untouched (OLD)", got)
	}
	if *restarts != 0 {
		t.Errorf("restarts = %d, want 0", *restarts)
	}
}
