// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build !linux && !freebsd

package probe

import "net/netip"

// osPeerSocket: only Linux (sock_diag) and FreeBSD (getcred) tell the socket that took a connection;
// elsewhere the guard relies on its checks before the connect.
func osPeerSocket(netip.AddrPort, netip.AddrPort) (peerState, error) {
	return peerNone, errPeerUnsupported
}
