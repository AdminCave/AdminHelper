// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"net/netip"
	"reflect"
	"testing"
)

func TestListenersAreTheGuardsSnapshot(t *testing.T) {
	h := &fakeHost{list: []listener{lst("0.0.0.0", 80, 7), lst("::1", 8080, 0)}}
	stubHost(t, h)
	want := []Listener{
		{Addr: netip.MustParseAddr("0.0.0.0"), Port: 80, PID: 7},
		{Addr: netip.MustParseAddr("::1"), Port: 8080},
	}
	for range 2 {
		got, err := Listeners(context.Background())
		if err != nil || !reflect.DeepEqual(got, want) {
			t.Fatalf("Listeners = %+v, %v; want %+v", got, err, want)
		}
	}
	if h.listCalls != 1 {
		t.Errorf("the sockets were read %d times, want once for the snapshot", h.listCalls)
	}

	stubHost(t, &fakeHost{listErr: errors.New("permission denied")})
	if got, err := Listeners(context.Background()); err == nil || got != nil {
		t.Errorf("Listeners of an unreadable host = %+v, %v; want an error", got, err)
	}
}

func TestProcessNameIsTheGuardsKey(t *testing.T) {
	stubHost(t, &fakeHost{names: map[int32]string{7: "NGINX.exe"}})
	if got := ProcessName(context.Background(), 7); got != "nginx" {
		t.Errorf("ProcessName = %q, want nginx", got)
	}
	if got := ProcessName(context.Background(), 8); got != "" {
		t.Errorf("ProcessName of a process that cannot be read = %q, want none", got)
	}
}

func TestNeverProbedTakesPortsAndProcesses(t *testing.T) {
	for _, c := range []struct {
		port uint16
		name string
		want bool
	}{
		{0, "", true},
		{22, "", true},
		{3306, "nginx", true},
		{9100, "", true},
		{9107, "", true},
		{80, "sshd", true},
		{80, "MariaDBd", true},
		{80, "dockerd", true},
		{80, "containerd-shim-runc-v2", true},
		{80, "nginx", false},
		{9108, "", false},
	} {
		if got := NeverProbed(c.port, c.name); got != c.want {
			t.Errorf("NeverProbed(%d, %q) = %v, want %v", c.port, c.name, got, c.want)
		}
	}
}

func TestRecognizePortReachesThePortBeyondLoopback(t *testing.T) {
	smtp := listen(t, func(c *fakeConn) {
		c.say("220 mail.example.org ESMTP\r\n")
		c.hear()
	})
	web := listen(t, func(c *fakeConn) {
		c.hear()
		c.say("HTTP/1.0 503 Service Unavailable\r\n\r\n")
	})
	pid := int32(4242)
	stubHost(t, &fakeHost{
		list:  []listener{lst("0.0.0.0", uint16(smtp.port()), pid), lst("0.0.0.0", uint16(web.port()), pid)},
		names: map[int32]string{pid: "master"},
	})
	for _, c := range []struct {
		port int
		want string
	}{
		{smtp.port(), "smtp"},
		// The name alone, without what the service answered.
		{web.port(), "http"},
	} {
		if got, err := RecognizePort(context.Background(), uint16(c.port)); err != nil || got != c.want {
			t.Errorf("RecognizePort(%d) = %q, %v; want %s", c.port, got, err, c.want)
		}
	}
}

func TestRecognizePortLeavesWhatTheGuardRefuses(t *testing.T) {
	srv := listen(t, func(c *fakeConn) { c.say("220 mail.example.org ESMTP\r\n") })
	port := uint16(srv.port())
	pid := int32(4242)
	ctx := context.Background()

	// A port that listens on loopback alone is no port beyond it.
	stubHost(t, &fakeHost{list: []listener{lst("127.0.0.1", port, pid)}, names: map[int32]string{pid: "master"}})
	if got, err := RecognizePort(ctx, port); !errors.Is(err, errNotListening) {
		t.Errorf("a loopback port = %q, %v; want it not listening", got, err)
	}

	for _, c := range []struct {
		name string
		host *fakeHost
		port uint16
	}{
		{"a host daemon", &fakeHost{list: []listener{lst("0.0.0.0", port, pid)}, names: map[int32]string{pid: "dockerd"}}, port},
		{"a process that cannot be read", &fakeHost{list: []listener{lst("0.0.0.0", port, pid)}}, port},
		{"a blocked port", &fakeHost{list: []listener{lst("0.0.0.0", 22, pid)}, names: map[int32]string{pid: "master"}}, 22},
	} {
		stubHost(t, c.host)
		if got, err := RecognizePort(ctx, c.port); !errors.Is(err, ErrNotAllowed) {
			t.Errorf("%s = %q, %v; want it refused", c.name, got, err)
		}
	}
	if heard := srv.close(); len(heard) != 0 {
		t.Errorf("the server heard %q, want no connection", heard)
	}
}
