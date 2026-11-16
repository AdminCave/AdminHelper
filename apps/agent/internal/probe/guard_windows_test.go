// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package probe

import (
	"context"
	"errors"
	"fmt"
	"net"
	"net/netip"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"testing"
	"time"

	gnet "github.com/shirou/gopsutil/v4/net"
	"golang.org/x/sys/windows"
	"golang.org/x/sys/windows/svc"
	"golang.org/x/sys/windows/svc/mgr"
)

// resetForwarding drops the last read of the forwarding service, before and after the test.
func resetForwarding(t *testing.T) {
	t.Helper()
	reset := func() {
		forwarding.Lock()
		forwarding.at, forwarding.pid = time.Time{}, 0
		forwarding.Unlock()
	}
	reset()
	t.Cleanup(reset)
}

func TestServiceForwarderTellsTheProcessOfIphlpsvc(t *testing.T) {
	ctx := context.Background()
	for _, c := range []struct {
		name string
		st   svc.Status
		pid  int32
		want string
	}{
		{"its process", svc.Status{State: svc.Running, ProcessId: 4242}, 4242, "iphlpsvc"},
		{"another process", svc.Status{State: svc.Running, ProcessId: 4242}, 4243, ""},
		{"a stopped service", svc.Status{State: svc.Stopped}, 0, ""},
	} {
		resetForwarding(t)
		stubService(t, "iphlpsvc", c.st)
		if got, err := osServiceForwarder(ctx, c.pid); err != nil || got != c.want {
			t.Errorf("%s: = %q, %v; want %q", c.name, got, err, c.want)
		}
	}

	resetForwarding(t)
	old := queryService
	queryService = func(name string) (svc.Status, error) {
		return svc.Status{}, fmt.Errorf("service %s %w", name, errNoService)
	}
	t.Cleanup(func() { queryService = old })
	if got, err := osServiceForwarder(ctx, 4242); err != nil || got != "" {
		t.Errorf("no such service: = %q, %v; want none", got, err)
	}

	resetForwarding(t)
	queryService = func(string) (svc.Status, error) { return svc.Status{}, errors.New("access is denied") }
	if _, err := osServiceForwarder(ctx, 4242); err == nil {
		t.Error("an unreadable service manager told no error")
	}
}

func TestServiceForwarderReadsTheServiceOncePerTTL(t *testing.T) {
	resetForwarding(t)
	calls := 0
	old := queryService
	queryService = func(string) (svc.Status, error) {
		calls++
		return svc.Status{State: svc.Running, ProcessId: 4242}, nil
	}
	t.Cleanup(func() { queryService = old })
	for range 3 {
		_, _ = osServiceForwarder(context.Background(), 1)
	}
	if calls != 1 {
		t.Errorf("read the service %d times, want once within %s", calls, listenerTTL)
	}
}

// TestGuardNeverProbesAPortproxyPort sets up a real netsh portproxy and lets the real guard judge
// it. It needs an elevated process, which the CI job has.
func TestGuardNeverProbesAPortproxyPort(t *testing.T) {
	if !windows.GetCurrentProcessToken().IsElevated() {
		if os.Getenv("CI") != "" {
			t.Fatal("the CI job must run elevated to set up a portproxy")
		}
		t.Skip("needs an elevated process")
	}
	resetForwarding(t)
	ln, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	port := strconv.Itoa(ln.Addr().(*net.TCPAddr).Port)
	_ = ln.Close()
	netsh := func(args ...string) error {
		out, err := exec.Command("netsh", append([]string{"interface", "portproxy"}, args...)...).CombinedOutput()
		if err != nil {
			return fmt.Errorf("netsh %v: %v: %s", args, err, out)
		}
		return nil
	}
	if err := netsh("add", "v4tov4", "listenaddress=127.0.0.1", "listenport="+port,
		"connectaddress=127.0.0.1", "connectport=1"); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = netsh("delete", "v4tov4", "listenaddress=127.0.0.1", "listenport="+port) })

	g := NewGuard()
	var last error
	for deadline := time.Now().Add(30 * time.Second); time.Now().Before(deadline); time.Sleep(500 * time.Millisecond) {
		snapshot.Lock()
		snapshot.list, snapshot.at = nil, time.Time{}
		snapshot.Unlock()
		last = g.control(context.Background(), "tcp4", "127.0.0.1:"+port, nil)
		if !errors.Is(last, errNoProcess) {
			break
		}
	}
	if !errors.Is(last, ErrNotAllowed) || !strings.Contains(last.Error(), "iphlpsvc") {
		t.Fatalf("a portproxy port = %v, want it refused as iphlpsvc's", last)
	}
}

// filetimeNow is the FILETIME of now, the clock of liCreateTimestamp and of GetProcessTimes.
func filetimeNow() int64 {
	ft := windows.NsecToFiletime(time.Now().UnixNano())
	return int64(ft.HighDateTime)<<32 | int64(ft.LowDateTime)
}

