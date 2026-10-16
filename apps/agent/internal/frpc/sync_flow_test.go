// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package frpc

import (
	"bytes"
	"errors"
	"log"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"runtime"
	"strings"
	"testing"

	"adminhelper-agent/internal/config"
)

// seamCalls counts the stubbed frpc service actions of a sync test. active is the stubbed
// frpc state, which the actions change the way systemctl would.
type seamCalls struct {
	restarts, disables, enables int
	active                      bool
}

// setupSyncTest points FrpDir/MonitorDir at temp dirs, writes an adminhelper.conf targeting srvURL,
// and stubs the frpc service actions, with frpc stopped. Returns their call counters.
func setupSyncTest(t *testing.T, srvURL string) *seamCalls {
	t.Helper()
	t.Setenv("ADMINHELPER_FRP_DIR", t.TempDir())
	t.Setenv("ADMINHELPER_MONITOR_DIR", t.TempDir()) // no PKI here -> legacy client
	pointSyncAt(t, srvURL)
	calls := &seamCalls{}
	origRestart, origDisable, origEnable, origActive := restartService, disableService, enableService, isActive
	restartService = func() error { calls.restarts++; calls.active = true; return nil }
	disableService = func() error { calls.disables++; calls.active = false; return nil }
	enableService = func() error { calls.enables++; calls.active = true; return nil }
	isActive = func() bool { return calls.active }
	t.Cleanup(func() {
		restartService, disableService, enableService, isActive = origRestart, origDisable, origEnable, origActive
	})
	return calls
}

// pointSyncAt writes the adminhelper.conf of a sync against srvURL.
func pointSyncAt(t *testing.T, srvURL string) {
	t.Helper()
	conf := "ADMINHELPER_URL=" + srvURL + "\nAPI_KEY=k\nSERVER_ID=s\nINSECURE=1\n"
	if err := os.WriteFile(config.FrpAdminHelperConf(), []byte(conf), 0600); err != nil {
		t.Fatal(err)
	}
}

// tunnelToml is a server-built frpc.toml with one tunnel. It has no identity paths, so the
// rewrite is a no-op; without a [[proxies]] line the sync would stop frpc.
var tunnelToml = []byte("serverAddr = \"1.2.3.4\"\nserverPort = 7000\n\n[[proxies]]\nname = \"ssh\"\n")

// A running frpc restarts onto the new file.
func TestSyncWritesConfigOnHashMismatch(t *testing.T) {
	hash := hashConfig(tunnelToml)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case strings.HasSuffix(r.URL.Path, "/config-hash"):
			_, _ = w.Write([]byte(`{"hash":"` + hash + `"}`))
		case strings.HasSuffix(r.URL.Path, "/config"):
			_, _ = w.Write(tunnelToml)
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	defer srv.Close()
	calls := setupSyncTest(t, srv.URL)
	calls.active = true

	if err := Sync(); err != nil {
		t.Fatalf("Sync: %v", err)
	}
	if got, _ := os.ReadFile(config.FrpConfigFile()); string(got) != localPreamble+string(tunnelToml) {
		t.Errorf("frpc.toml = %q, want %q", got, localPreamble+string(tunnelToml))
	}
	if got, _ := os.ReadFile(config.FrpHashFile()); strings.TrimSpace(string(got)) != hash {
		t.Errorf("hash file = %q, want %q", got, hash)
	}
	if calls.restarts != 1 || calls.enables != 0 || calls.disables != 0 {
		t.Errorf("restarts = %d, enables = %d, disables = %d, want 1, 0 and 0", calls.restarts, calls.enables, calls.disables)
	}
}

