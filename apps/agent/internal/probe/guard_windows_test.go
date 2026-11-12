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
	"os"
	"os/exec"
	"strconv"
	"strings"
	"testing"
	"time"

	"golang.org/x/sys/windows"
	"golang.org/x/sys/windows/svc"
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
