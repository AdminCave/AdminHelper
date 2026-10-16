// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package enroll

import (
	"os"

	"golang.org/x/sys/unix"
)

// openLockFile opens the lock file at path and creates it if it is missing.
func openLockFile(path string) (*os.File, error) {
	return os.OpenFile(path, os.O_RDWR|os.O_CREATE, 0600)
}

// tryLockFile takes an exclusive flock on f without waiting and reports whether it
// got it. flock belongs to the open file, not to the process (unlike an fcntl lock),
// which is what makes a second open in the same process wait.
func tryLockFile(f *os.File) (bool, error) {
	switch err := unix.Flock(int(f.Fd()), unix.LOCK_EX|unix.LOCK_NB); err {
	case nil:
		return true, nil
	case unix.EWOULDBLOCK, unix.EINTR:
		return false, nil
	default:
		return false, err
	}
}

// unlockFile releases the flock on f.
func unlockFile(f *os.File) error {
	return unix.Flock(int(f.Fd()), unix.LOCK_UN)
}
