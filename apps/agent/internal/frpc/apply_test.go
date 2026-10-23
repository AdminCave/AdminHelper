// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package frpc

import (
	"bytes"
	"context"
	"encoding/base64"
	"errors"
	"log"
	"log/slog"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"strings"
	"testing"

	"adminhelper-agent/internal/config"
)

// R-0398: the sync config is what every later sync runs on (URL, API key, server ID,
// trust). It carries the server API key, so it and its directory are root's alone.
func TestWriteSyncConfigStoresKeyAndPinnedCA(t *testing.T) {
	// Not created yet: WriteSyncConfig makes the directory itself.
	t.Setenv("ADMINHELPER_FRP_DIR", filepath.Join(t.TempDir(), "frp"))
	pinned := filepath.Join(t.TempDir(), "pinned.crt")
	if err := os.WriteFile(pinned, []byte("PINNED-CA"), 0o600); err != nil {
		t.Fatal(err)
	}

	if err := WriteSyncConfig(SyncConfigParams{
		AdminHelperURL: "https://srv.example/",
		ServerID:       "srv-1",
		APIKey:         "key-1",
		TLS:            config.TLSOpts{CACert: pinned},
	}); err != nil {
		t.Fatalf("WriteSyncConfig: %v", err)
	}

	kv, err := config.LoadKeyValue(config.FrpAdminHelperConf())
	if err != nil {
		t.Fatalf("sync config: %v", err)
	}
	want := map[string]string{
		"ADMINHELPER_URL": "https://srv.example",
		"API_KEY":         "key-1",
		"SERVER_ID":       "srv-1",
		"CACERT":          config.FrpCACert(),
	}
	if !reflect.DeepEqual(kv, want) {
		t.Fatalf("sync config = %v, want %v", kv, want)
	}
	if got, _ := os.ReadFile(config.FrpCACert()); string(got) != "PINNED-CA" {
		t.Fatalf("ca.crt = %q, want the pinned CA copied", got)
	}
	// Mode bits mean nothing on Windows, EnsureDataDir sets the ACL there.
	if runtime.GOOS != "windows" {
		for path, want := range map[string]os.FileMode{config.FrpAdminHelperConf(): 0o600, config.FrpDir(): 0o700} {
			info, err := os.Stat(path)
			if err != nil {
				t.Fatal(err)
			}
			if perm := info.Mode().Perm(); perm != want {
				t.Errorf("%s mode = %o, want %o", path, perm, want)
			}
		}
	}
}

// --insecure holds for the provisioning call only: the sync config never stores INSECURE, and
// without a CA a later sync verifies the server against the system CAs.
func TestWriteSyncConfigNeverStoresInsecure(t *testing.T) {
	t.Setenv("ADMINHELPER_FRP_DIR", t.TempDir())

	if err := WriteSyncConfig(SyncConfigParams{
		AdminHelperURL: "https://srv.example",
		ServerID:       "srv-1",
		APIKey:         "key-1",
		TLS:            config.TLSOpts{Insecure: true},
	}); err != nil {
		t.Fatalf("WriteSyncConfig: %v", err)
	}

	kv, err := config.LoadKeyValue(config.FrpAdminHelperConf())
	if err != nil {
		t.Fatalf("sync config: %v", err)
	}
	want := map[string]string{
		"ADMINHELPER_URL": "https://srv.example",
		"API_KEY":         "key-1",
		"SERVER_ID":       "srv-1",
	}
	if !reflect.DeepEqual(kv, want) {
		t.Fatalf("sync config = %v, want %v", kv, want)
	}
	if _, err := os.Stat(config.FrpCACert()); !os.IsNotExist(err) {
		t.Fatalf("ca.crt written without a CA to copy (%v)", err)
	}
}

// Nothing is ever written to frp/pki anymore, so the sync config does not create it.
func TestWriteSyncConfigCreatesNoPkiDir(t *testing.T) {
	t.Setenv("ADMINHELPER_FRP_DIR", filepath.Join(t.TempDir(), "frp"))

	if err := WriteSyncConfig(SyncConfigParams{
		AdminHelperURL: "https://srv.example",
		ServerID:       "srv-1",
		APIKey:         "key-1",
	}); err != nil {
		t.Fatalf("WriteSyncConfig: %v", err)
	}

	if _, err := os.Stat(config.FrpAdminHelperConf()); err != nil {
		t.Fatalf("sync config: %v", err)
	}
	pki := filepath.Join(config.FrpDir(), "pki")
	if _, err := os.Lstat(pki); !os.IsNotExist(err) {
		t.Fatalf("%s exists after WriteSyncConfig (%v), want no pki dir", pki, err)
	}
}

