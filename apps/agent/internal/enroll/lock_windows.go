// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package enroll

import (
	"fmt"
	"os"
	"unsafe"

	"golang.org/x/sys/windows"
)

// allBytes is the length of the locked range, low and high word: the whole file.
const allBytes = ^uint32(0)

// openLockFile opens the lock file at path, creates it if it is missing and takes it
// only if SYSTEM or the Administrators own it. It creates the file owned by the
// Administrators: the default owner of a token depends on the account and on local
// policy, and the provisioning and the service may run as different accounts. The
// DACL is inherited from the directory of path, as with os.OpenFile.
func openLockFile(path string) (*os.File, error) {
	sd, err := windows.SecurityDescriptorFromString("O:BA")
	if err != nil {
		return nil, err
	}
	name, err := windows.UTF16PtrFromString(path)
	if err != nil {
		return nil, err
	}
	sa := windows.SecurityAttributes{SecurityDescriptor: sd}
	sa.Length = uint32(unsafe.Sizeof(sa))
	// Access and share mode as os.OpenFile(path, os.O_RDWR|os.O_CREATE, 0600) opens it.
	h, err := windows.CreateFile(name, windows.GENERIC_READ|windows.GENERIC_WRITE,
		windows.FILE_SHARE_READ|windows.FILE_SHARE_WRITE, &sa, windows.OPEN_ALWAYS, windows.FILE_ATTRIBUTE_NORMAL, 0)
	if err != nil {
		return nil, &os.PathError{Op: "open", Path: path, Err: err}
	}
	f := os.NewFile(uintptr(h), path)
	if err := checkLockOwner(h, path); err != nil {
		_ = f.Close()
		return nil, err
	}
	return f, nil
}

// checkLockOwner returns an error unless SYSTEM or the Administrators own the file h.
func checkLockOwner(h windows.Handle, path string) error {
	sd, err := windows.GetSecurityInfo(h, windows.SE_FILE_OBJECT, windows.OWNER_SECURITY_INFORMATION)
	if err != nil {
		return fmt.Errorf("read the owner of %s: %w", path, err)
	}
	owner, _, err := sd.Owner()
	if err != nil {
		return fmt.Errorf("read the owner of %s: %w", path, err)
	}
	if sid := owner.String(); !lockOwnerAllowed(sid) {
		return fmt.Errorf("%s is owned by %q, not by SYSTEM or the Administrators", path, sid)
	}
	return nil
}

// tryLockFile takes an exclusive lock on f without waiting and reports whether it got
// it. LockFileEx locks belong to the handle, so a second open in the same process
// waits as well. The handle does synchronous I/O, but LockFileEx still wants an
// OVERLAPPED: it carries the start of the range, zero here.
func tryLockFile(f *os.File) (bool, error) {
	err := windows.LockFileEx(windows.Handle(f.Fd()), windows.LOCKFILE_EXCLUSIVE_LOCK|windows.LOCKFILE_FAIL_IMMEDIATELY,
		0, allBytes, allBytes, new(windows.Overlapped))
	switch err {
	case nil:
		return true, nil
	case windows.ERROR_LOCK_VIOLATION:
		return false, nil
	default:
		return false, err
	}
}

// unlockFile releases the lock on f.
func unlockFile(f *os.File) error {
	return windows.UnlockFileEx(windows.Handle(f.Fd()), 0, allBytes, allBytes, new(windows.Overlapped))
}
