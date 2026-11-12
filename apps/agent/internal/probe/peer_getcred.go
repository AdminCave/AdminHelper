// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"encoding/binary"
	"net/netip"
)

// FreeBSD's address families and sockaddr sizes (sys/socket.h, netinet/in.h, netinet6/in6.h); the
// request is built here, free of a build tag, so every platform's tests check its layout.
const (
	bsdAFInet         = 2
	bsdAFInet6        = 28
	bsdSockaddrIn     = 16
	bsdSockaddrIn6    = 28
	getcredSysctlIPv4 = "net.inet.tcp.getcred"
	getcredSysctlIPv6 = "net.inet6.tcp6.getcred"
)

// getcredRequest returns the sysctl and its input that ask FreeBSD for the connected TCP socket
// whose local end is server and whose remote end is client: tcp_getcred reads two sockaddrs, the
// local one first, ports in network byte order. A pair of IPv4 (or v4-mapped) ends goes to the IPv4
// sysctl; scope is the interface index of a link-local IPv6 address, else 0.
func getcredRequest(server, client netip.AddrPort, scope uint32) (string, []byte) {
	s, c := server.Addr().Unmap(), client.Addr().Unmap()
	if s.Is4() && c.Is4() {
		req := make([]byte, 2*bsdSockaddrIn)
		putSockaddrIn(req[:bsdSockaddrIn], s, server.Port())
		putSockaddrIn(req[bsdSockaddrIn:], c, client.Port())
		return getcredSysctlIPv4, req
	}
	req := make([]byte, 2*bsdSockaddrIn6)
	putSockaddrIn6(req[:bsdSockaddrIn6], server.Addr(), server.Port(), scope)
	putSockaddrIn6(req[bsdSockaddrIn6:], client.Addr(), client.Port(), scope)
	return getcredSysctlIPv6, req
}

// putSockaddrIn writes struct sockaddr_in: sin_len, sin_family, sin_port, sin_addr, sin_zero.
func putSockaddrIn(b []byte, a netip.Addr, port uint16) {
	b[0], b[1] = bsdSockaddrIn, bsdAFInet
	binary.BigEndian.PutUint16(b[2:4], port)
	ip := a.As4()
	copy(b[4:8], ip[:])
}

// putSockaddrIn6 writes struct sockaddr_in6: sin6_len, sin6_family, sin6_port, sin6_flowinfo,
// sin6_addr, sin6_scope_id (host byte order).
func putSockaddrIn6(b []byte, a netip.Addr, port uint16, scope uint32) {
	b[0], b[1] = bsdSockaddrIn6, bsdAFInet6
	binary.BigEndian.PutUint16(b[2:4], port)
	ip := a.As16()
	copy(b[8:24], ip[:])
	if a.Is6() && a.IsLinkLocalUnicast() {
		binary.NativeEndian.PutUint32(b[24:28], scope)
	}
}