// processStart is the FILETIME the test's process started at.
func processStart(t *testing.T) int64 {
	t.Helper()
	h, err := windows.OpenProcess(windows.PROCESS_QUERY_LIMITED_INFORMATION, false, uint32(os.Getpid()))
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = windows.CloseHandle(h) }()
	var start, exit, kernel, user windows.Filetime
	if err := windows.GetProcessTimes(h, &start, &exit, &kernel, &user); err != nil {
		t.Fatal(err)
	}
	return int64(start.HighDateTime)<<32 | int64(start.LowDateTime)
}

// pastStartTick waits until a socket bound now counts as the test's own (createdByProcess), however
// soon after its start the test runs.
func pastStartTick() {
	time.Sleep(2 * clockTick * 100 * time.Nanosecond)
}

// TestListenerAccountTellsServiceAccountsFromUsers asks Windows: the test runs under a user account,
// HTTP.sys counts as no service account's, EventLog runs as LocalService, and a socket older than
// its process names a pid Windows gave to another process.
func TestListenerAccountTellsServiceAccountsFromUsers(t *testing.T) {
	pastStartTick()
	now := filetimeNow()
	if uid, known := osListenerAccount(int32(os.Getpid()), now); !known || uid != accountUser {
		t.Errorf("the test's own process: %d, %v; want %d, true", uid, known, accountUser)
	}
	if _, known := osListenerAccount(int32(os.Getpid()), 1); known {
		t.Error("a socket created before its process names an account")
	}
	if _, known := osListenerAccount(int32(os.Getpid()), processStart(t)); known {
		t.Error("a socket created in the tick its process started names an account")
	}
	if _, known := osListenerAccount(int32(os.Getpid()), 0); known {
		t.Error("a socket without a creation time names an account")
	}
	if uid, known := osListenerAccount(systemPID, now); !known || uid != accountUser {
		t.Errorf("the System process: %d, %v; want %d, true", uid, known, accountUser)
	}
	if _, known := osListenerAccount(0, now); known {
		t.Error("pid 0 names an account")
	}
	m, err := mgr.Connect()
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = m.Disconnect() }()
	s, err := m.OpenService("EventLog")
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = s.Close() }()
	st, err := s.Query()
	if err != nil || st.State != svc.Running {
		t.Fatalf("EventLog: %+v, %v; want it running", st, err)
	}
	if uid, known := osListenerAccount(int32(st.ProcessId), now); !known || uid != 0 {
		t.Errorf("EventLog (LocalService): %d, %v; want 0, true", uid, known)
	}
}

// TestListenTCPReadsTheTableOfWindows: the rows of GetExtendedTcpTable name this test's listeners with
// their address, port, pid and a creation time between the process's start and now, as gopsutil
// (TCP_TABLE_OWNER_PID) names them too; the owners after a connect are the test's account.
func TestListenTCPReadsTheTableOfWindows(t *testing.T) {
	pastStartTick()
	var ports []netip.AddrPort
	for _, address := range []string{"127.0.0.1:0", "[::1]:0"} {
		ln, err := net.Listen("tcp", address)
		if err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() { _ = ln.Close() })
		ports = append(ports, ln.Addr().(*net.TCPAddr).AddrPort())
	}
	before := filetimeNow()
	started := processStart(t)

	conns, err := gnet.Connections("tcp")
	if err != nil {
		t.Fatal(err)
	}
	for i, ap := range ports {
		rows, err := tcpListenerTable(map[bool]uint32{false: windows.AF_INET, true: windows.AF_INET6}[i == 1], i == 1)
		if err != nil {
			t.Fatal(err)
		}
		found := false
		for _, r := range rows {
			if r.addr != ap.Addr().Unmap() || r.port != ap.Port() {
				continue
			}
			found = true
			if r.pid != int32(os.Getpid()) || r.created < started || r.created > before {
				t.Errorf("%s: pid %d created %d; want pid %d created in [%d, %d]", ap, r.pid, r.created, os.Getpid(), started, before)
			}
		}
		if !found {
			t.Errorf("%s: not in the table", ap)
		}
		viaGopsutil := false
		for _, c := range conns {
			if c.Status == "LISTEN" && c.Laddr.Port == uint32(ap.Port()) && c.Pid == int32(os.Getpid()) {
				viaGopsutil = true
			}
		}
		if !viaGopsutil {
			t.Errorf("%s: gopsutil lists no listener of this process", ap)
		}
		owners, err := osTakerOwners(ap, netip.AddrPortFrom(ap.Addr(), 1))
		if err != nil || len(owners) != 1 || owners[0] != accountUser {
			t.Errorf("%s: owners = %v, %v; want [%d]", ap, owners, err, accountUser)
		}
	}
	free, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	gone := free.Addr().(*net.TCPAddr).AddrPort()
	_ = free.Close()
	if owners, err := osTakerOwners(gone, netip.AddrPortFrom(gone.Addr(), 1)); err != nil || len(owners) != 0 {
		t.Errorf("a port nobody holds: owners = %v, %v; want none", owners, err)
	}
}