// bundleToml is a server-built frpc.toml as a provisioning bundle carries it. Its identity path
// is rewritten to the agent's identity dir (setupSyncTest moves it to a temp dir), so the file on
// disk differs from the server's text by more than the preamble.
var bundleToml = []byte("serverAddr = \"1.2.3.4\"\nserverPort = 7000\n" +
	"transport.tls.certFile = \"/etc/adminhelper/identity/agent.crt\"\n\n[[proxies]]\nname = \"ssh\"\n")

// applyBundle runs Apply as a provisioning with an FRP bundle carrying toml.
func applyBundle(toml []byte) error {
	return Apply(ApplyParams{
		AdminHelperURL: "https://srv.example",
		ServerID:       "srv-1",
		APIKey:         "key-1",
		FrpConfigB64:   base64.StdEncoding.EncodeToString(toml),
		TLS:            config.TLSOpts{Insecure: true},
	})
}

// R-0398: provisioning again while frpc runs restarts it onto the new config. Apply ran only
// `enable --now` before, which leaves a running frpc on the old file.
func TestReprovisionRestartsRunningFrpcOnTheNewConfig(t *testing.T) {
	calls := setupSyncTest(t, "https://srv.example")
	writeFrpcState(t)
	calls.active = true

	if err := applyBundle(bundleToml); err != nil {
		t.Fatalf("Apply: %v", err)
	}
	if calls.restarts != 1 || calls.enables != 0 || calls.disables != 0 {
		t.Errorf("restarts = %d, enables = %d, disables = %d, want 1, 0 and 0", calls.restarts, calls.enables, calls.disables)
	}
	identity := filepath.ToSlash(config.AgentPkiDir()) + "/"
	want := localHead(t) + strings.ReplaceAll(string(bundleToml), "/etc/adminhelper/identity/", identity)
	if got, _ := os.ReadFile(config.FrpConfigFile()); string(got) != want {
		t.Errorf("frpc.toml = %q, want %q", got, want)
	}
}

// R-0398: the provisioning restarts a running frpc also when its common part stays: it may have
// enrolled a new identity, and a reload does not connect to frps anew, only a restart does.
func TestReprovisionRestartsRatherThanReload(t *testing.T) {
	calls := setupSyncTest(t, "https://unused.example")
	serveToml(t, bundleToml)
	if err := Sync(context.Background()); err != nil {
		t.Fatalf("Sync with the tunnel: %v", err)
	}

	if err := applyBundle(bundleToml); err != nil {
		t.Fatalf("Apply with unchanged tunnels: %v", err)
	}
	if calls.restarts != 1 || calls.reloads != 0 {
		t.Errorf("restarts = %d, reloads = %d, want 1 and 0", calls.restarts, calls.reloads)
	}
}

// The stored hash is the one of the bundle's text, not of the file the agent wrote (preamble,
// identity paths): it then matches the server's config-hash, and the next sync does nothing.
// Before, Apply hashed its own file, so the next sync fetched and applied the config once more.
func TestReprovisionStoresTheHashOfTheBundleText(t *testing.T) {
	calls := setupSyncTest(t, "https://srv.example")

	if err := applyBundle(bundleToml); err != nil {
		t.Fatalf("Apply: %v", err)
	}
	hash := hashConfig(bundleToml)
	if got, _ := os.ReadFile(config.FrpHashFile()); strings.TrimSpace(string(got)) != hash {
		t.Errorf("hash file = %q, want the hash of the bundle's text %q", got, hash)
	}
	if calls.enables != 1 {
		t.Fatalf("enables = %d, want 1 (frpc was stopped)", calls.enables)
	}

	srv, fetches := hashServer(t, `{"hash":"`+hash+`"}`, bundleToml)
	pointSyncAt(t, srv.URL)
	if err := Sync(context.Background()); err != nil {
		t.Fatalf("Sync after the provisioning: %v", err)
	}
	if *fetches != 0 || calls.enables != 1 || calls.restarts != 0 {
		t.Errorf("config fetches = %d, enables = %d, restarts = %d, want 0, 1 and 0", *fetches, calls.enables, calls.restarts)
	}
}

