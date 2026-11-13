// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package probe

import (
	"context"
	"net"
	"net/netip"
	"strconv"
	"testing"
	"time"

	"golang.org/x/sys/unix"
)

// connectedPair dials a listener on network and address and returns both ends of the connection.
func connectedPair(t *testing.T, network, address string) (server, client netip.AddrPort) {
	t.Helper()
	ln, err := net.Listen(network, address)
	if err != nil {
		t.Skipf("no %s listener on %s here: %v", network, address, err)
	}
	t.Cleanup(func() { _ = ln.Close() })
	port := ln.Addr().(*net.TCPAddr).Port
	host, _, _ := net.SplitHostPort(address)
	if host == "::" {
		host = "127.0.0.1"
	}
	conn, err := net.Dial("tcp", net.JoinHostPort(host, strconv.Itoa(port)))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = conn.Close() })
	srv, err := ln.Accept()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = srv.Close() })
	return conn.RemoteAddr().(*net.TCPAddr).AddrPort(), conn.LocalAddr().(*net.TCPAddr).AddrPort()
}

// TestPeerSocketFindsTheSocketThatTookTheConnection asks the kernel of the test host itself.
func TestPeerSocketFindsTheSocketThatTookTheConnection(t *testing.T) {
	for _, c := range []struct{ network, address string }{
		{"tcp4", "127.0.0.1:0"},
		{"tcp6", "[::1]:0"},
		{"tcp", "[::]:0"}, // an IPv4 connection taken by a dual-stack socket, as a mapped address
	} {
		server, client := connectedPair(t, c.network, c.address)
		state, err := osPeerSocket(server, client)
		if err != nil || state != peerConnected {
			t.Errorf("%s %s: %s from %s = %v, %v; want peerConnected", c.network, c.address, server, client, state, err)
		}
	}
}

// TestPeerSocketTellsAConnectionNoSocketHas: a redirect hands the connection to a socket bound to
// another port, so no socket has the ends the client sees; the kernel then answers the listener on
// the dialed port, or nothing if there is none.
func TestPeerSocketTellsAConnectionNoSocketHas(t *testing.T) {
	server, client := connectedPair(t, "tcp4", "127.0.0.1:0")
	other := netip.AddrPortFrom(client.Addr(), client.Port()+1)
	if state, err := osPeerSocket(server, other); err != nil || state != peerListener {
		t.Errorf("a client end no socket has = %v, %v; want peerListener", state, err)
	}

	ln, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	free := ln.Addr().(*net.TCPAddr).AddrPort()
	_ = ln.Close()
	if state, err := osPeerSocket(free, client); err != nil || state != peerNone {
		t.Errorf("a port nobody listens on = %v, %v; want peerNone", state, err)
	}
}

// TestPeerSocketTellsAFullAcceptQueue: a listener nobody accepts from, with a backlog of 0, holds one
// connection and is then full; the kernel drops the next completed handshake (R-1409).
func TestPeerSocketTellsAFullAcceptQueue(t *testing.T) {
	fd, err := unix.Socket(unix.AF_INET, unix.SOCK_STREAM|unix.SOCK_CLOEXEC, 0)
	if err != nil {
		t.Fatal(err)
	}
	defer unix.Close(fd)
	if err := unix.Bind(fd, &unix.SockaddrInet4{Addr: [4]byte{127, 0, 0, 1}}); err != nil {
		t.Fatal(err)
	}
	if err := unix.Listen(fd, 0); err != nil {
		t.Fatal(err)
	}
	sa, err := unix.Getsockname(fd)
	if err != nil {
		t.Fatal(err)
	}
	server := netip.AddrPortFrom(netip.MustParseAddr("127.0.0.1"), uint16(sa.(*unix.SockaddrInet4).Port))
	other := netip.MustParseAddrPort("127.0.0.1:1")
	if state, err := osPeerSocket(server, other); err != nil || state != peerListener {
		t.Fatalf("an empty queue = %v, %v; want peerListener", state, err)
	}

	conn, err := net.Dial("tcp4", server.String())
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	var state peerState
	for deadline := time.Now().Add(30 * time.Second); time.Now().Before(deadline); time.Sleep(10 * time.Millisecond) {
		if state, err = osPeerSocket(server, other); err != nil || state == peerListenerFull {
			break
		}
	}
	if err != nil || state != peerListenerFull {
		t.Errorf("a full queue = %v, %v; want peerListenerFull", state, err)
	}
}

