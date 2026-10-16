// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package enroll

import (
	"os"

	"golang.org/x/sys/unix"
)

// lockFile waits for an exclusive flock on f. flock belongs to the open file, not
// to the process (unlike an fcntl lock), which is what makes a second open in the
// same process wait.
func lockFile(f *os.File) error {
	for {
		// A signal can interrupt the wait; the Go toolchain's own file lock retries too.
		if err := unix.Flock(int(f.Fd()), unix.LOCK_EX); err != unix.EINTR {
			return err
		}
	}
}

// unlockFile releases the flock on f.
func unlockFile(f *os.File) error {
	return unix.Flock(int(f.Fd()), unix.LOCK_UN)
}
