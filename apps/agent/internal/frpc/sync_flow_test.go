// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package frpc

import (
	"bytes"
	"context"
	"errors"
	"log"
	"log/slog"
	"maps"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"slices"
	"strconv"
	"strings"
	"testing"
	"time"

	"adminhelper-agent/internal/config"
)

// seamCalls counts the stubbed frpc service actions of a sync test. active is the stubbed
// frpc state, which the actions change the way systemctl would.
type seamCalls struct {
	restarts, disables, enables, reloads int
	active                               bool
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
	origReload, origDown, origOwns := reloadService, isDown, ownsAdminPort
	restartService = func(context.Context) error { calls.restarts++; calls.active = true; return nil }
	disableService = func(context.Context) error { calls.disables++; calls.active = false; return nil }
	enableService = func(context.Context) error { calls.enables++; calls.active = true; return nil }
	isActive = func(context.Context) (bool, error) { return calls.active, nil }
	reloadService = func(context.Context) error { calls.reloads++; return nil }
	isDown = func(context.Context) (bool, error) { return !calls.active, nil }
	ownsAdminPort = func(int) bool { return true }
	t.Cleanup(func() {
		restartService, disableService, enableService, isActive = origRestart, origDisable, origEnable, origActive
		reloadService, isDown, ownsAdminPort = origReload, origDown, origOwns
	})
	return calls
}

// localHead is the head the agent puts before the server's text: loginFailExit, then frpc's
// admin API on loopback with the port and password from admin.conf.
func localHead(t *testing.T) string {
	t.Helper()
	kv, err := config.LoadKeyValue(filepath.Join(config.FrpDir(), "admin.conf"))
	if err != nil {
		t.Fatalf("read admin.conf: %v", err)
	}
	return "loginFailExit = false\n" +
		"webServer.addr = \"127.0.0.1\"\n" +
		"webServer.port = " + kv["PORT"] + "\n" +
		"webServer.user = \"adminhelper\"\n" +
		"webServer.password = \"" + kv["PASSWORD"] + "\"\n"
}

// serveToml points the sync at a server that sends toml under its hash, and returns the
// server's config fetch counter.
func serveToml(t *testing.T, toml []byte) *int {
	t.Helper()
	srv, fetches := hashServer(t, `{"hash":"`+hashConfig(toml)+`"}`, toml)
	pointSyncAt(t, srv.URL)
	return fetches
}

