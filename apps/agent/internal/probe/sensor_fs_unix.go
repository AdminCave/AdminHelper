// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux || freebsd

package probe

import (
	"errors"
	"fmt"
	"io/fs"
	"os"

	"golang.org/x/sys/unix"
)

// dirStatfs opens the directory name (below root unless root is nil; dirFlags: no FIFO, no device) and
// asks statfs of its file system. Its errors call it shown.
func dirStatfs(root *os.Root, name, shown string) (fsUsage, error) {
	var d *os.File
	var err error
	if root == nil {
		d, err = openDir(nil, name)
	} else {
		d, err = root.OpenFile(name, dirFlags, 0)
		err = notDir(err)
	}
	switch {
	case errors.Is(err, errNotDir):
		return fsUsage{}, fmt.Errorf("%s is %w", shown, errNotDir)
	case errors.Is(err, fs.ErrNotExist):
		return fsUsage{}, fmt.Errorf("%s does not exist", shown)
	case err != nil:
		return fsUsage{}, fmt.Errorf("%s cannot be read: %v", shown, cause(err))
	}
	defer d.Close()
	var st unix.Statfs_t
	if err := unix.Fstatfs(int(d.Fd()), &st); err != nil {
		return fsUsage{}, fmt.Errorf("the file system of %s cannot be read: %v", shown, err)
	}
	// The field types differ between Linux and FreeBSD (Bavail and Ffree are signed there, negative when
	// root wrote into its reserve).
	bsize, inodes := uint64(st.Bsize), uint64(st.Files)
	return fsUsage{
		total:      uint64(st.Blocks) * bsize,
		free:       min(uint64(st.Bfree), uint64(st.Blocks)) * bsize,
		avail:      uint64(max(int64(st.Bavail), 0)) * bsize,
		inodes:     inodes,
		inodesFree: min(uint64(max(int64(st.Ffree), 0)), inodes),
	}, nil
}
