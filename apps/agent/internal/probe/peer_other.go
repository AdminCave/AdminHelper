// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build !linux && !freebsd

package probe

import (
	"context"
	"fmt"
	"net/netip"
)

// osPeerSocket: only Linux (sock_diag) and FreeBSD (getcred) tell the socket that took a connection;
// elsewhere a strict guard reads the listeners of the port again (osTakerOwners).
func osPeerSocket(netip.AddrPort, netip.AddrPort) (peerState, error) {
	return peerNone, errPeerUnsupported
}

// osTakerOwners returns the owners of the sockets that listen on server's port for server's address
// or for every address, read anew: without the taker that is what holds the port after the connect.
func osTakerOwners(server, _ netip.AddrPort) ([]uint32, error) {
	list, err := listenTCP(context.Background())
	if err != nil {
		return nil, err
	}
	ip := server.Addr().Unmap()
	var owners []uint32
	for _, l := range list {
		if l.port != server.Port() || (l.addr != ip && !l.addr.IsUnspecified()) {
			continue
		}
		if !l.hasUID {
			return nil, fmt.Errorf("a listener of port %d names no owner", server.Port())
		}
		owners = append(owners, l.uid)
	}
	return owners, nil
}