// readFile returns the content of path, "" when it cannot be read.
func readFile(t *testing.T, path string) string {
	t.Helper()
	data, _ := os.ReadFile(path)
	return string(data)
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

	if err := Sync(context.Background()); err != nil {
		t.Fatalf("Sync: %v", err)
	}
	if got, want := readFile(t, config.FrpConfigFile()), localHead(t)+string(tunnelToml); got != want {
		t.Errorf("frpc.toml = %q, want %q", got, want)
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

	if err := Sync(context.Background()); err != nil {
		t.Fatalf("Sync with the first tunnel: %v", err)
	}
	if calls.enables != 1 || calls.restarts != 0 || calls.disables != 0 {
		t.Errorf("enables = %d, restarts = %d, disables = %d, want 1, 0 and 0", calls.enables, calls.restarts, calls.disables)
	}
	got, err := os.ReadFile(config.FrpConfigFile())
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.HasPrefix(got, []byte("loginFailExit = false\n")) {
		t.Errorf("frpc.toml = %q, want it to start with the line loginFailExit = false", got)
	}
	rest, ok := bytes.CutPrefix(got, []byte(localHead(t)))
	if !ok {
		t.Errorf("frpc.toml = %q, want it to start with the local head %q", got, localHead(t))
	}
	if !bytes.Equal(rest, tunnelToml) {
		t.Errorf("frpc.toml after the local head = %q, want the server's text %q", rest, tunnelToml)
	}
	if runtime.GOOS != "windows" {
		if info, err := os.Stat(config.FrpConfigFile()); err != nil || info.Mode().Perm() != 0o600 {
			t.Errorf("frpc.toml stat = %v, %v, want mode 0600 (it holds the frps token)", info, err)
		}
	}
	if got, _ := os.ReadFile(config.FrpHashFile()); strings.TrimSpace(string(got)) != hash {
		t.Errorf("hash file = %q, want the hash of the server's text %q", got, hash)
	}

	if err := Sync(context.Background()); err != nil {
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
	if err := Sync(context.Background()); err != nil {
		t.Fatalf("Sync without a tunnel: %v", err)
	}
	if calls.disables != 1 {
		t.Fatalf("disables = %d, want 1", calls.disables)
	}

	tunnelSrv, _ := hashServer(t, `{"hash":"`+hashConfig(tunnelToml)+`"}`, tunnelToml)
	pointSyncAt(t, tunnelSrv.URL)
	if err := Sync(context.Background()); err != nil {
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
			enableService = func(context.Context) error { return errors.New("systemctl failed") }
			restartService = func(context.Context) error { return errors.New("systemctl failed") }
			oldHash, _ := os.ReadFile(config.FrpHashFile())

			if err := Sync(context.Background()); err == nil {
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
	// Local hash already matches remote and this agent checked the text -> no fetch/write/restart.
	if err := os.WriteFile(config.FrpHashFile(), []byte(hash), 0644); err != nil {
		t.Fatal(err)
	}
	if err := writeCheckedBy(hash); err != nil {
		t.Fatal(err)
	}

	if err := Sync(context.Background()); err != nil {
		t.Fatalf("Sync: %v", err)
	}
	if _, err := os.Stat(config.FrpConfigFile()); !os.IsNotExist(err) {
		t.Error("frpc.toml should not be written on identical hash")
	}
	if calls.restarts != 0 || calls.enables != 0 {
		t.Errorf("restarts = %d, enables = %d, want 0 and 0", calls.restarts, calls.enables)
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

	if err := Sync(context.Background()); err == nil {
		t.Error("Sync must error on a failing hash endpoint, not skip silently")
	}
	if calls.restarts != 0 || calls.enables != 0 {
		t.Errorf("restarts = %d, enables = %d, want 0 and 0", calls.restarts, calls.enables)
	}
}

// R-0638: a run's context reaches the sync's requests. A server that holds config-hash costs the
// sync no more than its context, not the client timeout of 30 s, and the sync changes nothing.
func TestSyncEndsWithTheContextWhileTheServerHangs(t *testing.T) {
	arrived := make(chan struct{}, 1)
	release := make(chan struct{})
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !strings.HasSuffix(r.URL.Path, "/config-hash") {
			t.Errorf("unexpected request: %s", r.URL.Path)
			w.WriteHeader(http.StatusNotFound)
			return
		}
		select {
		case arrived <- struct{}{}:
		default:
		}
		// Released when the test ends.
		<-release
	}))
	defer srv.Close()
	defer close(release) // runs first: Close waits for the held handler
	calls := setupSyncTest(t, srv.URL)
	writeFrpcState(t)
	calls.active = true
	files, actions := frpFiles(t), *calls

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	res := make(chan error, 1)
	go func() { res <- Sync(ctx) }()
	select {
	case <-arrived:
	case <-time.After(10 * time.Second):
		t.Fatal("the config-hash request did not reach the server")
	}
	cancel()
	select {
	case err := <-res:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("Sync = %v, want an error that wraps context.Canceled", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("Sync did not end with its ctx (client timeout 30s)")
	}
	if got := frpFiles(t); !maps.Equal(got, files) {
		t.Errorf("the FRP directory holds %q, want it unchanged %q", got, files)
	}
	if *calls != actions {
		t.Errorf("frpc service state %+v, want it unchanged %+v (no start, stop or reload)", *calls, actions)
	}
}

// R-0638: a systemctl that does not answer whether frpc runs (timeout, end of the run) does not
// make frpc stuck: the sync would renew its admin API and restart a frpc that may run. On a
// changed hash with frpc.toml in place and no frpc on its admin port (R-0884) the sync returns
// the error before it fetches the config, and changes nothing: admin.conf, frpc.toml and the hash
// stay, nothing starts.
func TestSyncFrpcSystemctlWithoutAnswerChangesNothing(t *testing.T) {
	calls := setupSyncTest(t, "https://unused.example")
	serveToml(t, tunnelToml)
	if err := Sync(context.Background()); err != nil {
		t.Fatalf("Sync with the first tunnel: %v", err)
	}
	noAnswer := errors.New("systemctl is-active frpc.service: context deadline exceeded")
	isDown = func(context.Context) (bool, error) { return false, noAnswer }
	ownsAdminPort = func(int) bool { return false }
	fetches := serveToml(t, twoTunnelsToml)
	files, actions := frpFiles(t), *calls

	if err := Sync(context.Background()); !errors.Is(err, noAnswer) {
		t.Fatalf("Sync = %v, want the failed status query %q", err, noAnswer)
	}
	if got := frpFiles(t); !maps.Equal(got, files) {
		t.Errorf("the FRP directory holds %q, want it unchanged %q", got, files)
	}
	if *calls != actions {
		t.Errorf("frpc service state %+v, want it unchanged %+v (no start, stop or reload)", *calls, actions)
	}
	if *fetches != 0 {
		t.Errorf("config fetches = %d, want 0", *fetches)
	}
}

// R-0884: a systemd that does not answer does not keep a removed tunnel open. frpc listens on its
// admin API and the common part is the one it started on: the sync reloads it there, writes the
// new hash and starts, stops or restarts nothing.
func TestSyncReloadsWithoutAnswerFromSystemd(t *testing.T) {
	calls := setupSyncTest(t, "https://unused.example")
	serveToml(t, twoTunnelsToml)
	if err := Sync(context.Background()); err != nil {
		t.Fatalf("Sync with two tunnels: %v", err)
	}
	noAnswer := errors.New("systemctl is-active frpc.service: context deadline exceeded")
	isDown = func(context.Context) (bool, error) { return false, noAnswer }
	isActive = func(context.Context) (bool, error) { return false, noAnswer }
	var atReload string
	reloadService = func(context.Context) error {
		calls.reloads++
		atReload = readFile(t, config.FrpConfigFile())
		return nil
	}
	serveToml(t, tunnelToml)

	if err := Sync(context.Background()); err != nil {
		t.Fatalf("Sync without an answer from systemd: %v, want a reload", err)
	}
	if calls.reloads != 1 || calls.restarts != 0 || calls.enables != 1 || calls.disables != 0 {
		t.Errorf("reloads = %d, restarts = %d, enables = %d, disables = %d, want 1, 0, 1 and 0",
			calls.reloads, calls.restarts, calls.enables, calls.disables)
	}
	if want := localHead(t) + string(tunnelToml); atReload != want {
		t.Errorf("frpc.toml at the reload = %q, want %q", atReload, want)
	}
	if got := readFile(t, config.FrpHashFile()); got != hashConfig(tunnelToml) {
		t.Errorf("hash file = %q, want the hash of the new text %q", got, hashConfig(tunnelToml))
	}
}

// R-0884: without an answer from systemd a reload is the only way left. When the common part
// changed (a restart would be due) or the reload fails, the sync returns the error, keeps the old
// hash for the next run, and restarts nothing.
func TestSyncWithoutAnswerFromSystemdNoReloadKeepsTheHash(t *testing.T) {
	for _, c := range []struct {
		name   string
		next   []byte
		reload error
	}{
		{"common part changed", withToken("rotated-token"), nil},
		{"reload fails", twoTunnelsToml, errors.New("api status code [401]")},
	} {
		t.Run(c.name, func(t *testing.T) {
			calls := setupSyncTest(t, "https://unused.example")
			serveToml(t, tunnelToml)
			if err := Sync(context.Background()); err != nil {
				t.Fatalf("Sync with the first tunnel: %v", err)
			}
			noAnswer := errors.New("systemctl is-active frpc.service: context deadline exceeded")
			isDown = func(context.Context) (bool, error) { return false, noAnswer }
			isActive = func(context.Context) (bool, error) { return false, noAnswer }
			reloadService = func(context.Context) error { calls.reloads++; return c.reload }
			serveToml(t, c.next)
			before := *calls

			if err := Sync(context.Background()); !errors.Is(err, noAnswer) {
				t.Fatalf("Sync = %v, want the failed status query %q", err, noAnswer)
			}
			if calls.restarts != before.restarts || calls.enables != before.enables || calls.disables != before.disables {
				t.Errorf("frpc service state %+v, want no start, stop or restart since %+v", *calls, before)
			}
			if got := readFile(t, config.FrpHashFile()); got != hashConfig(tunnelToml) {
				t.Errorf("hash file = %q, want the old hash %q", got, hashConfig(tunnelToml))
			}
		})
	}
}

// R-0879: a run that ends while frpc reloads or restarts keeps the record of the common part frpc
// started on: the next run reloads frpc instead of restarting it and dropping every tunnel.
func TestSyncEndedDuringReloadKeepsTheStartedRecord(t *testing.T) {
	calls := setupSyncTest(t, "https://unused.example")
	serveToml(t, tunnelToml)
	if err := Sync(context.Background()); err != nil {
		t.Fatalf("Sync with the first tunnel: %v", err)
	}
	started := readFile(t, startedHashFile())
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	reload := reloadService
	reloadService = func(ctx context.Context) error { cancel(); return ctx.Err() }
	restartService = func(ctx context.Context) error { calls.restarts++; return ctx.Err() }
	serveToml(t, twoTunnelsToml)

	if err := Sync(ctx); !errors.Is(err, context.Canceled) {
		t.Fatalf("Sync = %v, want it ended by its context", err)
	}
	if calls.restarts != 0 {
		t.Errorf("restarts = %d, want 0 after the end of the run", calls.restarts)
	}
	if got := readFile(t, startedHashFile()); started == "" || got != started {
		t.Fatalf("started record = %q, want it kept %q", got, started)
	}

	reloadService = reload
	if err := Sync(context.Background()); err != nil {
		t.Fatalf("next Sync: %v", err)
	}
	if calls.reloads != 1 || calls.restarts != 0 {
		t.Errorf("next Sync: reloads = %d, restarts = %d, want 1 and 0", calls.reloads, calls.restarts)
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

	if err := Sync(context.Background()); err == nil {
		t.Error("Sync must error when the config endpoint fails")
	}
	if got, _ := os.ReadFile(config.FrpConfigFile()); string(got) != "OLD" {
		t.Errorf("frpc.toml = %q, want it untouched (OLD)", got)
	}
	if calls.restarts != 0 || calls.enables != 0 {
		t.Errorf("restarts = %d, enables = %d, want 0 and 0", calls.restarts, calls.enables)
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

	if err := Sync(context.Background()); err != nil {
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

	if err := Sync(context.Background()); err != nil {
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

	if err := Sync(context.Background()); err != nil {
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

	if err := Sync(context.Background()); err != nil {
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

	if err := Sync(context.Background()); err != nil {
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
			disableService = func(context.Context) error { return errors.New("systemctl failed") }
			writeFrpcState(t)
			oldHash, _ := os.ReadFile(config.FrpHashFile())

			if err := Sync(context.Background()); err == nil {
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

// twoTunnelsToml is tunnelToml with a second tunnel: the common part stays, only the proxies change.
var twoTunnelsToml = []byte("serverAddr = \"1.2.3.4\"\nserverPort = 7000\n\n[[proxies]]\nname = \"ssh\"\n\n" +
	"[[proxies]]\nname = \"rdp\"\n")

// withToken is a server-built frpc.toml with one tunnel and the frps token token.
func withToken(token string) []byte {
	return []byte("serverAddr = \"1.2.3.4\"\nauth.token = \"" + token + "\"\n\n[[proxies]]\nname = \"ssh\"\n")
}

// R-0398: a running frpc takes changed tunnels by a reload over its local admin API, so the
// unchanged tunnels and their connections stay; a restart would drop every session to the host.
// The reload reads frpc.toml, so the new file is in place when it runs.
func TestReloadWhenOnlyProxiesChange(t *testing.T) {
	calls := setupSyncTest(t, "https://unused.example")
	serveToml(t, tunnelToml)
	if err := Sync(context.Background()); err != nil {
		t.Fatalf("Sync with the first tunnel: %v", err)
	}
	var atReload string
	reloadService = func(context.Context) error {
		calls.reloads++
		atReload = readFile(t, config.FrpConfigFile())
		return nil
	}

	serveToml(t, twoTunnelsToml)
	if err := Sync(context.Background()); err != nil {
		t.Fatalf("Sync with a second tunnel: %v", err)
	}
	if calls.reloads != 1 || calls.restarts != 0 || calls.enables != 1 {
		t.Errorf("reloads = %d, restarts = %d, enables = %d, want 1, 0 and 1", calls.reloads, calls.restarts, calls.enables)
	}
	if want := localHead(t) + string(twoTunnelsToml); atReload != want {
		t.Errorf("frpc.toml at the reload = %q, want %q", atReload, want)
	}
	if got := readFile(t, config.FrpHashFile()); got != hashConfig(twoTunnelsToml) {
		t.Errorf("hash file = %q, want the hash of the new text %q", got, hashConfig(twoTunnelsToml))
	}
}

// frp takes the common part (frps address, token, user, TLS) only at start and a reload keeps the
// old one, so a rotated token restarts frpc.
func TestReloadNotWhenTheTokenChanges(t *testing.T) {
	calls := setupSyncTest(t, "https://unused.example")
	serveToml(t, withToken("old-token"))
	if err := Sync(context.Background()); err != nil {
		t.Fatalf("Sync with the first tunnel: %v", err)
	}

	serveToml(t, withToken("rotated-token"))
	if err := Sync(context.Background()); err != nil {
		t.Fatalf("Sync with a rotated token: %v", err)
	}
	if calls.restarts != 1 || calls.reloads != 0 {
		t.Errorf("restarts = %d, reloads = %d, want 1 and 0", calls.restarts, calls.reloads)
	}
	if got, want := readFile(t, config.FrpConfigFile()), localHead(t)+string(withToken("rotated-token")); got != want {
		t.Errorf("frpc.toml = %q, want %q", got, want)
	}
}

// A reload that fails (admin API refused, frpc gone) falls back to a restart: the run applies the
// config and stays green, and the log says why frpc restarted.
func TestReloadFailureRestartsFrpc(t *testing.T) {
	calls := setupSyncTest(t, "https://unused.example")
	serveToml(t, tunnelToml)
	if err := Sync(context.Background()); err != nil {
		t.Fatalf("Sync with the first tunnel: %v", err)
	}
	reloadService = func(context.Context) error { calls.reloads++; return errors.New("api status code [401]") }
	out := captureLog(t)

	serveToml(t, twoTunnelsToml)
	if err := Sync(context.Background()); err != nil {
		t.Fatalf("Sync with a failing reload: %v, want a restart instead", err)
	}
	if calls.reloads != 1 || calls.restarts != 1 {
		t.Errorf("reloads = %d, restarts = %d, want 1 and 1", calls.reloads, calls.restarts)
	}
	for _, want := range []string{"level=WARN", "api status code [401]"} {
		if !strings.Contains(out.String(), want) {
			t.Errorf("log %q is missing %q", out.String(), want)
		}
	}
	if got := readFile(t, config.FrpHashFile()); got != hashConfig(twoTunnelsToml) {
		t.Errorf("hash file = %q, want the hash of the new text %q", got, hashConfig(twoTunnelsToml))
	}
}

// A provisioning restarts frpc with the common part unchanged, to have it connect anew. When that
// restart fails, frpc may still run on its old connection, and the record of the common part it
// started on is gone: the next run restarts frpc again instead of reloading it.
func TestReloadNotAfterAFailedRestart(t *testing.T) {
	calls := setupSyncTest(t, "https://unused.example")
	serveToml(t, bundleToml)
	if err := Sync(context.Background()); err != nil {
		t.Fatalf("Sync with the tunnel: %v", err)
	}
	restart := restartService
	restartService = func(context.Context) error { return errors.New("systemctl failed") }
	if err := applyBundle(bundleToml); err != nil {
		t.Fatalf("Apply with a failing restart: %v, want only a warning", err)
	}
	restartService = restart

	serveToml(t, bundleToml) // Apply pointed the sync config at its own URL
	if err := Sync(context.Background()); err != nil {
		t.Fatalf("next Sync: %v", err)
	}
	if calls.restarts != 1 || calls.reloads != 0 {
		t.Errorf("next Sync: restarts = %d, reloads = %d, want 1 and 0", calls.restarts, calls.reloads)
	}
}

// R-0398: frpc should run (frpc.toml is there) but does not. After a reboot another process may
// hold its admin port, and frpc does not start without it. The next run, with the hash unchanged,
// renews the admin API (new port, new password), writes the file anew and starts frpc.
func TestReloadAdminPortMovesWhenFrpcIsDown(t *testing.T) {
	calls := setupSyncTest(t, "https://unused.example")
	fetches := serveToml(t, tunnelToml)
	if err := Sync(context.Background()); err != nil {
		t.Fatalf("Sync with the first tunnel: %v", err)
	}
	adminConf := filepath.Join(config.FrpDir(), "admin.conf")
	before, err := config.LoadKeyValue(adminConf)
	if err != nil {
		t.Fatal(err)
	}
	// Another process holds the old port, as after the reboot; one that took it already does too.
	if l, err := net.Listen("tcp", "127.0.0.1:"+before["PORT"]); err == nil {
		t.Cleanup(func() { _ = l.Close() })
	}
	calls.active = false

	if err := Sync(context.Background()); err != nil {
		t.Fatalf("Sync with frpc down: %v", err)
	}
	after, err := config.LoadKeyValue(adminConf)
	if err != nil {
		t.Fatal(err)
	}
	if after["PORT"] == before["PORT"] || after["PASSWORD"] == before["PASSWORD"] {
		t.Errorf("admin.conf port %s -> %s, password kept = %v; want a new port and a new password",
			before["PORT"], after["PORT"], after["PASSWORD"] == before["PASSWORD"])
	}
	if got, want := readFile(t, config.FrpConfigFile()), localHead(t)+string(tunnelToml); got != want {
		t.Errorf("frpc.toml = %q, want %q", got, want)
	}
	if calls.enables != 2 || *fetches != 2 {
		t.Errorf("enables = %d, config fetches = %d, want 2 and 2", calls.enables, *fetches)
	}

	if err := Sync(context.Background()); err != nil {
		t.Fatalf("Sync with frpc running again: %v", err)
	}
	if calls.enables != 2 || *fetches != 2 {
		t.Errorf("after frpc runs again: enables = %d, config fetches = %d, want still 2 and 2", calls.enables, *fetches)
	}
}

// R-0398: frpc hangs on its held admin port, and the hash changes before the next run (a tunnel
// added). That run renews the admin API as well and starts frpc on the new file; on the old port
// frpc would stay down for one run more. frpc does not run, so it starts, it does not reload.
func TestSyncStuckFrpcGetsANewAdminPortWhenTheHashChanges(t *testing.T) {
	calls := setupSyncTest(t, "https://unused.example")
	serveToml(t, tunnelToml)
	if err := Sync(context.Background()); err != nil {
		t.Fatalf("Sync with the first tunnel: %v", err)
	}
	adminConf := filepath.Join(config.FrpDir(), "admin.conf")
	before, err := config.LoadKeyValue(adminConf)
	if err != nil {
		t.Fatal(err)
	}
	if l, err := net.Listen("tcp", "127.0.0.1:"+before["PORT"]); err == nil {
		t.Cleanup(func() { _ = l.Close() })
	}
	calls.active = false

	serveToml(t, twoTunnelsToml)
	if err := Sync(context.Background()); err != nil {
		t.Fatalf("Sync with a second tunnel and frpc down: %v", err)
	}
	after, err := config.LoadKeyValue(adminConf)
	if err != nil {
		t.Fatal(err)
	}
	if after["PORT"] == before["PORT"] || after["PASSWORD"] == before["PASSWORD"] {
		t.Errorf("admin.conf port %s -> %s, password kept = %v; want a new port and a new password",
			before["PORT"], after["PORT"], after["PASSWORD"] == before["PASSWORD"])
	}
	if got, want := readFile(t, config.FrpConfigFile()), localHead(t)+string(twoTunnelsToml); got != want {
		t.Errorf("frpc.toml = %q, want %q", got, want)
	}
	if calls.enables != 2 || calls.restarts != 0 || calls.reloads != 0 {
		t.Errorf("enables = %d, restarts = %d, reloads = %d, want 2, 0 and 0", calls.enables, calls.restarts, calls.reloads)
	}
	if got := readFile(t, config.FrpHashFile()); got != hashConfig(twoTunnelsToml) {
		t.Errorf("hash file = %q, want the hash of the new text %q", got, hashConfig(twoTunnelsToml))
	}
}

// A hung frpc on a host without a tunnel left only stops, for a server text without [[proxies]]
// as for a null hash: the admin API stays as it is, and frpc does not start.
func TestSyncStuckFrpcWithoutATunnelOnlyStops(t *testing.T) {
	empty := []byte("serverAddr = \"1.2.3.4\"\n")
	cases := map[string]struct {
		hashJSON string
		toml     []byte
	}{
		"without proxies": {`{"hash":"` + hashConfig(empty) + `"}`, empty},
		"null hash":       {`{"hash": null}`, nil},
	}
	for name, tc := range cases {
		t.Run(name, func(t *testing.T) {
			calls := setupSyncTest(t, "https://unused.example")
			serveToml(t, tunnelToml)
			if err := Sync(context.Background()); err != nil {
				t.Fatalf("Sync with the first tunnel: %v", err)
			}
			adminConf := filepath.Join(config.FrpDir(), "admin.conf")
			before := readFile(t, adminConf)
			calls.active = false

			srv, _ := hashServer(t, tc.hashJSON, tc.toml)
			pointSyncAt(t, srv.URL)
			if err := Sync(context.Background()); err != nil {
				t.Fatalf("Sync without a tunnel and frpc down: %v", err)
			}
			if calls.disables != 1 || calls.enables != 1 || calls.restarts != 0 || calls.reloads != 0 {
				t.Errorf("disables = %d, enables = %d, restarts = %d, reloads = %d, want 1, 1, 0 and 0",
					calls.disables, calls.enables, calls.restarts, calls.reloads)
			}
			if got := readFile(t, adminConf); got != before {
				t.Errorf("admin.conf = %q, want it unchanged %q", got, before)
			}
			if _, err := os.Stat(config.FrpConfigFile()); !os.IsNotExist(err) {
				t.Errorf("frpc.toml is still there (stat: %v), want it removed", err)
			}
		})
	}
}

// R-0398: an older agent may have written the server's text without a tunnel to frpc.toml and
// left frpc running on it; the stored hash then matches the server's. The sync stops frpc all the
// same, as on a hash change: stopped and disabled, frpc.toml removed, the hash stored, and neither
// a new admin API nor a start. With frpc down the file alone counts. The next run has nothing to do.
func TestSyncStopsFrpcOnAConfigWithoutATunnel(t *testing.T) {
	toml := []byte("serverAddr = \"1.2.3.4\"\nserverPort = 7000\n\nauth.method = \"token\"\nauth.token = \"frps-token\"\n")
	for name, active := range map[string]bool{"frpc running": true, "frpc down": false} {
		t.Run(name, func(t *testing.T) {
			calls := setupSyncTest(t, "https://unused.example")
			fetches := serveToml(t, toml)
			if err := os.WriteFile(config.FrpConfigFile(), toml, 0600); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(config.FrpHashFile(), []byte(hashConfig(toml)), 0644); err != nil {
				t.Fatal(err)
			}
			calls.active = active

			if err := Sync(context.Background()); err != nil {
				t.Fatalf("Sync with the same hash and frpc.toml without a tunnel: %v", err)
			}
			if calls.disables != 1 || calls.enables != 0 || calls.restarts != 0 || calls.reloads != 0 {
				t.Errorf("disables = %d, enables = %d, restarts = %d, reloads = %d, want 1, 0, 0 and 0",
					calls.disables, calls.enables, calls.restarts, calls.reloads)
			}
			if _, err := os.Stat(config.FrpConfigFile()); !os.IsNotExist(err) {
				t.Errorf("frpc.toml is still there (stat: %v), want it removed", err)
			}
			if _, err := os.Stat(filepath.Join(config.FrpDir(), "admin.conf")); !os.IsNotExist(err) {
				t.Errorf("admin.conf stat: %v, want none written without a tunnel", err)
			}
			if got := readFile(t, config.FrpHashFile()); got != hashConfig(toml) {
				t.Errorf("hash file = %q, want %q", got, hashConfig(toml))
			}

			if err := Sync(context.Background()); err != nil {
				t.Fatalf("second Sync with the same hash: %v", err)
			}
			if calls.disables != 1 || *fetches != 1 {
				t.Errorf("after the second run disables = %d, config fetches = %d, want 1 and 1", calls.disables, *fetches)
			}
		})
	}
}

// The common run: the hash is the same and frpc runs on a frpc.toml with a tunnel. Reading the
// file changes nothing there: no fetch, no service action, the file stays as it is.
func TestSyncLeavesRunningFrpcWithATunnelAlone(t *testing.T) {
	calls := setupSyncTest(t, "https://unused.example")
	fetches := serveToml(t, tunnelToml)
	if err := Sync(context.Background()); err != nil {
		t.Fatalf("Sync with the first tunnel: %v", err)
	}
	before := readFile(t, config.FrpConfigFile())

	if err := Sync(context.Background()); err != nil {
		t.Fatalf("Sync with the same hash: %v", err)
	}
	if *fetches != 1 || calls.enables != 1 || calls.restarts != 0 || calls.reloads != 0 || calls.disables != 0 {
		t.Errorf("config fetches = %d, enables = %d, restarts = %d, reloads = %d, disables = %d, want 1, 1, 0, 0 and 0",
			*fetches, calls.enables, calls.restarts, calls.reloads, calls.disables)
	}
	if got := readFile(t, config.FrpConfigFile()); got != before {
		t.Errorf("frpc.toml = %q, want it unchanged %q", got, before)
	}
}

// frpc hangs and a tunnel is added. When admin.conf cannot be written, the run fails at the
// renewal: frpc does not start, frpc.toml stays, and the old hash stays, so the next run retries.
func TestSyncStuckFrpcFailsWhenRenewingTheAdminAPIFails(t *testing.T) {
	calls := setupSyncTest(t, "https://unused.example")
	serveToml(t, tunnelToml)
	if err := Sync(context.Background()); err != nil {
		t.Fatalf("Sync with the first tunnel: %v", err)
	}
	adminConf := filepath.Join(config.FrpDir(), "admin.conf")
	// A directory in its place fails the write also for root, which a read-only file would not.
	if err := os.Remove(adminConf); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(adminConf, 0o700); err != nil {
		t.Fatal(err)
	}
	oldConfig, oldHash := readFile(t, config.FrpConfigFile()), readFile(t, config.FrpHashFile())
	calls.active = false

	serveToml(t, twoTunnelsToml)
	err := Sync(context.Background())
	if err == nil || !strings.Contains(err.Error(), "write "+adminConf) {
		t.Fatalf("Sync = %v, want the failed write of %s", err, adminConf)
	}
	if calls.enables != 1 || calls.restarts != 0 || calls.reloads != 0 {
		t.Errorf("enables = %d, restarts = %d, reloads = %d, want 1, 0 and 0", calls.enables, calls.restarts, calls.reloads)
	}
	if got := readFile(t, config.FrpConfigFile()); got != oldConfig {
		t.Errorf("frpc.toml = %q, want the old %q", got, oldConfig)
	}
	if got := readFile(t, config.FrpHashFile()); got != oldHash {
		t.Errorf("hash file = %q, want the old %q", got, oldHash)
	}
}

// stubEnsureDataDir has securing a directory fail with err for the rest of the test, and returns
// the directories the sync asked to secure.
func stubEnsureDataDir(t *testing.T, err error) *[]string {
	t.Helper()
	var dirs []string
	orig := ensureDataDir
	ensureDataDir = func(dir string) error { dirs = append(dirs, dir); return err }
	t.Cleanup(func() { ensureDataDir = orig })
	return &dirs
}

// frpFiles returns the name and the content of every entry of the FRP directory.
func frpFiles(t *testing.T) map[string]string {
	t.Helper()
	entries, err := os.ReadDir(config.FrpDir())
	if err != nil {
		t.Fatal(err)
	}
	files := make(map[string]string, len(entries))
	for _, e := range entries {
		files[e.Name()] = readFile(t, filepath.Join(config.FrpDir(), e.Name()))
	}
	return files
}

// A sync changes frpc's files only in a directory it secured in the same run. When the FRP
// directory cannot be secured, the sync fails with the directory in the error and writes,
// removes, starts and stops nothing: for a new config with a tunnel, for a null hash and a
// server text without a tunnel while frpc.toml is in place, and for a hung frpc on a changed
// hash, where the sync would renew the admin API (admin.conf) first.
func TestSyncChangesNothingWhenTheFrpDirCannotBeSecured(t *testing.T) {
	empty := []byte("serverAddr = \"1.2.3.4\"\n")
	firstRun := func(*testing.T, *seamCalls) {}
	ranWithATunnel := func(t *testing.T, calls *seamCalls) {
		writeFrpcState(t)
		calls.active = true
	}
	hung := func(t *testing.T, calls *seamCalls) {
		serveToml(t, tunnelToml)
		if err := Sync(context.Background()); err != nil {
			t.Fatalf("Sync with the first tunnel: %v", err)
		}
		calls.active = false
	}
	cases := map[string]struct {
		before   func(t *testing.T, calls *seamCalls)
		hashJSON string
		toml     []byte
	}{
		"new config with a tunnel":                  {firstRun, `{"hash":"` + hashConfig(tunnelToml) + `"}`, tunnelToml},
		"null hash, frpc.toml in place":             {ranWithATunnel, `{"hash": null}`, nil},
		"text without a tunnel, frpc.toml in place": {ranWithATunnel, `{"hash":"` + hashConfig(empty) + `"}`, empty},
		"hung frpc, changed hash":                   {hung, `{"hash":"` + hashConfig(twoTunnelsToml) + `"}`, twoTunnelsToml},
	}
	for name, tc := range cases {
		t.Run(name, func(t *testing.T) {
			calls := setupSyncTest(t, "https://unused.example")
			tc.before(t, calls)
			srv, _ := hashServer(t, tc.hashJSON, tc.toml)
			pointSyncAt(t, srv.URL)
			files, actions := frpFiles(t), *calls
			notSecured := errors.New("an entry in the data root cannot be removed")
			secured := stubEnsureDataDir(t, notSecured)

			err := Sync(context.Background())
			if !errors.Is(err, notSecured) || !strings.Contains(err.Error(), config.FrpDir()) {
				t.Fatalf("Sync = %v, want the failure to secure %s, naming it", err, config.FrpDir())
			}
			if !slices.Equal(*secured, []string{config.FrpDir()}) {
				t.Errorf("secured %q, want the FRP directory %s once", *secured, config.FrpDir())
			}
			if got := frpFiles(t); !maps.Equal(got, files) {
				t.Errorf("the FRP directory holds %q, want it unchanged %q", got, files)
			}
			if *calls != actions {
				t.Errorf("frpc service state %+v, want it unchanged %+v (no start, stop or reload)", *calls, actions)
			}
		})
	}
}

// A run without a change secures nothing, so that the common run does not walk the data root
// (on Windows with its tree): the hash is the same and frpc runs on a frpc.toml with a tunnel,
// or the server has no FRP config and neither frpc.toml nor the hash is left.
func TestSyncSecuresNothingWithoutAChange(t *testing.T) {
	t.Run("same hash, frpc runs on a tunnel", func(t *testing.T) {
		setupSyncTest(t, "https://unused.example")
		serveToml(t, tunnelToml)
		if err := Sync(context.Background()); err != nil {
			t.Fatalf("Sync with the first tunnel: %v", err)
		}
		secured := stubEnsureDataDir(t, errors.New("not secured"))

		if err := Sync(context.Background()); err != nil {
			t.Fatalf("Sync with the same hash: %v", err)
		}
		if len(*secured) != 0 {
			t.Errorf("secured %q, want nothing", *secured)
		}
	})
	t.Run("null hash, nothing left", func(t *testing.T) {
		srv, _ := hashServer(t, `{"hash": null}`, nil)
		setupSyncTest(t, srv.URL)
		secured := stubEnsureDataDir(t, errors.New("not secured"))

		if err := Sync(context.Background()); err != nil {
			t.Fatalf("Sync with a null hash: %v", err)
		}
		if len(*secured) != 0 {
			t.Errorf("secured %q, want nothing", *secured)
		}
	})
}

// A sync that changes frpc's files secures the FRP directory with EnsureDataDir: on Linux it
// ends 0700, as at the provisioning, also when it was wider before.
func TestSyncLeavesTheFrpDirOwnerOnly(t *testing.T) {
	setupSyncTest(t, "https://unused.example")
	serveToml(t, tunnelToml)
	if runtime.GOOS != "windows" {
		if err := os.Chmod(config.FrpDir(), 0o755); err != nil {
			t.Fatal(err)
		}
	}

	if err := Sync(context.Background()); err != nil {
		t.Fatalf("Sync with the first tunnel: %v", err)
	}
	if got, want := readFile(t, config.FrpConfigFile()), localHead(t)+string(tunnelToml); got != want {
		t.Errorf("frpc.toml = %q, want %q", got, want)
	}
	if runtime.GOOS != "windows" {
		info, err := os.Stat(config.FrpDir())
		if err != nil {
			t.Fatal(err)
		}
		if got := info.Mode().Perm(); got != 0o700 {
			t.Errorf("%s has mode %v, want 0700", config.FrpDir(), got)
		}
	}
}

// The reload goes only to the agent's own frpc: a root-owned socket listening on 127.0.0.1 at the
// admin port from admin.conf. Without one, frpc restarts instead.
func TestReloadOnlyWhenFrpcHoldsTheAdminPort(t *testing.T) {
	calls := setupSyncTest(t, "https://unused.example")
	serveToml(t, tunnelToml)
	if err := Sync(context.Background()); err != nil {
		t.Fatalf("Sync with the first tunnel: %v", err)
	}
	checked := 0
	ownsAdminPort = func(port int) bool { checked = port; return false }

	serveToml(t, twoTunnelsToml)
	if err := Sync(context.Background()); err != nil {
		t.Fatalf("Sync with a second tunnel: %v", err)
	}
	if calls.reloads != 0 || calls.restarts != 1 {
		t.Errorf("reloads = %d, restarts = %d, want 0 and 1", calls.reloads, calls.restarts)
	}
	kv, err := config.LoadKeyValue(filepath.Join(config.FrpDir(), "admin.conf"))
	if err != nil {
		t.Fatal(err)
	}
	if strconv.Itoa(checked) != kv["PORT"] {
		t.Errorf("checked port %d, want the admin port %s", checked, kv["PORT"])
	}
}

// The server sets no local head: a server text with a webServer or loginFailExit key or table,
// in any case and also after the proxies (a table header there is a root table again), is
// refused. frpc does not keep running on the old file: it is stopped and disabled, frpc.toml and
// the hash go, so the next run fetches and checks again.
func TestReloadRefusesALocalHeadFromTheServer(t *testing.T) {
	common := "serverAddr = \"1.2.3.4\"\n"
	proxy := "\n[[proxies]]\nname = \"ssh\"\n"
	for name, toml := range map[string]string{
		"webServer key":           common + "webServer.port = 7400\n" + proxy,
		"loginFailExit key":       common + "loginFailExit = true\n" + proxy,
		"other case, indented":    common + "  webserver.addr = \"0.0.0.0\"\n" + proxy,
		"upper case":              common + "LOGINFAILEXIT = true\n" + proxy,
		"quoted key":              common + "\"webServer\".user = \"x\"\n" + proxy,
		"inline table":            common + "webServer = { port = 7400 }\n" + proxy,
		"table after the proxies": common + proxy + "\n[WebServer]\naddr = \"0.0.0.0\"\n",
	} {
		t.Run(name, func(t *testing.T) {
			calls := setupSyncTest(t, "https://unused.example")
			writeFrpcState(t)
			calls.active = true
			serveToml(t, []byte(toml))

			if err := Sync(context.Background()); err == nil {
				t.Fatal("Sync must refuse the server's text")
			}
			if calls.reloads+calls.restarts+calls.enables != 0 || calls.disables != 1 || calls.active {
				t.Errorf("reloads = %d, restarts = %d, enables = %d, disables = %d, active = %v, want 0, 0, 0, 1, false",
					calls.reloads, calls.restarts, calls.enables, calls.disables, calls.active)
			}
			if !frpcGone() {
				t.Errorf("frpc.toml or the hash is still there, want both removed")
			}
		})
	}
}

// Only keys and tables count: a value that names webServer, as a proxy name may, passes.
func TestReloadLocalHeadCheckLetsValuesPass(t *testing.T) {
	toml := []byte("serverAddr = \"1.2.3.4\"\nuser = \"webServer\"\n\n[[proxies]]\nname = \"loginFailExit\"\n")
	if err := checkServerConfig(toml); err != nil {
		t.Errorf("checkServerConfig = %v, want nil when only values name webServer or loginFailExit", err)
	}
}

// seedRunningTunnel puts frpc running on tunnelToml under its hash, as a former sync left it,
// with checkedBy holding the given version ("" for none, as every agent before the marker).
func seedRunningTunnel(t *testing.T, calls *seamCalls, toml []byte, checkedByVersion string) {
	t.Helper()
	if err := os.WriteFile(config.FrpConfigFile(), toml, 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(config.FrpHashFile(), []byte(hashConfig(toml)), 0644); err != nil {
		t.Fatal(err)
	}
	if checkedByVersion != "" {
		if err := os.WriteFile(checkedByFile(), []byte(checkedByVersion), 0644); err != nil {
			t.Fatal(err)
		}
	}
	calls.active = true
}

// useAgentVersion sets the agent version for one test.
func useAgentVersion(t *testing.T, v string) {
	t.Helper()
	orig := agentVersion
	SetAgentVersion(v)
	t.Cleanup(func() { SetAgentVersion(orig) })
}

// After an agent update the stored text is fetched and checked once, even with the same hash.
// When it passes, frpc and its files stay as they are and only the marker is written; the next
// run is a no-op again. Without a marker (an agent from before it) it is the same.
func TestSyncRechecksTheConfigAfterAnUpdate(t *testing.T) {
	for name, before := range map[string]string{
		"no marker":                 "",
		"older agent":               "0.45.0",
		"older agent, with hash":    "0.45.0 " + hashConfig(tunnelToml),
		"this agent, another text":  "0.47.0 " + hashConfig([]byte("another text")),
		"this agent, version alone": "0.47.0",
	} {
		t.Run(name, func(t *testing.T) {
			calls := setupSyncTest(t, "https://unused.example")
			useAgentVersion(t, "0.47.0")
			fetches := serveToml(t, tunnelToml)
			seedRunningTunnel(t, calls, tunnelToml, before)
			files, actions := frpFiles(t), *calls

			if err := Sync(context.Background()); err != nil {
				t.Fatalf("Sync after an update: %v", err)
			}
			if *fetches != 1 {
				t.Errorf("config fetches = %d, want 1", *fetches)
			}
			if *calls != actions {
				t.Errorf("frpc service state %+v, want it unchanged %+v (no reload or restart)", *calls, actions)
			}
			if got := readFile(t, config.FrpConfigFile()); got != files["frpc.toml"] {
				t.Errorf("frpc.toml = %q, want it unchanged %q", got, files["frpc.toml"])
			}
			if got, want := checkedBy(), "0.47.0 "+hashConfig(tunnelToml); got != want {
				t.Errorf("checked by %q, want %q", got, want)
			}

			if err := Sync(context.Background()); err != nil {
				t.Fatalf("second Sync: %v", err)
			}
			if *fetches != 1 {
				t.Errorf("config fetches after the second run = %d, want still 1", *fetches)
			}
		})
	}
}

// A stored text the updated agent's check refuses is not left running: the recheck stops frpc
// like any refused text.
func TestSyncRecheckStopsFrpcOnARefusedStoredText(t *testing.T) {
	calls := setupSyncTest(t, "https://unused.example")
	useAgentVersion(t, "0.47.0")
	refused := []byte(refusedOverTheFlows["proxy plugin"])
	serveToml(t, refused)
	seedRunningTunnel(t, calls, refused, "0.45.0")

	if err := Sync(context.Background()); err == nil {
		t.Fatal("the recheck must refuse the stored text")
	}
	if calls.disables != 1 || calls.active || calls.enables+calls.restarts+calls.reloads != 0 {
		t.Errorf("frpc service state %+v, want it stopped and disabled once, nothing started", *calls)
	}
	if !frpcGone() {
		t.Errorf("frpc.toml or the hash is still there, want both removed")
	}
	if got := checkedBy(); got != "" {
		t.Errorf("checked by %q, want the marker removed", got)
	}
}

// Writing a config records the agent that checked it, and a host without an FRP config keeps
// no marker.
func TestSyncKeepsTheMarkerWithTheConfig(t *testing.T) {
	calls := setupSyncTest(t, "https://unused.example")
	useAgentVersion(t, "0.47.0")
	serveToml(t, tunnelToml)
	if err := Sync(context.Background()); err != nil {
		t.Fatalf("Sync: %v", err)
	}
	if got, want := checkedBy(), "0.47.0 "+hashConfig(tunnelToml); got != want {
		t.Errorf("checked by %q after writing the config, want %q", got, want)
	}

	srv, _ := hashServer(t, `{"hash": null}`, nil)
	pointSyncAt(t, srv.URL)
	if err := Sync(context.Background()); err != nil {
		t.Fatalf("Sync with a null hash: %v", err)
	}
	if _, err := os.Stat(checkedByFile()); !os.IsNotExist(err) {
		t.Errorf("marker stat = %v, want it removed with the config", err)
	}
	if calls.disables != 1 {
		t.Errorf("disables = %d, want 1", calls.disables)
	}
}

// Without a stored hash there is no stored text to check again: an answer without a hash and
// no hash on disk compare equal, and the marker of another agent alone fetches nothing.
func TestSyncRechecksNothingWithoutAStoredHash(t *testing.T) {
	srv, fetches := hashServer(t, `{}`, tunnelToml)
	setupSyncTest(t, srv.URL)
	useAgentVersion(t, "0.47.0")
	if err := os.WriteFile(checkedByFile(), []byte("0.45.0"), 0644); err != nil {
		t.Fatal(err)
	}
	if err := Sync(context.Background()); err != nil {
		t.Fatalf("Sync: %v", err)
	}
	if *fetches != 0 {
		t.Errorf("config fetches = %d, want 0", *fetches)
	}
}

// A refused text stays an error when stopping frpc fails as well, for the sync and for the
// provisioning, which turns a plain failed stop into a warning.
func TestRefusalStaysAnErrorWhenStoppingFrpcFails(t *testing.T) {
	refused := []byte(refusedOverTheFlows["proxy plugin"])
	for name, run := range map[string]func() error{
		"sync":            func() error { return Sync(context.Background()) },
		"re-provisioning": func() error { return applyBundle(refused) },
	} {
		t.Run(name, func(t *testing.T) {
			calls := setupSyncTest(t, "https://srv.example")
			serveToml(t, refused)
			writeFrpcState(t)
			calls.active = true
			disableService = func(context.Context) error { calls.disables++; return errors.New("systemctl failed") }

			err := run()
			if err == nil {
				t.Fatal("a refused text must stay an error when stopping frpc fails")
			}
			if errors.Is(err, errFrpcService) {
				t.Errorf("error %v carries errFrpcService, which the provisioning turns into a warning", err)
			}
		})
	}
}

// R-0963: a stop that systemd does not carry out still drops the tunnels: the agent's own frpc
// gets its frpc.toml without the [[proxies]] tables over a reload, frp stops every proxy the
// reload no longer names. The stop stays an error and the old hash stays, so the next run asks
// systemd again; the common part stays for that run.
func TestStopFrpcDropsTheTunnelsWhenSystemdFails(t *testing.T) {
	for name, owns := range map[string]bool{"own frpc": true, "foreign admin port": false} {
		t.Run(name, func(t *testing.T) {
			calls := setupSyncTest(t, "https://srv.example")
			serveToml(t, tunnelToml)
			if err := Sync(context.Background()); err != nil {
				t.Fatalf("first Sync: %v", err)
			}
			withTunnel, _ := os.ReadFile(config.FrpConfigFile())
			oldHash, _ := os.ReadFile(config.FrpHashFile())
			srv, _ := hashServer(t, `{"hash": null}`, nil)
			pointSyncAt(t, srv.URL)
			disableService = func(context.Context) error { calls.disables++; return errors.New("systemctl failed") }
			ownsAdminPort = func(int) bool { return owns }
			reloads := calls.reloads

			err := Sync(context.Background())
			if !errors.Is(err, errFrpcService) {
				t.Fatalf("Sync = %v, want the failed stop as errFrpcService", err)
			}
			got, _ := os.ReadFile(config.FrpConfigFile())
			if h, _ := os.ReadFile(config.FrpHashFile()); string(h) != string(oldHash) {
				t.Errorf("hash file = %q, want the old %q", h, oldHash)
			}
			if !owns {
				if calls.reloads != reloads || string(got) != string(withTunnel) {
					t.Errorf("foreign port: reloads %d -> %d, frpc.toml %q, want no reload and the file unchanged",
						reloads, calls.reloads, got)
				}
				if !strings.Contains(err.Error(), "does not listen on its admin port") {
					t.Errorf("error %v does not say why the tunnels stay", err)
				}
				return
			}
			if calls.reloads != reloads+1 {
				t.Errorf("reloads %d -> %d, want one reload without the tunnels", reloads, calls.reloads)
			}
			if hasProxies(got) || string(got) != string(commonPart(withTunnel)) {
				t.Errorf("frpc.toml = %q, want the common part %q", got, commonPart(withTunnel))
			}

			disableService = func(context.Context) error { calls.disables++; return nil }
			if err := Sync(context.Background()); err != nil {
				t.Fatalf("next Sync: %v", err)
			}
			if _, err := os.Stat(config.FrpConfigFile()); !os.IsNotExist(err) {
				t.Errorf("next Sync: frpc.toml stat = %v, want removed", err)
			}
		})
	}
}

// A reload that fails as well joins the stop error; the stop stays errFrpcService, and the next
// run reloads again although frpc.toml is already without proxies.
func TestStopFrpcReportsAFailedTunnelDrop(t *testing.T) {
	calls := setupSyncTest(t, "https://srv.example")
	serveToml(t, tunnelToml)
	if err := Sync(context.Background()); err != nil {
		t.Fatalf("first Sync: %v", err)
	}
	disableService = func(context.Context) error { calls.disables++; return errors.New("systemctl failed") }
	reloadService = func(context.Context) error { return errors.New("reload refused") }

	err := stopFrpc(context.Background())
	if !errors.Is(err, errFrpcService) || !strings.Contains(err.Error(), "reload refused") {
		t.Errorf("stopFrpc = %v, want errFrpcService with the failed reload", err)
	}

	// The file is without proxies now, frpc still runs with them: the next run reloads again.
	reloadService = func(context.Context) error { calls.reloads++; return nil }
	reloads := calls.reloads
	if err := stopFrpc(context.Background()); !errors.Is(err, errFrpcService) {
		t.Errorf("second stopFrpc = %v, want the failed stop as errFrpcService", err)
	}
	if calls.reloads != reloads+1 {
		t.Errorf("second stopFrpc: reloads %d -> %d, want a new reload after the failed one", reloads, calls.reloads)
	}
}
