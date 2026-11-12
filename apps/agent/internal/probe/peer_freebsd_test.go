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
	"net/netip"
	"os"
	"os/exec"
	"strings"
	"testing"
)

// needRoot skips a test of getcred, which only root may call; the FreeBSD box runs these as root.
func needRoot(t *testing.T) {
	t.Helper()
	if os.Geteuid() != 0 {
		t.Skip("net.inet.tcp.getcred needs root")
	}
}

// TestPeerSocketOnFreeBSDFindsTheTaker: the kernel names the socket that took a connection by its
// exact ends, and none for another client port; over IPv4 and over a dual-stack listener.
func TestPeerSocketOnFreeBSDFindsTheTaker(t *testing.T) {
	needRoot(t)
	for _, c := range []struct{ network, listen, dial string }{
		{"tcp4", "127.0.0.1:0", "127.0.0.1"},
		{"tcp", ":0", "127.0.0.1"},
		{"tcp6", "[::1]:0", "::1"},
	} {
		t.Run(c.network+" "+c.listen, func(t *testing.T) {
			ln, err := net.Listen(c.network, c.listen)
			if err != nil {
				t.Skipf("listen %s: %v", c.listen, err)
			}
			defer ln.Close()
			port := ln.Addr().(*net.TCPAddr).Port
			conn, err := net.Dial("tcp", net.JoinHostPort(c.dial, fmt.Sprint(port)))
			if err != nil {
				t.Fatal(err)
			}
			defer conn.Close()
			taken, err := ln.Accept()
			if err != nil {
				t.Fatal(err)
			}
			defer taken.Close()
			server := conn.RemoteAddr().(*net.TCPAddr).AddrPort()
			client := conn.LocalAddr().(*net.TCPAddr).AddrPort()
			if got, err := osPeerSocket(server, client); err != nil || got != peerConnected {
				t.Errorf("exact ends = %v, %v, want peerConnected", got, err)
			}
			other := netip.AddrPortFrom(client.Addr(), client.Port()+1)
			if got, err := osPeerSocket(server, other); err != nil || got != peerNone {
				t.Errorf("another client port = %v, %v, want peerNone", got, err)
			}
		})
	}
}

// takenByWithoutSockstat is takenBy with the dialed listener as the only one the guard knows:
// these tests check what the kernel says after the connect, not the listeners sockstat reads
// before it.
func takenByWithoutSockstat(t *testing.T, h *fakeHost) (string, chan net.Conn) {
	t.Helper()
	address, accepted := takenBy(t, h)
	h.live = false
	h.list = []listener{lst("127.0.0.1", netip.MustParseAddrPort(address).Port(), 4242)}
	h.names = map[int32]string{4242: "web"}
	h.args = map[int32][]string{4242: {"web"}}
	return address, accepted
}

// TestGuardConnectsWhenFreeBSDListsTheTaker: the guard's own dial, with the real getcred behind it,
// keeps a connection the dialed listener took.
func TestGuardConnectsWhenFreeBSDListsTheTaker(t *testing.T) {
	needRoot(t)
	h := &fakeHost{}
	address, accepted := takenByWithoutSockstat(t, h)
	peerSocket = osPeerSocket
	conn, err := NewGuard().DialContext(context.Background(), "tcp", address)
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	_ = conn.Close()
	(<-accepted).Close()
}

// TestGuardRefusesAPfRedirectOnFreeBSD: a pf rdr rule hands a connection to the dialed port over to
// another listener; the guard resets it and refuses. It changes the host's pf, so it runs only with
// AH_FREEBSD_PF=1 (the pool box).
func TestGuardRefusesAPfRedirectOnFreeBSD(t *testing.T) {
	needRoot(t)
	if os.Getenv("AH_FREEBSD_PF") != "1" {
		t.Skip("changes the host's pf; set AH_FREEBSD_PF=1 on a throwaway box")
	}
	h := &fakeHost{}
	address, accepted := takenByWithoutSockstat(t, h)
	other, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer other.Close()
	go func() {
		for {
			c, err := other.Accept()
			if err != nil {
				return
			}
			_ = c.Close()
		}
	}()
	dialed := netip.MustParseAddrPort(address).Port()
	target := other.Addr().(*net.TCPAddr).Port
	_ = exec.Command("kldload", "-n", "pf").Run()
	rule := fmt.Sprintf("rdr pass on lo0 inet proto tcp from any to 127.0.0.1 port %d -> 127.0.0.1 port %d\n", dialed, target)
	load := exec.Command("pfctl", "-f", "-")
	load.Stdin = strings.NewReader(rule)
	if out, err := load.CombinedOutput(); err != nil {
		t.Fatalf("pfctl -f: %v: %s", err, out)
	}
	t.Cleanup(func() {
		_ = exec.Command("pfctl", "-F", "all").Run()
		_ = exec.Command("pfctl", "-d").Run()
	})
	if out, err := exec.Command("pfctl", "-e").CombinedOutput(); err != nil {
		t.Fatalf("pfctl -e: %v: %s", err, out)
	}
	peerSocket = osPeerSocket
	conn, err := NewGuard().DialContext(context.Background(), "tcp", address)
	if err == nil {
		_ = conn.Close()
		t.Fatal("dial through the rdr rule connected, want ErrNotAllowed")
	}
	if !errors.Is(err, ErrNotAllowed) || !strings.Contains(err.Error(), "taken by another socket") {
		t.Fatalf("dial: %v, want it refused as taken by another socket", err)
	}
	select {
	case c := <-accepted:
		c.Close()
		t.Error("the dialed listener took the connection, so the rdr rule did not apply")
	default:
	}
}
