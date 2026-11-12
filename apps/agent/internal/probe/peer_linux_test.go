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
