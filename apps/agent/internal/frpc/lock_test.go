// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package frpc

import (
	"context"
	"errors"
	"maps"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	"adminhelper-agent/internal/config"
	"adminhelper-agent/internal/enroll"
)

// R-0641: a run of the agent (Sync) and a provisioning (Apply) change frpc's state only under the
// frpc lock, so that they never write frpc.toml, the hashes, admin.conf or the sync config, or
// start and stop frpc, at the same time.

// holdFrpcLock takes the frpc lock the way a second process would and returns the function that
// releases it; the end of the test releases it at the latest.
func holdFrpcLock(t *testing.T) (release func()) {
	t.Helper()
	unlock, err := enroll.LockFile(context.Background(), frpcLockFile(), time.Second)
	if err != nil {
		t.Fatalf("hold the frpc lock: %v", err)
	}
	var once sync.Once
	release = func() { once.Do(unlock) }
	t.Cleanup(release)
	return release
}

// serveTomlSignaling points the sync at a server that sends toml under its hash, and returns a
// channel that gets a value once the server has sent the config: from there on the sync only
// secures the FRP directory before it takes the lock.
func serveTomlSignaling(t *testing.T, toml []byte) <-chan struct{} {
	t.Helper()
	served := make(chan struct{}, 1)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case strings.HasSuffix(r.URL.Path, "/config-hash"):
			_, _ = w.Write([]byte(`{"hash":"` + hashConfig(toml) + `"}`))
		case strings.HasSuffix(r.URL.Path, "/config"):
			_, _ = w.Write(toml)
			select {
			case served <- struct{}{}:
			default:
			}
		default:
			t.Errorf("unexpected request: %s", r.URL.Path)
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	t.Cleanup(srv.Close)
	pointSyncAt(t, srv.URL)
	return served
}

// lockedCall runs call in a goroutine while the test holds the frpc lock. fail releases the
// lock and waits for call before it fails the test, so that call does not outlive the test (it
// would write into the removed temp dirs and race with the restored seams).
type lockedCall struct {
	t       *testing.T
	release func()
	res     chan error
}

func startLocked(t *testing.T, release func(), call func() error) *lockedCall {
	c := &lockedCall{t: t, release: release, res: make(chan error, 1)}
	go func() { c.res <- call() }()
	return c
}

func (c *lockedCall) fail(format string, args ...any) {
	c.t.Helper()
	c.release()
	select {
	case <-c.res:
	case <-time.After(10 * time.Second):
	}
	c.t.Fatalf(format, args...)
}

// stillWaiting fails the test if call returns within d.
func (c *lockedCall) stillWaiting(d time.Duration) {
	c.t.Helper()
	select {
	case err := <-c.res:
		c.release()
		c.t.Fatalf("returned (%v) while the test held the frpc lock", err)
	case <-time.After(d):
	}
}

// goesOn releases the lock and fails the test unless call then returns nil within 5 s.
func (c *lockedCall) goesOn(what string) {
	c.t.Helper()
	c.release()
	select {
	case err := <-c.res:
		if err != nil {
			c.t.Fatalf("%s after the lock was released: %v", what, err)
		}
	case <-time.After(5 * time.Second):
		c.t.Fatalf("%s did not go on after the lock was released", what)
	}
}

// A sync with a changed hash waits for the lock: while another holds it, nothing in the FRP
// directory changes and frpc is not started; once it is released, the sync goes on.
func TestFrpcLockSyncWaits(t *testing.T) {
	calls := setupSyncTest(t, "https://unused.example")
	served := serveTomlSignaling(t, tunnelToml)
	release := holdFrpcLock(t)
	files := frpFiles(t)

	c := startLocked(t, release, func() error { return Sync(context.Background()) })
	select {
	case <-served:
	case <-time.After(10 * time.Second):
		c.fail("the sync did not fetch the config")
	}
	c.stillWaiting(300 * time.Millisecond)
	if got := frpFiles(t); !maps.Equal(got, files) {
		c.fail("the FRP directory holds %q while the lock is held, want it unchanged %q", got, files)
	}

	c.goesOn("Sync")
	if got, want := readFile(t, config.FrpConfigFile()), localHead(t)+string(tunnelToml); got != want {
		t.Errorf("frpc.toml = %q, want %q", got, want)
	}
	if calls.enables != 1 {
		t.Errorf("enables = %d, want 1", calls.enables)
	}
}

