// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package enroll

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"adminhelper-agent/internal/config"
)

// LockFileName is the file in the identity directory whose exclusive lock
// serializes the operations that replace the identity (R-0384).
const LockFileName = "agent.lock"

// identityLockWait is how long LockIdentity waits for the lock before it gives up;
// tests shorten it. A lock that another process does not release must hold up
// neither a provisioning nor the service cycle for good. The operations that hold
// it wait for one request to the issuer, 30 s at most.
var identityLockWait = 60 * time.Second

// maxLockPause caps the pause between two attempts to take the lock. The first
// pauses are short: a Store under the lock takes about a millisecond.
const maxLockPause = 100 * time.Millisecond

// The well-known SIDs of LocalSystem and of the built-in Administrators group.
const (
	systemSID         = "S-1-5-18"
	administratorsSID = "S-1-5-32-544"
)

// LockIdentity waits for the exclusive lock on the identity in dir and returns the
// function that releases it. An operation that replaces the identity holds it from
// its first read of the identity to the commit of the new one: Store renames key,
// cert and CA one after another, and two commits that interleave leave the key of
// one with the cert of the other. The lock belongs to the open file, so a second
// LockIdentity in the same process waits as well. It waits at most identityLockWait,
// or until ctx ends, and then returns an error that names the lock file.
func LockIdentity(ctx context.Context, dir string) (unlock func(), err error) {
	if err := config.EnsureDataDir(dir); err != nil {
		return nil, fmt.Errorf("create the identity directory: %w", err)
	}
	unlock, err = LockFile(ctx, filepath.Join(dir, LockFileName), identityLockWait)
	if err != nil {
		return nil, fmt.Errorf("lock the identity: %w", err)
	}
	return unlock, nil
}

// LockFile waits for the exclusive lock on the file at path, which it creates if it
// is missing, and returns the function that releases it. It only creates the file:
// the caller secures the directory first, in the same call (EnsureDataDir). On
// Windows it takes only a lock file that SYSTEM or the Administrators own. The lock
// belongs to the open file, so a second LockFile on path in the same process waits
// as well. It waits at most wait, or until ctx ends, and then returns an error that
// names path.
func LockFile(ctx context.Context, path string, wait time.Duration) (unlock func(), err error) {
	f, err := openLockFile(path)
	if err != nil {
		return nil, fmt.Errorf("open the lock file: %w", err)
	}
	if err := waitForLock(ctx, f, path, wait); err != nil {
		_ = f.Close()
		return nil, err
	}
	return func() {
		_ = unlockFile(f)
		_ = f.Close()
	}, nil
}

// waitForLock tries to lock f until it gets the lock, wait has passed or ctx has
// ended. The error for an ended ctx wraps ctx.Err().
func waitForLock(ctx context.Context, f *os.File, path string, wait time.Duration) error {
	deadline := time.Now().Add(wait)
	pause := time.Millisecond
	for {
		locked, err := tryLockFile(f)
		if err != nil || locked {
			return err
		}
		if !time.Now().Before(deadline) {
			return fmt.Errorf("%s is still locked after %s", path, wait)
		}
		timer := time.NewTimer(pause)
		select {
		case <-ctx.Done():
			timer.Stop()
			return fmt.Errorf("stopped waiting for %s: %w", path, ctx.Err())
		case <-timer.C:
		}
		pause = min(2*pause, maxLockPause)
	}
}

// lockOwnerAllowed reports whether LockFile takes a lock file whose owner is the
// SID sid (string form). Only Windows asks: the agent creates the lock file owned by
// the Administrators there, and one whose owner is neither SYSTEM nor the
// Administrators is not a lock file the agent created.
func lockOwnerAllowed(sid string) bool {
	return sid == systemSID || sid == administratorsSID
}
