// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package enroll

import (
	"context"
	"crypto/ecdsa"
	"crypto/tls"
	"crypto/x509"
	"encoding/pem"
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"testing"
	"time"
)

// R-0384: LockIdentity serializes the operations that replace the identity.

func TestLockIdentityWaitsUntilTheHolderUnlocks(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "identity") // not pre-created -> LockIdentity must mkdir
	unlock, err := LockIdentity(context.Background(), dir)
	if err != nil {
		t.Fatalf("LockIdentity: %v", err)
	}
	type result struct {
		unlock func()
		err    error
	}
	second := make(chan result, 1)
	go func() {
		u, err := LockIdentity(context.Background(), dir)
		second <- result{u, err}
	}()

	select {
	case r := <-second:
		if r.err == nil {
			r.unlock()
		}
		unlock()
		t.Fatalf("a second LockIdentity returned while the first held the lock (err: %v)", r.err)
	case <-time.After(500 * time.Millisecond):
	}

	unlock()
	select {
	case r := <-second:
		if r.err != nil {
			t.Fatalf("second LockIdentity: %v", r.err)
		}
		r.unlock()
	case <-time.After(10 * time.Second):
		t.Fatal("the second LockIdentity did not return after the first unlocked")
	}
}

// shortenLockWait sets how long LockIdentity waits for the lock, for the test.
func shortenLockWait(t *testing.T, wait time.Duration) {
	t.Helper()
	orig := identityLockWait
	identityLockWait = wait
	t.Cleanup(func() { identityLockWait = orig })
}

// A lock that is not released holds up LockIdentity for its wait, not for good.
func TestLockIdentityGivesUpAfterItsWait(t *testing.T) {
	const wait = 300 * time.Millisecond
	shortenLockWait(t, wait)
	dir := t.TempDir()
	unlock, err := LockIdentity(context.Background(), dir)
	if err != nil {
		t.Fatalf("LockIdentity: %v", err)
	}
	defer unlock()

	start := time.Now()
	second := make(chan error, 1)
	go func() {
		u, err := LockIdentity(context.Background(), dir)
		if err == nil {
			u()
		}
		second <- err
	}()
	select {
	case err := <-second:
		if err == nil {
			t.Fatal("a second LockIdentity took the lock while the first held it")
		}
		if elapsed := time.Since(start); elapsed < wait {
			t.Fatalf("LockIdentity gave up after %s, before its wait of %s", elapsed, wait)
		}
		if lockFile := filepath.Join(dir, LockFileName); !strings.Contains(err.Error(), lockFile) {
			t.Fatalf("the error does not name the lock file %s: %v", lockFile, err)
		}
	case <-time.After(10 * time.Second):
		t.Fatal("LockIdentity did not give up after its wait")
	}
}

// The end of the ctx ends the wait for a held lock, long before identityLockWait.
func TestLockIdentityEndsWithTheContext(t *testing.T) {
	dir := t.TempDir()
	unlock, err := LockIdentity(context.Background(), dir)
	if err != nil {
		t.Fatalf("LockIdentity: %v", err)
	}
	defer unlock()

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	second := make(chan error, 1)
	go func() {
		u, err := LockIdentity(ctx, dir)
		if err == nil {
			u()
		}
		second <- err
	}()
	select {
	case err := <-second:
		t.Fatalf("a second LockIdentity returned (%v) while the first held the lock", err)
	case <-time.After(100 * time.Millisecond):
	}

	cancel()
	select {
	case err := <-second:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("want an error that wraps context.Canceled, got %v", err)
		}
		if lockFile := filepath.Join(dir, LockFileName); !strings.Contains(err.Error(), lockFile) {
			t.Fatalf("the error does not name the lock file %s: %v", lockFile, err)
		}
	case <-time.After(2 * time.Second):
		t.Fatalf("LockIdentity did not end with its ctx (identityLockWait %s)", identityLockWait)
	}
}

func TestLockIdentityFailsWhenTheLockFileCannotBeOpened(t *testing.T) {
	dir := t.TempDir()
	if err := os.Mkdir(filepath.Join(dir, LockFileName), 0700); err != nil {
		t.Fatal(err)
	}
	unlock, err := LockIdentity(context.Background(), dir)
	if err == nil {
		unlock()
		t.Fatal("LockIdentity took a lock on a directory named like the lock file")
	}
}

// On Windows LockIdentity takes only a lock file that SYSTEM or the Administrators own.
func TestLockOwnerAllowed(t *testing.T) {
	cases := []struct {
		name string
		sid  string
		want bool
	}{
		{"SYSTEM", "S-1-5-18", true},
		{"Administrators", "S-1-5-32-544", true},
		{"Users", "S-1-5-32-545", false},
		{"a local user", "S-1-5-21-1111111111-2222222222-3333333333-1001", false},
		{"Everyone", "S-1-1-0", false},
		{"Administrators with a suffix", "S-1-5-32-5440", false},
		{"no owner", "", false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := lockOwnerAllowed(tc.sid); got != tc.want {
				t.Fatalf("lockOwnerAllowed(%q) = %v, want %v", tc.sid, got, tc.want)
			}
		})
	}
}

// storableIdentity is a key with a self-signed cert for it, in the shape Store takes.
func storableIdentity(t *testing.T, cn string) (*ecdsa.PrivateKey, *IssueResponse) {
	t.Helper()
	now := time.Now()
	certPEM, keyPEM := selfSigned(t, cn, now.Add(-time.Hour), now.Add(time.Hour))
	block, _ := pem.Decode(keyPEM)
	key, err := x509.ParsePKCS8PrivateKey(block.Bytes)
	if err != nil {
		t.Fatal(err)
	}
	return key.(*ecdsa.PrivateKey), &IssueResponse{Cert: string(certPEM), Fullchain: string(certPEM), Chain: string(certPEM)}
}

// Store renames key, cert and CA one after another. Two operations that store at the
// same time without the lock interleave those renames and leave the key of one with the
// cert of the other: the probe on main@aa7decf6 counted 561, 473 and 531 of 3000.
func TestLockIdentityKeepsConcurrentStoresAMatchingPair(t *testing.T) {
	keyA, respA := storableIdentity(t, "srv-a")
	keyB, respB := storableIdentity(t, "srv-b")
	trials := 3000
	if runtime.GOOS == "windows" {
		// Every LockIdentity and Store secures the directory again there (EnsureDataDir:
		// owner, ACL and each entry, through handles), so a trial costs far more than on
		// Linux: 3000 trials would outlast the test timeout. The Linux run is the proof
		// of the race.
		trials = 20
	}
	mismatches := 0
	for i := 0; i < trials; i++ {
		dir := t.TempDir()
		var wg sync.WaitGroup
		start := make(chan struct{})
		for _, id := range []struct {
			key  *ecdsa.PrivateKey
			resp *IssueResponse
		}{{keyA, respA}, {keyB, respB}} {
			wg.Add(1)
			go func() {
				defer wg.Done()
				<-start
				unlock, err := LockIdentity(context.Background(), dir)
				if err != nil {
					t.Error(err)
					return
				}
				defer unlock()
				if err := Store(dir, id.key, id.resp); err != nil {
					t.Error(err)
				}
			}()
		}
		close(start)
		wg.Wait()
		if _, err := tls.LoadX509KeyPair(CertPath(dir), KeyPath(dir)); err != nil {
			mismatches++
		}
	}
	if mismatches > 0 {
		t.Fatalf("want a matching key/cert pair after every pair of locked Stores, got %d mismatches in %d trials", mismatches, trials)
	}
}