// R-0398: the first tunnel of a host finds frpc stopped. The sync enables it (it must also run
// after a reboot) instead of only starting it. The file is the server's text behind the local
// preamble, which keeps frpc retrying while frps is unreachable; the stored hash is the one of
// the server's text, so the next run with the same hash does nothing.
func TestSyncFirstTunnelEnablesFrpc(t *testing.T) {
	hash := hashConfig(tunnelToml)
	srv, fetches := hashServer(t, `{"hash":"`+hash+`"}`, tunnelToml)
	calls := setupSyncTest(t, srv.URL)

	if err := Sync(); err != nil {
		t.Fatalf("Sync with the first tunnel: %v", err)
	}
	if calls.enables != 1 || calls.restarts != 0 || calls.disables != 0 {
		t.Errorf("enables = %d, restarts = %d, disables = %d, want 1, 0 and 0", calls.enables, calls.restarts, calls.disables)
	}
	got, err := os.ReadFile(config.FrpConfigFile())
	if err != nil {
		t.Fatal(err)
	}
	rest, ok := bytes.CutPrefix(got, []byte("loginFailExit = false\n"))
	if !ok {
		t.Errorf("frpc.toml = %q, want it to start with the line loginFailExit = false", got)
	}
	if !bytes.Equal(rest, tunnelToml) {
		t.Errorf("frpc.toml after the first line = %q, want the server's text %q", rest, tunnelToml)
	}
	if runtime.GOOS != "windows" {
		if info, err := os.Stat(config.FrpConfigFile()); err != nil || info.Mode().Perm() != 0o600 {
			t.Errorf("frpc.toml stat = %v, %v, want mode 0600 (it holds the frps token)", info, err)
		}
	}
	if got, _ := os.ReadFile(config.FrpHashFile()); strings.TrimSpace(string(got)) != hash {
		t.Errorf("hash file = %q, want the hash of the server's text %q", got, hash)
	}

	if err := Sync(); err != nil {
		t.Fatalf("second Sync with the same hash: %v", err)
	}
	if calls.enables != 1 || calls.restarts != 0 || *fetches != 1 {
		t.Errorf("after the second run enables = %d, restarts = %d, config fetches = %d, want 1, 0 and 1",
			calls.enables, calls.restarts, *fetches)
	}
}

// R-0398: after a former run stopped and disabled frpc (last tunnel gone), a tunnel created
// later enables frpc again; a plain restart would start it without surviving a reboot.
func TestSyncTunnelAfterStopEnablesFrpc(t *testing.T) {
	empty := []byte("serverAddr = \"1.2.3.4\"\n")
	emptySrv, _ := hashServer(t, `{"hash":"`+hashConfig(empty)+`"}`, empty)
	calls := setupSyncTest(t, emptySrv.URL)
	writeFrpcState(t)
	calls.active = true
	if err := Sync(); err != nil {
		t.Fatalf("Sync without a tunnel: %v", err)
	}
	if calls.disables != 1 {
		t.Fatalf("disables = %d, want 1", calls.disables)
	}

	tunnelSrv, _ := hashServer(t, `{"hash":"`+hashConfig(tunnelToml)+`"}`, tunnelToml)
	pointSyncAt(t, tunnelSrv.URL)
	if err := Sync(); err != nil {
		t.Fatalf("Sync with the new tunnel: %v", err)
	}
	if calls.enables != 1 || calls.restarts != 0 {
		t.Errorf("enables = %d, restarts = %d, want 1 and 0", calls.enables, calls.restarts)
	}
}