// TestPeerSocketLosesTheOwnSocketOfAResetConnection: a reset ends the client's socket too, so the
// guard asks about its own end to tell an ended connection from a redirect (R-1409).
func TestPeerSocketLosesTheOwnSocketOfAResetConnection(t *testing.T) {
	ln, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer ln.Close()
	conn, err := net.Dial("tcp4", ln.Addr().String())
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	srv, err := ln.Accept()
	if err != nil {
		t.Fatal(err)
	}
	server := conn.RemoteAddr().(*net.TCPAddr).AddrPort()
	client := conn.LocalAddr().(*net.TCPAddr).AddrPort()
	if state, err := osPeerSocket(client, server); err != nil || state != peerConnected {
		t.Fatalf("the own end of a standing connection = %v, %v; want peerConnected", state, err)
	}

	_ = srv.(*net.TCPConn).SetLinger(0)
	_ = srv.Close()
	var state peerState
	for deadline := time.Now().Add(30 * time.Second); time.Now().Before(deadline); time.Sleep(10 * time.Millisecond) {
		if state, err = osPeerSocket(client, server); err != nil || state != peerConnected {
			break
		}
	}
	if err != nil || state == peerConnected {
		t.Errorf("the own end of a reset connection = %v, %v; want it gone", state, err)
	}
}

// TestJudgePeerWantsTheExactEnds: an answer whose ends differ from the asked ones took another
// connection.
func TestJudgePeerWantsTheExactEnds(t *testing.T) {
	server := netip.MustParseAddrPort("127.0.0.1:8080")
	client := netip.MustParseAddrPort("127.0.0.1:40000")
	answer := inetDiagMsg{family: unix.AF_INET, state: 1, id: sockID(server, client)}
	if got := judgePeer(answer, server, client); got != peerConnected {
		t.Errorf("exact ends = %v, want peerConnected", got)
	}
	if got := judgePeer(answer, server, netip.MustParseAddrPort("127.0.0.1:40001")); got != peerNone {
		t.Errorf("another client = %v, want peerNone", got)
	}
	answer.state = tcpListen
	if got := judgePeer(answer, server, client); got != peerListener {
		t.Errorf("a listener = %v, want peerListener", got)
	}
	for _, q := range []struct {
		rqueue, wqueue uint32
		want           peerState
	}{{3, 4096, peerListener}, {4096, 4096, peerListenerFull}, {4097, 4096, peerListenerFull}, {1, 0, peerListenerFull}} {
		answer.rqueue, answer.wqueue = q.rqueue, q.wqueue
		if got := judgePeer(answer, server, client); got != q.want {
			t.Errorf("a listener with %d of %d queued = %v, want %v", q.rqueue, q.wqueue, got, q.want)
		}
	}
	answer.rqueue, answer.wqueue = 0, 0
	answer = inetDiagMsg{family: unix.AF_INET6, state: 1,
		id: sockID(netip.MustParseAddrPort("[::ffff:127.0.0.1]:8080"), netip.MustParseAddrPort("[::ffff:127.0.0.1]:40000"))}
	if got := judgePeer(answer, server, client); got != peerConnected {
		t.Errorf("mapped ends of a dual-stack socket = %v, want peerConnected", got)
	}
}

// TestGuardConnectsWhenTheKernelListsTheTaker: the guard's own dial, with the real sock_diag behind
// it, keeps a connection the dialed listener took.
func TestGuardConnectsWhenTheKernelListsTheTaker(t *testing.T) {
	h := &fakeHost{}
	address, accepted := takenBy(t, h)
	peerSocket = osPeerSocket
	conn, err := NewGuard().DialContext(context.Background(), "tcp", address)
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	_ = conn.Close()
	(<-accepted).Close()
}
