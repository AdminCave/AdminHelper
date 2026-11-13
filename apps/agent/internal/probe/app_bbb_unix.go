// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux || freebsd

package probe

import (
	"errors"
	"os"
	"path/filepath"

	"golang.org/x/sys/unix"
)

// dirFlags open a directory to list it and nothing else: for O_DIRECTORY the kernel refuses a FIFO or
// a device before it opens it, so the view neither waits for a writer nor acts on a device.
const dirFlags = unix.O_RDONLY | unix.O_DIRECTORY | unix.O_CLOEXEC

// openDir opens the directory name to list it: the path name when parent is nil, else name below
// parent without following a link there. A link there is errNotDir, as is any other file that is no
// directory.
func openDir(parent *os.File, name string) (*os.File, error) {
	if parent == nil {
		f, err := os.OpenFile(name, dirFlags, 0)
		return f, notDir(err)
	}
	conn, err := parent.SyscallConn()
	if err != nil {
		return nil, err
	}
	fd, openErr := -1, error(nil)
	if err := conn.Control(func(pfd uintptr) {
		fd, openErr = unix.Openat(int(pfd), name, dirFlags|unix.O_NOFOLLOW, 0)
	}); err != nil {
		return nil, err
	}
	if openErr != nil {
		return nil, notDir(openErr)
	}
	return os.NewFile(uintptr(fd), filepath.Join(parent.Name(), name)), nil
}

// notDir makes errNotDir of the errors an open gets for a file that is no directory: ENOTDIR, which
// Linux also returns for a link it does not follow, ELOOP (POSIX) and EMLINK (FreeBSD) for the link.
func notDir(err error) error {
	if errors.Is(err, unix.ENOTDIR) || errors.Is(err, unix.ELOOP) || errors.Is(err, unix.EMLINK) {
		return errNotDir
	}
	return err
}
