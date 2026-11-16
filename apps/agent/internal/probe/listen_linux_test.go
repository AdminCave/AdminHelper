// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package probe

import (
	"context"
	"net"
	"net/netip"
	"os"
	"os/exec"
	"slices"
	"strconv"
	"strings"
	"testing"
	"time"

	gnet "github.com/shirou/gopsutil/v4/net"
)

// TestListenTCPNamesEveryProcessOfASocket: a socket two processes hold (systemd and the service it
// started) is listed once for each; gopsutil keeps only one of them (R-1441).
func TestListenTCPNamesEveryProcessOfASocket(t *testing.T) {
	ln, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer ln.Close()
	port := uint16(ln.Addr().(*net.TCPAddr).Port)
	f, err := ln.(*net.TCPListener).File()
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	child := exec.Command("sleep", "60")
	child.ExtraFiles = []*os.File{f}
	if err := child.Start(); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = child.Process.Kill(); _ = child.Wait() })

	want := []int32{int32(os.Getpid()), int32(child.Process.Pid)}
	slices.Sort(want)
	var pids []int32
	// The child holds the socket once it runs; a bound of 30 s, not a short one (testing.md).
	for deadline := time.Now().Add(30 * time.Second); time.Now().Before(deadline); time.Sleep(50 * time.Millisecond) {
		list, err := listenTCP(context.Background())
		if err != nil {
			t.Fatal(err)
		}
		pids = nil
		for _, l := range list {
			if l.port == port && l.addr == netip.MustParseAddr("127.0.0.1") {
				pids = append(pids, l.pid)
			}
		}
		slices.Sort(pids)
		if slices.Equal(pids, want) {
			break
		}
	}
	if !slices.Equal(pids, want) {
		t.Fatalf("processes of the socket = %v, want both %v", pids, want)
	}
}

// TestListenTCPSeesWhatGopsutilSees: the same sockets as gopsutil, by address and port.
func TestListenTCPSeesWhatGopsutilSees(t *testing.T) {
	ln, err := net.Listen("tcp", "[::1]:0")
	if err != nil {
		ln, err = net.Listen("tcp4", "127.0.0.1:0")
	}
	if err != nil {
		t.Fatal(err)
	}
	defer ln.Close()
	type key struct {
		addr netip.Addr
		port uint16
	}
	ours := map[key]bool{}
	list, err := listenTCP(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	for _, l := range list {
		ours[key{l.addr, l.port}] = true
	}
	conns, err := gnet.ConnectionsWithContext(context.Background(), "tcp")
	if err != nil {
		t.Fatal(err)
	}
	theirs := map[key]bool{}
	for _, c := range conns {
		if c.Status != "LISTEN" {
			continue
		}
		a, err := netip.ParseAddr(c.Laddr.IP)
		if err != nil {
			continue
		}
		theirs[key{a.Unmap().WithZone(""), uint16(c.Laddr.Port)}] = true
	}
	own := key{netip.MustParseAddr(ln.Addr().(*net.TCPAddr).IP.String()).Unmap(), uint16(ln.Addr().(*net.TCPAddr).Port)}
	if !ours[own] {
		t.Fatalf("our own listener %v is missing", own)
	}
	for k := range ours {
		if !theirs[k] && k == own {
			t.Errorf("gopsutil misses our own listener %v", k)
		}
	}
	// Sockets may come and go between the two reads: compare, and fail only on one we miss that
	// gopsutil still sees on a second read of ours.
	for k := range theirs {
		if ours[k] {
			continue
		}
		again, err := listenTCP(context.Background())
		if err != nil {
			t.Fatal(err)
		}
		if slices.ContainsFunc(again, func(l listener) bool { return l.addr == k.addr && l.port == k.port }) {
			continue
		}
		if still, _ := gnet.ConnectionsWithContext(context.Background(), "tcp"); slices.ContainsFunc(still, func(c gnet.ConnectionStat) bool {
			a, err := netip.ParseAddr(c.Laddr.IP)
			return err == nil && c.Status == "LISTEN" && uint16(c.Laddr.Port) == k.port && a.Unmap().WithZone("") == k.addr
		}) {
			t.Errorf("gopsutil lists %v, the reader does not", k)
		}
	}
}

func TestOSPrivilegedPortsEndBelowTheKernelsFirstUnprivilegedPort(t *testing.T) {
	data, err := os.ReadFile("/proc/sys/net/ipv4/ip_unprivileged_port_start")
	if err != nil {
		t.Fatal(err)
	}
	start, err := strconv.Atoi(strings.TrimSpace(string(data)))
	if err != nil {
		t.Fatal(err)
	}
	lo, hi := osPrivilegedPorts()
	if lo != 1 || int(hi) != start-1 {
		t.Errorf("osPrivilegedPorts = %d..%d, want 1..%d", lo, hi, start-1)
	}
}
