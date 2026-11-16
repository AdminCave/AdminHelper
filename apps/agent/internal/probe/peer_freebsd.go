// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build freebsd

package probe

import (
	"encoding/binary"
	"errors"
	"fmt"
	"net"
	"net/netip"
	"strconv"
	"unsafe"

	"golang.org/x/sys/unix"
)

// osPeerSocket asks the kernel (getcred) for the connected TCP socket whose local end is server and
// whose remote end is client. The lookup matches the exact four ends only, never a listener: found
// is the socket that took the connection, ENOENT is none of this host.
func osPeerSocket(server, client netip.AddrPort) (peerState, error) {
	_, found, err := getcred(server, client)
	if err != nil || !found {
		return peerNone, err
	}
	return peerConnected, nil
}

// osTakerOwners returns the owner of the connected socket whose local end is server and whose
// remote end is client: cr_uid of the struct xucred getcred answers (sys/ucred.h), the credential
// the socket took over from its listener (sonewconn); none without that socket.
func osTakerOwners(server, client netip.AddrPort) ([]uint32, error) {
	uid, found, err := getcred(server, client)
	if err != nil || !found {
		return nil, err
	}
	return []uint32{uid}, nil
}

// getcred asks net.inet.tcp.getcred (as root) for the socket with the exact ends server and
// client and returns its owner; found is false when the kernel knows none (ENOENT).
func getcred(server, client netip.AddrPort) (uint32, bool, error) {
	var scope uint32
	if zone := server.Addr().Zone(); zone != "" {
		// Go writes the zone as the index when it knows no name for the interface.
		if i, err := strconv.ParseUint(zone, 10, 32); err == nil {
			scope = uint32(i)
		} else {
			ifi, err := net.InterfaceByName(zone)
			if err != nil {
				return 0, false, fmt.Errorf("getcred: %w", err)
			}
			scope = uint32(ifi.Index)
		}
	}
	name, req := getcredRequest(server, client, scope)
	out, err := sysctlByName(name, req)
	switch {
	case errors.Is(err, unix.ENOENT):
		return 0, false, nil
	case err != nil:
		return 0, false, fmt.Errorf("getcred: %w", err)
	}
	// struct xucred: u_int cr_version (XUCRED_VERSION, 0), then uid_t cr_uid.
	if len(out) < 8 || binary.NativeEndian.Uint32(out[0:4]) != 0 {
		return 0, false, fmt.Errorf("getcred: an answer of unknown form")
	}
	return binary.NativeEndian.Uint32(out[4:8]), true, nil
}

// sysctlByName writes req to the sysctl name and returns its answer (a struct xucred).
func sysctlByName(name string, req []byte) ([]byte, error) {
	p, err := unix.BytePtrFromString(name)
	if err != nil {
		return nil, err
	}
	var out [256]byte
	outLen := uintptr(len(out))
	_, _, errno := unix.Syscall6(unix.SYS___SYSCTLBYNAME,
		uintptr(unsafe.Pointer(p)), uintptr(len(name)),
		uintptr(unsafe.Pointer(&out[0])), uintptr(unsafe.Pointer(&outLen)),
		uintptr(unsafe.Pointer(&req[0])), uintptr(len(req)))
	if errno != 0 {
		return nil, errno
	}
	return out[:outLen], nil
}
