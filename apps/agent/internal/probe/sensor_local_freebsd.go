// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build freebsd

package probe

import (
	"context"
	"errors"
	"fmt"
	"net"
	"os"
	"unsafe"

	"golang.org/x/sys/unix"
)

// unitPattern is the name of an rc.d service, the unit of this platform (rcNamePattern).
var unitPattern = rcNamePattern

// measureUnit reads the state of the rc.d service name (measureRC).
func measureUnit(ctx context.Context, name string) (map[string]any, error) {
	return measureRC(ctx, name)
}

// kernelFileSystems are the file systems of the kernel by f_fstypename, the names their modules
// register (VFS_SET, PSEUDOFS): reading a file there can change the kernel's state or wait on a
// device.
var kernelFileSystems = map[string]bool{
	"procfs": true, "linprocfs": true, "linsysfs": true, "fdescfs": true, "devfs": true,
}

// refuseKernelFile returns an error if f lies in a file system of the kernel.
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

// dialUnix connects to the unix socket path. A socket that does not exist or that nobody serves is
// errNoListener; one at a path of controlSockets, as given or with its links resolved, or served by a
// process the agent never probes is ErrNotAllowed.
func dialUnix(ctx context.Context, path string) (net.Conn, error) {
	real, err := socketToDial(path)
	if err != nil {
		return nil, err
	}
	var d net.Dialer
	conn, err := d.DialContext(ctx, "unix", real)
	if errors.Is(err, unix.ENOENT) || errors.Is(err, unix.ECONNREFUSED) {
		return nil, errNoListener
	}
	if err != nil {
		return nil, err
	}
	if err := checkPeer(ctx, conn.(*net.UnixConn), path); err != nil {
		_ = conn.Close()
		return nil, err
	}
	return conn, nil
}

// checkPeer refuses the socket path unless the socket it reached lies outside controlSockets
// (checkPeerName) and the process serving it may be probed: not a process the guard refuses on TCP
// and no forwarder (checkForwarder), and not inetd, which holds the sockets of the services it starts
// on their behalf (LOCAL_PEERCRED names the process that called listen).
func checkPeer(ctx context.Context, conn *net.UnixConn, path string) error {
	bound, err := peerName(conn)
	if err != nil {
		return fmt.Errorf("%w: the socket %s reached cannot be read: %v", ErrNotAllowed, path, err)
	}
	if err := checkPeerName(bound, path); err != nil {
		return err
	}
	pid, err := peerPID(conn)
	if err != nil {
		return fmt.Errorf("%w: the process serving %s cannot be read: %v", ErrNotAllowed, path, err)
	}
	name, err := processName(ctx, pid)
	if err != nil {
		return fmt.Errorf("%w: the process serving %s cannot be read: %v", ErrNotAllowed, path, err)
	}
	if neverProbed(name) || processKey(name) == "inetd" {
		return fmt.Errorf("%w: %s belongs to %s, which the agent never probes", ErrNotAllowed, path, name)
	}
	return checkForwarder(ctx, pid, name, path)
}

// peerPID returns the pid of the process that serves conn. struct xucred (sys/ucred.h) ends in a
// union of a pointer and cr_pid, which x/sys leaves unnamed: cr_pid starts where the union does, a
// pointer's size before the end, on either byte order.
func peerPID(conn *net.UnixConn) (int32, error) {
	raw, err := conn.SyscallConn()
	if err != nil {
		return 0, err
	}
	var cred *unix.Xucred
	var credErr error
	if err := raw.Control(func(fd uintptr) {
		cred, credErr = unix.GetsockoptXucred(int(fd), unix.SOL_LOCAL, unix.LOCAL_PEERCRED)
	}); err != nil {
		credErr = err
	}
	if credErr != nil {
		return 0, credErr
	}
	// XUCRED_VERSION 0 is the only layout there is; another one could move cr_pid.
	if cred.Version != 0 {
		return 0, fmt.Errorf("xucred version %d", cred.Version)
	}
	pid := *(*int32)(unsafe.Add(unsafe.Pointer(cred), unsafe.Sizeof(*cred)-unsafe.Sizeof(uintptr(0))))
	if pid <= 0 {
		return 0, fmt.Errorf("xucred names pid %d", pid)
	}
	return pid, nil
}

// peerName returns the address the server of conn bound, from getpeername: conn.RemoteAddr falls
// back to the dialed address when the call names nothing.
func peerName(conn *net.UnixConn) (string, error) {
	raw, err := conn.SyscallConn()
	if err != nil {
		return "", err
	}
	var peer unix.Sockaddr
	var peerErr error
	if err := raw.Control(func(fd uintptr) { peer, peerErr = unix.Getpeername(int(fd)) }); err != nil {
		peerErr = err
	}
	if peerErr != nil {
		return "", peerErr
	}
	sa, ok := peer.(*unix.SockaddrUnix)
	if !ok {
		return "", fmt.Errorf("the peer is no unix socket (%T)", peer)
	}
	return sa.Name, nil
}