// R-0638: a systemctl that does not answer whether frpc runs fails like a start: the provisioning
// warns and removes the hash, so the next run applies the config again. It starts nothing, since
// frpc may run.
func TestReprovisionWarnsWhenSystemctlDoesNotAnswer(t *testing.T) {
	calls := setupSyncTest(t, "https://srv.example")
	isActive = func(context.Context) (bool, error) {
		return false, errors.New("systemctl is-active frpc.service: context deadline exceeded")
	}
	out := captureLog(t)

	if err := applyBundle(bundleToml); err != nil {
		t.Fatalf("Apply without an answer from systemctl: %v, want only a warning", err)
	}
	for _, want := range []string{"level=WARN", "context deadline exceeded", "next agent run tries again"} {
		if !strings.Contains(out.String(), want) {
			t.Errorf("log %q is missing %q", out.String(), want)
		}
	}
	if calls.enables != 0 || calls.restarts != 0 || calls.reloads != 0 {
		t.Errorf("enables = %d, restarts = %d, reloads = %d, want 0, 0 and 0", calls.enables, calls.restarts, calls.reloads)
	}
	if _, err := os.Stat(config.FrpHashFile()); !os.IsNotExist(err) {
		t.Errorf("hash file is there (stat: %v), want none", err)
	}
}

// Kevin, 2026-10-16: a frpc that does not start at provisioning only warns, as before; the
// provision token is spent by then. The warning names the way on, and the hash goes, so the next
// sync applies the config again, also when the stored hash already was the bundle's (provisioned
// again with unchanged tunnels). The written file is logged before the start: the desktop tunnel
// E2E greps for "frpc.toml geschrieben" and has no systemctl.
func TestReprovisionWarnsWhenStartingFrpcFails(t *testing.T) {
	cases := map[string]struct {
		running bool
		prepare func(t *testing.T)
	}{
		"provisioned again with unchanged tunnels, restart fails": {true, func(t *testing.T) {
			writeFrpcState(t)
			if err := os.WriteFile(config.FrpHashFile(), []byte(hashConfig(bundleToml)), 0644); err != nil {
				t.Fatal(err)
			}
		}},
		"first provisioning, enable fails": {false, func(*testing.T) {}},
	}
	for name, tc := range cases {
		t.Run(name, func(t *testing.T) {
			calls := setupSyncTest(t, "https://srv.example")
			calls.active = tc.running
			tc.prepare(t)
			restart, enable := restartService, enableService
			restartService = func(context.Context) error { return errors.New("systemctl failed") }
			enableService = restartService
			out := captureLog(t)

			if err := applyBundle(bundleToml); err != nil {
				t.Fatalf("Apply with a failing start: %v, want only a warning", err)
			}
			for _, want := range []string{"frpc.toml geschrieben", "level=WARN", "systemctl failed",
				"next agent run tries again", "systemctl status frpc"} {
				if !strings.Contains(out.String(), want) {
					t.Errorf("log %q is missing %q", out.String(), want)
				}
			}
			if got, _ := os.ReadFile(config.FrpConfigFile()); !bytes.HasPrefix(got, []byte(localPreamble)) {
				t.Errorf("frpc.toml = %q, want the new file", got)
			}
			if _, err := os.Stat(config.FrpHashFile()); !os.IsNotExist(err) {
				t.Errorf("hash file is still there (stat: %v), want it removed", err)
			}

			restartService, enableService = restart, enable
			srv, fetches := hashServer(t, `{"hash":"`+hashConfig(bundleToml)+`"}`, bundleToml)
			pointSyncAt(t, srv.URL)
			if err := Sync(context.Background()); err != nil {
				t.Fatalf("next Sync: %v", err)
			}
			if *fetches != 1 || calls.restarts+calls.enables != 1 {
				t.Errorf("next Sync: config fetches = %d, starts = %d, want 1 and 1", *fetches, calls.restarts+calls.enables)
			}
		})
	}
}

// A failed write still fails the provisioning: frpc does not start, and the old file and hash stay.
func TestReprovisionFailsWhenWritingTheConfigFails(t *testing.T) {
	calls := setupSyncTest(t, "https://srv.example")
	writeFrpcState(t)
	calls.active = true
	oldConfig, _ := os.ReadFile(config.FrpConfigFile())
	oldHash, _ := os.ReadFile(config.FrpHashFile())
	// A directory where the staged file goes makes the write fail on every platform.
	if err := os.Mkdir(config.FrpConfigFile()+".tmp", 0o700); err != nil {
		t.Fatal(err)
	}

	err := applyBundle(bundleToml)
	if err == nil || errors.Is(err, errFrpcService) {
		t.Fatalf("Apply = %v, want the write error", err)
	}
	if calls.restarts != 0 || calls.enables != 0 {
		t.Errorf("restarts = %d, enables = %d, want 0 and 0", calls.restarts, calls.enables)
	}
	if got, _ := os.ReadFile(config.FrpConfigFile()); string(got) != string(oldConfig) {
		t.Errorf("frpc.toml = %q, want the old %q", got, oldConfig)
	}
	if got, _ := os.ReadFile(config.FrpHashFile()); string(got) != string(oldHash) {
		t.Errorf("hash file = %q, want the old %q", got, oldHash)
	}
}

