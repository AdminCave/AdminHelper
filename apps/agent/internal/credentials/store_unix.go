// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux || freebsd

package credentials

import (
	"fmt"
	"io"
	"os"
	"syscall"
)

// euid is the account the agent runs as; tests stand in another.
var euid = os.Geteuid

// readPrivate reads the file at path if it is a regular file of the agent's account that no other
// account may read or change (no bit in 0077). It opens the file without following a link and
// checks the open file, so a swap between the check and the read does not count.
func readPrivate(path string) ([]byte, error) {
	f, err := os.OpenFile(path, os.O_RDONLY|syscall.O_NOFOLLOW, 0)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	var st syscall.Stat_t
	if err := syscall.Fstat(int(f.Fd()), &st); err != nil {
		return nil, &os.PathError{Op: "stat", Path: path, Err: err}
	}
	switch {
	case st.Mode&syscall.S_IFMT != syscall.S_IFREG:
		return nil, fmt.Errorf("%s is no regular file", path)
	case st.Mode&0o077 != 0:
		return nil, fmt.Errorf("%s is open to other accounts (mode %#o); the agent uses no credential from it until chmod 600", path, st.Mode&0o777)
	case int(st.Uid) != euid():
		return nil, fmt.Errorf("%s belongs to uid %d, not to the agent's account", path, st.Uid)
	}
	data, err := io.ReadAll(io.LimitReader(f, maxFileBytes+1))
	if err != nil {
		return nil, &os.PathError{Op: "read", Path: path, Err: err}
	}
	if len(data) > maxFileBytes {
		return nil, fmt.Errorf("%s is larger than %d bytes", path, maxFileBytes)
	}
	return data, nil
}
