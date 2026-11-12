// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package probe

import (
	"encoding/binary"
	"fmt"
	"net/netip"
	"syscall"
	"unsafe"

	"golang.org/x/sys/unix"
)

// inetDiagSockID is struct inet_diag_sockid of linux/inet_diag.h; ports and addresses are in
// network byte order.
type inetDiagSockID struct {
	sport, dport [2]byte
	src, dst     [16]byte
	iface        uint32
	cookie       [2]uint32
}

// inetDiagReqV2 is struct inet_diag_req_v2.
type inetDiagReqV2 struct {
	family, protocol, ext, pad uint8
	states                     uint32
	id                         inetDiagSockID
}

// inetDiagMsg is struct inet_diag_msg.
type inetDiagMsg struct {
	family, state, timer, retrans       uint8
	id                                  inetDiagSockID
	expires, rqueue, wqueue, uid, inode uint32
}

const (
	tcpListen        = 10 // TCP_LISTEN of include/net/tcp_states.h
	inetDiagNoCookie = ^uint32(0)
)

// osPeerSocket asks sock_diag for the one TCP socket of this host whose local end is server and
// whose remote end is client. An exact lookup that finds no such socket answers the listener on
// server's port, if there is one, or nothing.
func osPeerSocket(server, client netip.AddrPort) (peerState, error) {
	fd, err := unix.Socket(unix.AF_NETLINK, unix.SOCK_DGRAM|unix.SOCK_CLOEXEC, unix.NETLINK_SOCK_DIAG)
	if err != nil {
		return peerNone, fmt.Errorf("sock_diag: %w", err)
	}
	defer unix.Close(fd)
	if err := unix.SetsockoptTimeval(fd, unix.SOL_SOCKET, unix.SO_RCVTIMEO, &unix.Timeval{Sec: 1}); err != nil {
		return peerNone, fmt.Errorf("sock_diag: %w", err)
	}

	req := inetDiagReqV2{family: unix.AF_INET, protocol: unix.IPPROTO_TCP, states: ^uint32(0)}
	if server.Addr().Is6() {
		req.family = unix.AF_INET6
	}
	req.id = sockID(server, client)
	hdr := unix.NlMsghdr{
		Len:   uint32(unix.SizeofNlMsghdr + unsafe.Sizeof(req)),
		Type:  unix.SOCK_DIAG_BY_FAMILY,
		Flags: unix.NLM_F_REQUEST,
		Seq:   1,
	}
	msg := make([]byte, hdr.Len)
	*(*unix.NlMsghdr)(unsafe.Pointer(&msg[0])) = hdr
	*(*inetDiagReqV2)(unsafe.Pointer(&msg[unix.SizeofNlMsghdr])) = req
	if err := unix.Sendto(fd, msg, 0, &unix.SockaddrNetlink{Family: unix.AF_NETLINK}); err != nil {
		return peerNone, fmt.Errorf("sock_diag: %w", err)
	}

	buf := make([]byte, 8192)
	n, _, err := unix.Recvfrom(fd, buf, 0)
	if err != nil {
		return peerNone, fmt.Errorf("sock_diag: %w", err)
	}
	msgs, err := syscall.ParseNetlinkMessage(buf[:n])
	if err != nil {
		return peerNone, fmt.Errorf("sock_diag: %w", err)
	}
	for _, m := range msgs {
		switch m.Header.Type {
		case unix.NLMSG_ERROR:
			if len(m.Data) < 4 {
				return peerNone, fmt.Errorf("sock_diag: short error")
			}
			if errno := -int32(binary.NativeEndian.Uint32(m.Data)); errno == int32(unix.ENOENT) {
				return peerNone, nil
			} else if errno != 0 {
				return peerNone, fmt.Errorf("sock_diag: %w", syscall.Errno(errno))
			}
		case unix.SOCK_DIAG_BY_FAMILY:
			if len(m.Data) < int(unsafe.Sizeof(inetDiagMsg{})) {
				return peerNone, fmt.Errorf("sock_diag: short answer")
			}
			answer := *(*inetDiagMsg)(unsafe.Pointer(&m.Data[0]))
			return judgePeer(answer, server, client), nil
		}
	}
	return peerNone, fmt.Errorf("sock_diag: no answer")
}

// judgePeer says what the socket sock_diag answered is: the listener, the socket that took the
// connection, or one of neither.
func judgePeer(m inetDiagMsg, server, client netip.AddrPort) peerState {
	if m.state == tcpListen {
		return peerListener
	}
	local, ok1 := endOf(m.family, m.id.src, m.id.sport)
	remote, ok2 := endOf(m.family, m.id.dst, m.id.dport)
	if ok1 && ok2 && local == unmapped(server) && remote == unmapped(client) {
		return peerConnected
	}
	return peerNone
}

func sockID(server, client netip.AddrPort) inetDiagSockID {
	id := inetDiagSockID{iface: 0, cookie: [2]uint32{inetDiagNoCookie, inetDiagNoCookie}}
	binary.BigEndian.PutUint16(id.sport[:], server.Port())
	binary.BigEndian.PutUint16(id.dport[:], client.Port())
	putAddr(&id.src, server.Addr())
	putAddr(&id.dst, client.Addr())
	return id
}

func putAddr(dst *[16]byte, a netip.Addr) {
	if a.Is4() {
		b := a.As4()
		copy(dst[:4], b[:])
		return
	}
	b := a.As16()
	copy(dst[:], b[:])
}

func endOf(family uint8, addr [16]byte, port [2]byte) (netip.AddrPort, bool) {
	var a netip.Addr
	switch family {
	case unix.AF_INET:
		a = netip.AddrFrom4([4]byte(addr[:4]))
	case unix.AF_INET6:
		a = netip.AddrFrom16(addr).Unmap()
	default:
		return netip.AddrPort{}, false
	}
	return netip.AddrPortFrom(a, binary.BigEndian.Uint16(port[:])), true
}

func unmapped(ap netip.AddrPort) netip.AddrPort {
	return netip.AddrPortFrom(ap.Addr().Unmap().WithZone(""), ap.Port())
}
