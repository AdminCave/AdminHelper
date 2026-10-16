// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package enroll

import (
	"crypto/ecdsa"
	"crypto/tls"
	"crypto/x509"
	"encoding/pem"
	"path/filepath"
	"runtime"
	"sync"
	"testing"
	"time"
)

// R-0384: LockIdentity serializes the operations that replace the identity.

func TestLockIdentityWaitsUntilTheHolderUnlocks(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "identity") // not pre-created -> LockIdentity must mkdir
	unlock, err := LockIdentity(dir)
	if err != nil {
		t.Fatalf("LockIdentity: %v", err)
	}
	type result struct {
		unlock func()
		err    error
	}
	second := make(chan result, 1)
	go func() {
		u, err := LockIdentity(dir)
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
		// SecureDir starts icacls twice there, about 80 ms per Store in CI: 3000 trials
		// would outlast the test timeout. The Linux run is the proof of the race.
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
				unlock, err := LockIdentity(dir)
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
