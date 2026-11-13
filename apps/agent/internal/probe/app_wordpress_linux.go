// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package probe

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"strconv"

	"golang.org/x/sys/unix"
)

// reopenChecked opens for reading the very file p holds as a path, through /proc/self/fd: a file put
// at its name since p was opened is never opened. O_NONBLOCK fails the open at once where a lease on
// the file would hold it up.
var reopenChecked = func(p *os.File) (*os.File, error) {
	return os.OpenFile("/proc/self/fd/"+strconv.Itoa(int(p.Fd())), os.O_RDONLY|unix.O_NONBLOCK, 0)
}

// openRegular opens the regular file name below root for reading; its errors call it shown. It opens
// name as a path first (O_PATH, to which os.Root adds O_NOFOLLOW), so a FIFO, a device or a link at
// name is never opened for reading, and reads only the file it checked.
func openRegular(root *os.Root, name, shown string) (*os.File, error) {
	p, err := root.OpenFile(name, unix.O_PATH, 0)
	switch {
	case errors.Is(err, fs.ErrNotExist):
		return nil, fmt.Errorf("it holds no %s", shown)
	case err != nil:
		return nil, fmt.Errorf("%s cannot be read: %v", shown, cause(err))
	}
	defer p.Close()
	if fi, err := p.Stat(); err != nil || !fi.Mode().IsRegular() {
		return nil, fmt.Errorf("%s is no regular file", shown)
	}
	if err := refuseKernelFile(p, shown); err != nil {
		return nil, err
	}
	f, err := reopenChecked(p)
	if err != nil {
		return nil, fmt.Errorf("%s cannot be read: %v", shown, cause(err))
	}
	return f, nil
}