// R-0398: provisioning again without an FRP bundle (no FRP config; from an older server also no
// tunnel for the host) stops and disables the frpc of an earlier provisioning and removes
// frpc.toml, which holds the frps token, and the hash.
func TestReprovisionWithoutBundleStopsFrpcAndRemovesItsFiles(t *testing.T) {
	calls := setupSyncTest(t, "https://srv.example")
	writeFrpcState(t)
	calls.active = true

	if err := ApplyWithoutBundle(); err != nil {
		t.Fatalf("ApplyWithoutBundle: %v", err)
	}
	if calls.disables != 1 || calls.restarts != 0 || calls.enables != 0 {
		t.Errorf("disables = %d, restarts = %d, enables = %d, want 1, 0 and 0", calls.disables, calls.restarts, calls.enables)
	}
	for _, path := range []string{config.FrpConfigFile(), config.FrpHashFile()} {
		if _, err := os.Stat(path); !os.IsNotExist(err) {
			t.Errorf("%s is still there (stat: %v), want it removed", path, err)
		}
	}
}

// A frpc that does not stop at provisioning (no bundle, or a bundle without proxies) only warns
// too. frpc.toml stays for the retry, the hash goes, and the next sync stops frpc.
func TestReprovisionWarnsWhenStoppingFrpcFails(t *testing.T) {
	empty := []byte("serverAddr = \"1.2.3.4\"\n")
	cases := map[string]struct {
		provision func() error
		hashJSON  string
		toml      []byte
	}{
		"without a bundle":           {ApplyWithoutBundle, `{"hash": null}`, nil},
		"bundle without any proxies": {func() error { return applyBundle(empty) }, `{"hash":"` + hashConfig(empty) + `"}`, empty},
	}
	for name, tc := range cases {
		t.Run(name, func(t *testing.T) {
			calls := setupSyncTest(t, "https://srv.example")
			writeFrpcState(t)
			calls.active = true
			disable := disableService
			disableService = func(context.Context) error { return errors.New("systemctl failed") }
			out := captureLog(t)

			if err := tc.provision(); err != nil {
				t.Fatalf("provisioning with a failing stop: %v, want only a warning", err)
			}
			for _, want := range []string{"level=WARN", "systemctl failed", "next agent run tries again"} {
				if !strings.Contains(out.String(), want) {
					t.Errorf("log %q is missing %q", out.String(), want)
				}
			}
			if _, err := os.Stat(config.FrpConfigFile()); err != nil {
				t.Errorf("frpc.toml is gone (stat: %v), want it kept for the retry", err)
			}
			if _, err := os.Stat(config.FrpHashFile()); !os.IsNotExist(err) {
				t.Errorf("hash file is still there (stat: %v), want it removed", err)
			}

			disableService = disable
			srv, _ := hashServer(t, tc.hashJSON, tc.toml)
			pointSyncAt(t, srv.URL)
			if err := Sync(context.Background()); err != nil {
				t.Fatalf("next Sync: %v", err)
			}
			if _, err := os.Stat(config.FrpConfigFile()); calls.disables != 1 || !os.IsNotExist(err) {
				t.Errorf("next Sync: disables = %d, frpc.toml stat = %v, want 1 and removed", calls.disables, err)
			}
		})
	}
}

// A file that cannot be removed is no service failure: the provisioning fails, the hash stays.
func TestReprovisionWithoutBundleFailsWhenRemovingTheConfigFails(t *testing.T) {
	setupSyncTest(t, "https://srv.example")
	writeFrpcState(t)
	oldHash, _ := os.ReadFile(config.FrpHashFile())
	// A non-empty directory in place of frpc.toml cannot be removed on any platform.
	if err := os.Remove(config.FrpConfigFile()); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Join(config.FrpConfigFile(), "x"), 0o700); err != nil {
		t.Fatal(err)
	}

	err := ApplyWithoutBundle()
	if err == nil || errors.Is(err, errFrpcService) {
		t.Fatalf("ApplyWithoutBundle = %v, want the remove error", err)
	}
	if got, _ := os.ReadFile(config.FrpHashFile()); string(got) != string(oldHash) {
		t.Errorf("hash file = %q, want the old %q", got, oldHash)
	}
}

// captureLog sends the log of the test to the returned buffer.
func captureLog(t *testing.T) *bytes.Buffer {
	t.Helper()
	var buf bytes.Buffer
	prev, prevOut, prevFlags := slog.Default(), log.Writer(), log.Flags()
	slog.SetDefault(slog.New(slog.NewTextHandler(&buf, nil)))
	// SetDefault also redirects the log package, which restoring the slog default does not undo.
	t.Cleanup(func() { slog.SetDefault(prev); log.SetOutput(prevOut); log.SetFlags(prevFlags) })
	return &buf
}
