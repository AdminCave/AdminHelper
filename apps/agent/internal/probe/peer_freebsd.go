// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build freebsd

package probe

import (
	"errors"
	"fmt"
	"net"
	"net/netip"
	"strconv"
	"unsafe"

	"golang.org/x/sys/unix"
)

// osPeerSocket asks the kernel (net.inet.tcp.getcred, as root) for the connected TCP socket whose
// local end is server and whose remote end is client. The lookup matches the exact four ends only,
// never a listener: found is the socket that took the connection, ENOENT is none of this host.
func osPeerSocket(server, client netip.AddrPort) (peerState, error) {
	var scope uint32
	if zone := server.Addr().Zone(); zone != "" {
		// Go writes the zone as the index when it knows no name for the interface.
		if i, err := strconv.ParseUint(zone, 10, 32); err == nil {
			scope = uint32(i)
		} else {
			ifi, err := net.InterfaceByName(zone)
			if err != nil {
				return peerNone, fmt.Errorf("getcred: %w", err)
			}
			scope = uint32(ifi.Index)
		}
	}
	name, req := getcredRequest(server, client, scope)
	err := sysctlByName(name, req)
	switch {
	case err == nil:
		return peerConnected, nil
	case errors.Is(err, unix.ENOENT):
		return peerNone, nil
	default:
		return peerNone, fmt.Errorf("getcred: %w", err)
	}
}

// sysctlByName writes req to the sysctl name and drops its answer (a struct xucred).
func sysctlByName(name string, req []byte) error {
	p, err := unix.BytePtrFromString(name)
	if err != nil {
		return err
	}
	var out [256]byte
	outLen := uintptr(len(out))
	_, _, errno := unix.Syscall6(unix.SYS___SYSCTLBYNAME,
		uintptr(unsafe.Pointer(p)), uintptr(len(name)),
		uintptr(unsafe.Pointer(&out[0])), uintptr(unsafe.Pointer(&outLen)),
		uintptr(unsafe.Pointer(&req[0])), uintptr(len(req)))
	if errno != 0 {
		return errno
	}
	return nil
}