// The end of its ctx ends a sync's wait for the lock, long before frpcLockWait: the error names
// the lock file, and the sync has changed nothing.
func TestFrpcLockSyncEndsWithTheContext(t *testing.T) {
	calls := setupSyncTest(t, "https://unused.example")
	served := serveTomlSignaling(t, tunnelToml)
	release := holdFrpcLock(t)
	files, actions := frpFiles(t), *calls

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	c := startLocked(t, release, func() error { return Sync(ctx) })
	select {
	case <-served:
	case <-time.After(10 * time.Second):
		c.fail("the sync did not fetch the config")
	}
	c.stillWaiting(100 * time.Millisecond)

	cancel()
	select {
	case err := <-c.res:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("Sync = %v, want an error that wraps context.Canceled", err)
		}
		if !strings.Contains(err.Error(), frpcLockFile()) {
			t.Fatalf("the error does not name the lock file %s: %v", frpcLockFile(), err)
		}
	case <-time.After(2 * time.Second):
		c.fail("Sync did not end with its ctx (frpcLockWait %s)", frpcLockWait)
	}
	if got := frpFiles(t); !maps.Equal(got, files) {
		t.Errorf("the FRP directory holds %q, want it unchanged %q", got, files)
	}
	if *calls != actions {
		t.Errorf("frpc service state %+v, want it unchanged %+v (no start, stop or reload)", *calls, actions)
	}
}

// A provisioning with an FRP bundle waits for the lock from securing the FRP directory on: the
// sync config and frpc.toml are written only after the lock is released.
func TestFrpcLockApplyWaits(t *testing.T) {
	calls := setupSyncTest(t, "https://unused.example")
	release := holdFrpcLock(t)
	files := frpFiles(t)

	c := startLocked(t, release, func() error { return applyBundle(bundleToml) })
	c.stillWaiting(300 * time.Millisecond)
	if got := frpFiles(t); !maps.Equal(got, files) {
		c.fail("the FRP directory holds %q while the lock is held, want it unchanged %q", got, files)
	}

	c.goesOn("Apply")
	kv, err := config.LoadKeyValue(config.FrpAdminHelperConf())
	if err != nil || kv["API_KEY"] != "key-1" {
		t.Errorf("sync config = %v (%v), want the API key of the provisioning", kv, err)
	}
	if _, err := os.Stat(config.FrpConfigFile()); err != nil {
		t.Errorf("frpc.toml after the lock was released: %v", err)
	}
	if calls.enables != 1 {
		t.Errorf("enables = %d, want 1", calls.enables)
	}
}

// A provisioning without an FRP bundle writes the sync config under the lock as well: it is
// written only after the lock is released.
func TestFrpcLockWriteSyncConfigWaits(t *testing.T) {
	setupSyncTest(t, "https://unused.example")
	release := holdFrpcLock(t)
	files := frpFiles(t)

	c := startLocked(t, release, func() error {
		return WriteSyncConfig(SyncConfigParams{AdminHelperURL: "https://srv.example", ServerID: "srv-1", APIKey: "key-1"})
	})
	c.stillWaiting(300 * time.Millisecond)
	if got := frpFiles(t); !maps.Equal(got, files) {
		c.fail("the FRP directory holds %q while the lock is held, want it unchanged %q", got, files)
	}

	c.goesOn("WriteSyncConfig")
	kv, err := config.LoadKeyValue(config.FrpAdminHelperConf())
	if err != nil || kv["API_KEY"] != "key-1" {
		t.Errorf("sync config = %v (%v), want the API key of the provisioning", kv, err)
	}
}

