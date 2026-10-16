// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package enroll

import (
	"os"

	"golang.org/x/sys/windows"
)

// allBytes is the length of the locked range, low and high word: the whole file.
const allBytes = ^uint32(0)

// lockFile waits for an exclusive lock on f. LockFileEx locks belong to the handle,
// so a second open in the same process waits as well. The handle does synchronous
// I/O, but LockFileEx still wants an OVERLAPPED: it carries the start of the range,
// zero here.
func lockFile(f *os.File) error {
	return windows.LockFileEx(windows.Handle(f.Fd()), windows.LOCKFILE_EXCLUSIVE_LOCK, 0, allBytes, allBytes, new(windows.Overlapped))
}

// unlockFile releases the lock on f.
func unlockFile(f *os.File) error {
	return windows.UnlockFileEx(windows.Handle(f.Fd()), 0, allBytes, allBytes, new(windows.Overlapped))
}
