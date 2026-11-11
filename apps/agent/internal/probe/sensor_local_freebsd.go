// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build freebsd

package probe

import (
	"context"
	"fmt"
	"net"
	"os"
	"regexp"

	"golang.org/x/sys/unix"
)

// unitPattern is an rc.d script name as service(8) takes it: no "/", not "." or "..", no leading "-"
// (monitor's reRCScriptName).
var unitPattern = regexp.MustCompile(`^[A-Za-z0-9_][A-Za-z0-9._-]{0,254}$`)

// measureUnit is not supported: the unit sensor reads systemd units and Windows services, and rc.d
// keeps no state of its own to read.
func measureUnit(context.Context, string) (map[string]any, error) {
	return nil, fmt.Errorf("%w: the unit sensor on FreeBSD", ErrUnsupported)
}

// kernelFileSystems are the FreeBSD file systems of the kernel, by f_fstypename: reading a file there
// reads or acts on the kernel's state (procfs exposes the memory of processes, devfs the devices).
var kernelFileSystems = map[string]bool{
	"procfs": true, "linprocfs": true, "linsysfs": true, "devfs": true, "fdescfs": true,
}

// refuseKernelFile returns an error if f lies in a file system of the kernel (kernelFileSystems).
func refuseKernelFile(f *os.File, path string) error {
	conn, err := f.SyscallConn()
	if err != nil {
		return fmt.Errorf("the file system of %s cannot be read: %v", path, err)
	}
	var st unix.Statfs_t
	var statErr error
	if err := conn.Control(func(fd uintptr) { statErr = unix.Fstatfs(int(fd), &st) }); err != nil {
		statErr = err
	}
	if statErr != nil {
		return fmt.Errorf("the file system of %s cannot be read: %v", path, statErr)
	}
	if kernelFileSystems[unix.ByteSliceToString(st.Fstypename[:])] {
		return fmt.Errorf("%s lies in a file system of the kernel", path)
	}
	return nil
}

// openNoWait opens path to read without waiting: a FIFO swapped in since the stat does not block.
func openNoWait(path string) (*os.File, error) {
	return os.OpenFile(path, os.O_RDONLY|unix.O_NONBLOCK|unix.O_NOCTTY, 0)
}

// dialUnix is not supported: the agent probes unix sockets on Linux only, where it checks the
// serving process by SO_PEERCRED.
func dialUnix(context.Context, string) (net.Conn, error) {
	return nil, fmt.Errorf("%w: unix sockets are probed on Linux only", ErrUnsupported)
}