// A provisioning without an FRP bundle stops the frpc of an earlier one only under the lock:
// while it is held, frpc.toml and the hash stay; once it is released, frpc stops and both go.
func TestFrpcLockApplyWithoutBundleWaits(t *testing.T) {
	calls := setupSyncTest(t, "https://unused.example")
	writeFrpcState(t)
	calls.active = true
	release := holdFrpcLock(t)
	files := frpFiles(t)

	c := startLocked(t, release, ApplyWithoutBundle)
	c.stillWaiting(300 * time.Millisecond)
	if got := frpFiles(t); !maps.Equal(got, files) {
		c.fail("the FRP directory holds %q while the lock is held, want it unchanged %q", got, files)
	}

	c.goesOn("ApplyWithoutBundle")
	if calls.disables != 1 {
		t.Errorf("disables = %d, want 1", calls.disables)
	}
	for _, path := range []string{config.FrpConfigFile(), config.FrpHashFile()} {
		if _, err := os.Stat(path); !os.IsNotExist(err) {
			t.Errorf("%s is still there (stat: %v), want it removed", path, err)
		}
	}
}

// A sync on a null hash with frpc.toml in place stops frpc only under the lock: while it is
// held, frpc.toml and the hash stay; once it is released, frpc stops and both go.
func TestFrpcLockSyncNullHashWaits(t *testing.T) {
	srv, _ := hashServer(t, `{"hash": null}`, nil)
	calls := setupSyncTest(t, srv.URL)
	writeFrpcState(t)
	calls.active = true
	release := holdFrpcLock(t)
	files := frpFiles(t)

	c := startLocked(t, release, func() error { return Sync(context.Background()) })
	c.stillWaiting(300 * time.Millisecond)
	if got := frpFiles(t); !maps.Equal(got, files) {
		c.fail("the FRP directory holds %q while the lock is held, want it unchanged %q", got, files)
	}

	c.goesOn("Sync")
	if calls.disables != 1 {
		t.Errorf("disables = %d, want 1", calls.disables)
	}
	for _, path := range []string{config.FrpConfigFile(), config.FrpHashFile()} {
		if _, err := os.Stat(path); !os.IsNotExist(err) {
			t.Errorf("%s is still there (stat: %v), want it removed", path, err)
		}
	}
}

// A run without a change takes no lock: it neither waits for one that another holds nor fails on
// it, for the same hash with frpc running on a tunnel and for a null hash with nothing left.
func TestFrpcLockUnchangedRunTakesNoLock(t *testing.T) {
	t.Run("same hash, frpc runs on a tunnel", func(t *testing.T) {
		calls := setupSyncTest(t, "https://unused.example")
		fetches := serveToml(t, tunnelToml)
		if err := Sync(context.Background()); err != nil {
			t.Fatalf("Sync with the first tunnel: %v", err)
		}
		actions := *calls
		release := holdFrpcLock(t)

		c := startLocked(t, release, func() error { return Sync(context.Background()) })
		select {
		case err := <-c.res:
			if err != nil {
				t.Fatalf("Sync with the same hash: %v", err)
			}
		case <-time.After(5 * time.Second):
			c.fail("Sync with the same hash waited for the frpc lock (frpcLockWait %s)", frpcLockWait)
		}
		if *calls != actions || *fetches != 1 {
			t.Errorf("frpc service state %+v, config fetches %d, want %+v and 1", *calls, *fetches, actions)
		}
	})
	t.Run("null hash, nothing left", func(t *testing.T) {
		srv, _ := hashServer(t, `{"hash": null}`, nil)
		calls := setupSyncTest(t, srv.URL)
		release := holdFrpcLock(t)

		c := startLocked(t, release, func() error { return Sync(context.Background()) })
		select {
		case err := <-c.res:
			if err != nil {
				t.Fatalf("Sync with a null hash: %v", err)
			}
		case <-time.After(5 * time.Second):
			c.fail("Sync with a null hash waited for the frpc lock (frpcLockWait %s)", frpcLockWait)
		}
		if calls.disables != 0 {
			t.Errorf("disables = %d, want 0", calls.disables)
		}
	})
}
