// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build freebsd

package probe

import (
	"net/netip"
	"os"
	"testing"
)

// TestMain lets the box user's tests connect through the guard: FreeBSD tells the socket that took a
// connection only to root (net.inet.tcp.getcred), so without root every test that dials a listener
// of its own failed at the kernel instead of testing its view. The seams then answer as the kernel
// would for the test's own listener. The tests of the real lookup set peerSocket themselves and run
// as root (PROBE_ROOT_TESTS in box_freebsdbox.sh).
func TestMain(m *testing.M) {
	if os.Geteuid() != 0 {
		uid := uint32(os.Geteuid())
		peerSocket = func(netip.AddrPort, netip.AddrPort) (peerState, error) { return peerConnected, nil }
		takerOwners = func(netip.AddrPort, netip.AddrPort) ([]uint32, error) { return []uint32{uid}, nil }
	}
	os.Exit(m.Run())
}
