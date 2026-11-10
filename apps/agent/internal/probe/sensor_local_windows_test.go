// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package probe

import (
	"context"
	"errors"
	"fmt"
	"net/netip"
	"os"
	"strings"
	"testing"
	"time"

	"golang.org/x/sys/windows/svc"
)

// stubService puts in a service manager that knows one service of status st.
func stubService(t *testing.T, name string, st svc.Status) {
	t.Helper()
	old := queryService
	queryService = func(n string) (svc.Status, error) {
		if n != name {
			return svc.Status{}, fmt.Errorf("service %s does not exist on this host", n)
		}
		return st, nil
	}
	t.Cleanup(func() { queryService = old })
}

func TestPathParamTakesNoShareDriveOrDevice(t *testing.T) {
	for _, path := range []string{`/\\host\share\x`, `/\\.\pipe\x`, "/C:/x", "/x.log:stream", "/NUL", "/dir/COM1", "/CONIN$"} {
		_, err := pathParam(Probe{Sensor: "file_age", Params: map[string]any{"path": path}})
		if !errors.Is(err, ErrInvalid) {
			t.Errorf("pathParam(%q) = %v, want ErrInvalid", path, err)
		}
	}
}

func TestServiceStatesMapToTheStatesOfAUnit(t *testing.T) {
	cases := map[svc.State][2]string{
		svc.Running:         {"active", "running"},
		svc.StartPending:    {"activating", "start_pending"},
		svc.ContinuePending: {"activating", "continue_pending"},
		svc.StopPending:     {"deactivating", "stop_pending"},
		svc.PausePending:    {"deactivating", "pause_pending"},
		svc.Paused:          {"inactive", "paused"},
		svc.Stopped:         {"inactive", "stopped"},
		svc.State(99):       {"unknown", "state_99"},
	}
	for s, want := range cases {
		if active, sub := serviceState(s); active != want[0] || sub != want[1] {
			t.Errorf("serviceState(%d) = %s, %s; want %s, %s", s, active, sub, want[0], want[1])
		}
	}
}

func TestUnitSensorReadsTheStateOfAService(t *testing.T) {
	ctx := context.Background()
	stubService(t, "W3SVC", svc.Status{State: svc.Running, ProcessId: uint32(os.Getpid())})
	p := Probe{Sensor: "unit", Target: &Target{Kind: kindUnit, Name: "W3SVC"}}

	got, err := unitSensor(ctx, p, "")
	since, ok := got["active_since"].(int64)
	if err != nil || got["active_state"] != "active" || got["sub_state"] != "running" || !ok ||
		since > time.Now().Unix() || since < time.Now().Add(-time.Hour).Unix() || got["restarts"] != nil {
		t.Fatalf("unit = %v, %v; want active since this process started, no restarts", got, err)
	}

	stubService(t, "W3SVC", svc.Status{State: svc.Stopped})
	got, err = unitSensor(ctx, p, "")
	if err != nil || fmt.Sprint(got) != "map[active_state:inactive sub_state:stopped]" {
		t.Errorf("a stopped service = %v, %v", got, err)
	}
	p.Target.Name = "Other"
	if _, err := unitSensor(ctx, p, ""); err == nil || !strings.Contains(err.Error(), "does not exist") {
		t.Errorf("an unknown service = %v", err)
	}
}

func TestUnitSensorOnThisHost(t *testing.T) {
	ctx := context.Background()
	got, err := measureUnit(ctx, "EventLog")
	if err != nil || got["active_state"] != "active" || got["active_since"] == nil {
		t.Fatalf("EventLog = %v, %v; want active", got, err)
	}
	if _, err := measureUnit(ctx, "NoSuchServiceOfAdminHelper"); err == nil || !strings.Contains(err.Error(), "does not exist") {
		t.Errorf("an unknown service = %v, want it not to exist", err)
	}
}

func TestAServiceTargetListensWithItsProcess(t *testing.T) {
	stubHost(t, &fakeHost{list: []listener{lst("0.0.0.0", 80, 7), lst("127.0.0.1", 8080, 8)}})
	ctx := context.Background()

	stubService(t, "W3SVC", svc.Status{State: svc.Running, ProcessId: 7})
	ep, err := resolve(ctx, Target{Kind: kindUnit, Name: "W3SVC"})
	if err != nil || ep.port != 80 || ep.addr != netip.MustParseAddr("127.0.0.1") {
		t.Fatalf("resolve = %v, %v; want 127.0.0.1:80 of its process", ep, err)
	}
	stubService(t, "W3SVC", svc.Status{State: svc.Stopped})
	if _, err := resolve(ctx, Target{Kind: kindUnit, Name: "W3SVC"}); !errors.Is(err, errNotListening) {
		t.Errorf("resolve of a stopped service = %v, want it not listening", err)
	}
}

func TestAContainerTargetIsUnsupportedOnWindows(t *testing.T) {
	_, err := resolve(context.Background(), Target{Kind: kindContainer, Name: "web"})
	if !errors.Is(err, ErrUnsupported) {
		t.Errorf("resolve = %v, want ErrUnsupported", err)
	}
}

func TestUnixSocketsAreUnsupportedOnWindows(t *testing.T) {
	p := Probe{Sensor: "unixsocket", Params: map[string]any{"path": "/run/app.sock"}}
	if _, err := unixSocketSensor(context.Background(), p, ""); !errors.Is(err, ErrUnsupported) {
		t.Errorf("a unix socket = %v, want ErrUnsupported", err)
	}
}
