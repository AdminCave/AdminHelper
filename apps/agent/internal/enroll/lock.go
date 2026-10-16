// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package enroll

import (
	"fmt"
	"os"
	"path/filepath"

	"adminhelper-agent/internal/config"
)

// LockFileName is the file in the identity directory whose exclusive lock
// serializes the operations that replace the identity (R-0384).
const LockFileName = "agent.lock"

// LockIdentity waits for the exclusive lock on the identity in dir and returns the
// function that releases it. An operation that replaces the identity holds it from
// its first read of the identity to the commit of the new one: Store renames key,
// cert and CA one after another, and two commits that interleave leave the key of
// one with the cert of the other. The lock belongs to the open file, so a second
// LockIdentity in the same process waits as well.
func LockIdentity(dir string) (unlock func(), err error) {
	if err := os.MkdirAll(dir, 0700); err != nil {
		return nil, fmt.Errorf("create the identity directory: %w", err)
	}
	_ = config.SecureDir(dir)
	f, err := os.OpenFile(filepath.Join(dir, LockFileName), os.O_RDWR|os.O_CREATE, 0600)
	if err != nil {
		return nil, fmt.Errorf("open the identity lock: %w", err)
	}
	if err := lockFile(f); err != nil {
		_ = f.Close()
		return nil, fmt.Errorf("lock the identity: %w", err)
	}
	return func() {
		_ = unlockFile(f)
		_ = f.Close()
	}, nil
}