// A failed start keeps the old hash, so the next run retries instead of taking the new
// config for applied.
func TestSyncKeepsOldHashWhenStartingFrpcFails(t *testing.T) {
	for name, active := range map[string]bool{"stopped frpc, enable fails": false, "running frpc, restart fails": true} {
		t.Run(name, func(t *testing.T) {
			srv, _ := hashServer(t, `{"hash":"`+hashConfig(tunnelToml)+`"}`, tunnelToml)
			calls := setupSyncTest(t, srv.URL)
			writeFrpcState(t)
			calls.active = active
			enableService = func() error { return errors.New("systemctl failed") }
			restartService = func() error { return errors.New("systemctl failed") }
			oldHash, _ := os.ReadFile(config.FrpHashFile())

			if err := Sync(); err == nil {
				t.Fatal("Sync must report the failed start")
			}
			if got, _ := os.ReadFile(config.FrpHashFile()); string(got) != string(oldHash) {
				t.Errorf("hash file = %q, want the old %q", got, oldHash)
			}
		})
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
	calls := setupSyncTest(t, srv.URL)
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
	if calls.restarts != 0 {
		t.Errorf("restarts = %d, want 0", calls.restarts)
	}
}

func TestSyncErrorsOnHashEndpoint500(t *testing.T) {
	// A persistently broken sync (rotated key, expired cert) must surface as an error, not silently
	// skip — a lasting silent skip would freeze every agent's tunnels (the 4.9 hardening).
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer srv.Close()
	calls := setupSyncTest(t, srv.URL)

	if err := Sync(); err == nil {
		t.Error("Sync must error on a failing hash endpoint, not skip silently")
	}
	if calls.restarts != 0 {
		t.Errorf("restarts = %d, want 0", calls.restarts)
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
	calls := setupSyncTest(t, srv.URL)
	if err := os.WriteFile(config.FrpConfigFile(), []byte("OLD"), 0600); err != nil {
		t.Fatal(err)
	}

	if err := Sync(); err == nil {
		t.Error("Sync must error when the config endpoint fails")
	}
	if got, _ := os.ReadFile(config.FrpConfigFile()); string(got) != "OLD" {
		t.Errorf("frpc.toml = %q, want it untouched (OLD)", got)
	}
	if calls.restarts != 0 {
		t.Errorf("restarts = %d, want 0", calls.restarts)
	}
}

// R-0398: a host provisioned without a tunnel before this version has no sync config and
// never gets a tunnel created later. The sync stays green and tells how to get one.
func TestSyncWithoutSyncConfigNamesReprovisioning(t *testing.T) {
	t.Setenv("ADMINHELPER_FRP_DIR", t.TempDir())
	var buf bytes.Buffer
	prev, prevOut, prevFlags := slog.Default(), log.Writer(), log.Flags()
	slog.SetDefault(slog.New(slog.NewTextHandler(&buf, nil)))
	// SetDefault also redirects the log package, which restoring the slog default does not undo.
	t.Cleanup(func() { slog.SetDefault(prev); log.SetOutput(prevOut); log.SetFlags(prevFlags) })

	if err := Sync(); err != nil {
		t.Fatalf("Sync without a sync config: %v", err)
	}
	out := buf.String()
	for _, want := range []string{"level=INFO", "adminhelper-agent provision"} {
		if !strings.Contains(out, want) {
			t.Errorf("log %q is missing %q", out, want)
		}
	}
}

// hashServer answers config-hash with hashJSON and config with toml, and counts the config fetches.
func hashServer(t *testing.T, hashJSON string, toml []byte) (*httptest.Server, *int) {
	t.Helper()
	fetches := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case strings.HasSuffix(r.URL.Path, "/config-hash"):
			_, _ = w.Write([]byte(hashJSON))
		case strings.HasSuffix(r.URL.Path, "/config") && toml != nil:
			fetches++
			_, _ = w.Write(toml)
		default:
			t.Errorf("unexpected request: %s", r.URL.Path)
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	t.Cleanup(srv.Close)
	return srv, &fetches
}

// writeFrpcState leaves the files of a host whose frpc ran with a tunnel before.
func writeFrpcState(t *testing.T) {
	t.Helper()
	old := []byte("auth.token = \"frps-token\"\n\n[[proxies]]\nname = \"ssh\"\n")
	if err := os.WriteFile(config.FrpConfigFile(), old, 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(config.FrpHashFile(), []byte(hashConfig(old)), 0644); err != nil {
		t.Fatal(err)
	}
}

// R-0398: without an FRP config the server answers config-hash with null. frpc must not run:
// the sync stops and disables it, removes frpc.toml (it holds the frps token) and the hash, and
// stays green. The next run finds nothing left and does not touch systemd again.
func TestSyncNullHashStopsFrpcAndRemovesItsFiles(t *testing.T) {
	srv, _ := hashServer(t, `{"hash": null}`, nil)
	calls := setupSyncTest(t, srv.URL)
	writeFrpcState(t)

	if err := Sync(); err != nil {
		t.Fatalf("Sync with a null hash: %v", err)
	}
	if calls.disables != 1 || calls.restarts != 0 {
		t.Errorf("disables = %d, restarts = %d, want 1 and 0", calls.disables, calls.restarts)
	}
	for _, path := range []string{config.FrpConfigFile(), config.FrpHashFile()} {
		if _, err := os.Stat(path); !os.IsNotExist(err) {
			t.Errorf("%s is still there (stat: %v), want it removed", path, err)
		}
	}

	if err := Sync(); err != nil {
		t.Fatalf("second Sync with a null hash: %v", err)
	}
	if calls.disables != 1 {
		t.Errorf("disables after the second run = %d, want still 1", calls.disables)
	}
}

// R-0398: with the last tunnel gone the server still sends the common part, without any
// [[proxies]]. frpc must not run without one: the sync stops and disables it, removes
// frpc.toml and stores the hash, so the next run with the same hash does nothing.
func TestSyncConfigWithoutProxiesStopsFrpc(t *testing.T) {
	toml := []byte("serverAddr = \"1.2.3.4\"\nserverPort = 7000\n\nauth.method = \"token\"\nauth.token = \"frps-token\"\n")
	hash := hashConfig(toml)
	srv, fetches := hashServer(t, `{"hash":"`+hash+`"}`, toml)
	calls := setupSyncTest(t, srv.URL)
	writeFrpcState(t)

	if err := Sync(); err != nil {
		t.Fatalf("Sync with a config without proxies: %v", err)
	}
	if calls.disables != 1 || calls.restarts != 0 {
		t.Errorf("disables = %d, restarts = %d, want 1 and 0", calls.disables, calls.restarts)
	}
	if _, err := os.Stat(config.FrpConfigFile()); !os.IsNotExist(err) {
		t.Errorf("frpc.toml is still there (stat: %v), want it removed", err)
	}
	if got, _ := os.ReadFile(config.FrpHashFile()); strings.TrimSpace(string(got)) != hash {
		t.Errorf("hash file = %q, want %q", got, hash)
	}

	if err := Sync(); err != nil {
		t.Fatalf("second Sync with the same hash: %v", err)
	}
	if calls.disables != 1 || *fetches != 1 {
		t.Errorf("after the second run disables = %d, config fetches = %d, want 1 and 1", calls.disables, *fetches)
	}
}

// A failed stop leaves frpc.toml and the old hash in place, so the next run tries again
// instead of taking the stop for done.
func TestSyncKeepsFilesWhenStoppingFrpcFails(t *testing.T) {
	empty := []byte("serverAddr = \"1.2.3.4\"\n")
	cases := map[string]struct {
		hashJSON string
		toml     []byte
	}{
		"null hash":       {`{"hash": null}`, nil},
		"without proxies": {`{"hash":"` + hashConfig(empty) + `"}`, empty},
	}
	for name, tc := range cases {
		t.Run(name, func(t *testing.T) {
			srv, _ := hashServer(t, tc.hashJSON, tc.toml)
			setupSyncTest(t, srv.URL)
			disableService = func() error { return errors.New("systemctl failed") }
			writeFrpcState(t)
			oldHash, _ := os.ReadFile(config.FrpHashFile())

			if err := Sync(); err == nil {
				t.Fatal("Sync must report the failed stop")
			}
			if _, err := os.Stat(config.FrpConfigFile()); err != nil {
				t.Errorf("frpc.toml is gone (stat: %v), want it kept for the retry", err)
			}
			if got, _ := os.ReadFile(config.FrpHashFile()); string(got) != string(oldHash) {
				t.Errorf("hash file = %q, want the old %q", got, oldHash)
			}
		})
	}
}
