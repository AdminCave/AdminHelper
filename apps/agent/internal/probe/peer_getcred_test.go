// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"bytes"
	"encoding/binary"
	"net/netip"
	"testing"
)

// TestGetcredRequestIPv4: two struct sockaddr_in, the local end (the probe's target) first, ports
// in network byte order; v4-mapped ends go to the IPv4 sysctl as well.
func TestGetcredRequestIPv4(t *testing.T) {
	want := []byte{
		16, 2, 0x1f, 0x90, 127, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0,
		16, 2, 0x9c, 0x40, 127, 0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0,
	}
	for _, c := range []struct{ server, client string }{
		{"127.0.0.1:8080", "127.0.0.2:40000"},
		{"[::ffff:127.0.0.1]:8080", "[::ffff:127.0.0.2]:40000"},
	} {
		name, req := getcredRequest(netip.MustParseAddrPort(c.server), netip.MustParseAddrPort(c.client), 0)
		if name != "net.inet.tcp.getcred" || !bytes.Equal(req, want) {
			t.Errorf("%s -> %s: %s % x, want net.inet.tcp.getcred % x", c.client, c.server, name, req, want)
		}
	}
}

// TestGetcredRequestIPv6: two struct sockaddr_in6; the scope id only for a link-local address.
func TestGetcredRequestIPv6(t *testing.T) {
	server := netip.MustParseAddrPort("[2001:db8::1]:443")
	client := netip.MustParseAddrPort("[2001:db8::2]:50000")
	name, req := getcredRequest(server, client, 7)
	if name != "net.inet6.tcp6.getcred" || len(req) != 56 {
		t.Fatalf("got %s with %d bytes, want net.inet6.tcp6.getcred with 56", name, len(req))
	}
	for i, end := range []netip.AddrPort{server, client} {
		sa := req[i*28 : (i+1)*28]
		addr := end.Addr().As16()
		if sa[0] != 28 || sa[1] != 28 || binary.BigEndian.Uint16(sa[2:4]) != end.Port() ||
			!bytes.Equal(sa[8:24], addr[:]) || binary.NativeEndian.Uint32(sa[24:28]) != 0 {
			t.Errorf("sockaddr %d = % x", i, sa)
		}
	}
	_, req = getcredRequest(netip.MustParseAddrPort("[fe80::1%em0]:22"), netip.MustParseAddrPort("[fe80::2%em0]:50000"), 7)
	if binary.NativeEndian.Uint32(req[24:28]) != 7 || binary.NativeEndian.Uint32(req[52:56]) != 7 {
		t.Errorf("link-local scope ids = % x / % x, want 7", req[24:28], req[52:56])
	}
}
