// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package probe

import (
	"context"
	"errors"
	"testing"
	"time"
)

func TestAWMIQueryReadsTheOperatingSystem(t *testing.T) {
	var rows []struct{ NumberOfProcesses uint32 }
	q := wmiQuery{namespace: `root\cimv2`, class: "Win32_OperatingSystem"}
	if err := q.run(context.Background(), &rows); err != nil {
		t.Fatalf("run: %v", err)
	}
	if len(rows) != 1 || rows[0].NumberOfProcesses == 0 {
		t.Fatalf("rows = %+v, want one OS with processes", rows)
	}
}

func TestAWMIClassOrNamespaceTheHostLacksIsUnsupported(t *testing.T) {
	var rows []struct{ Name string }
	for _, q := range []wmiQuery{
		{namespace: `root\cimv2`, class: "AH_NoSuchClass"},
		{namespace: `root\AHNoSuchNamespace`, class: "Win32_OperatingSystem"},
	} {
		if err := q.run(context.Background(), &rows); !errors.Is(err, ErrUnsupported) {
			t.Errorf("%s %s: err = %v, want ErrUnsupported", q.namespace, q.class, err)
		}
	}
}

func TestEventsOfTheSystemLogAreCountedAndTheNewestIsRead(t *testing.T) {
	ctx := context.Background()
	all := eventQuery{channel: "System"}
	n, err := countEvents(ctx, all)
	if err != nil || n == 0 {
		t.Fatalf("countEvents(System) = %d, %v; want events", n, err)
	}
	info, ok, err := latestEvent(ctx, all)
	if err != nil || !ok {
		t.Fatalf("latestEvent(System) = %+v, %v, %v", info, ok, err)
	}
	if info.at.After(time.Now().Add(time.Minute)) || info.at.Before(time.Now().AddDate(-5, 0, 0)) {
		t.Errorf("newest event at %s, not a plausible time", info.at)
	}
	if info.level > 5 {
		t.Errorf("level %d out of range", info.level)
	}
	// A filter nothing matches counts zero and has no newest event.
	none := eventQuery{channel: "System", ids: []uint16{65000}, within: time.Second}
	if n, err := countEvents(ctx, none); err != nil || n != 0 {
		t.Errorf("countEvents(none) = %d, %v; want 0", n, err)
	}
	if _, ok, err := latestEvent(ctx, none); err != nil || ok {
		t.Errorf("latestEvent(none) = %v, %v; want none", ok, err)
	}
}

func TestALogTheHostLacksIsUnsupported(t *testing.T) {
	q := eventQuery{channel: "AH-No-Such-Channel"}
	if _, err := countEvents(context.Background(), q); !errors.Is(err, ErrUnsupported) {
		t.Errorf("countEvents: err = %v, want ErrUnsupported", err)
	}
	if _, _, err := latestEvent(context.Background(), q); !errors.Is(err, ErrUnsupported) {
		t.Errorf("latestEvent: err = %v, want ErrUnsupported", err)
	}
}

func TestTheMachineStoreOpensReadOnly(t *testing.T) {
	certs, err := machineCerts()
	if err != nil {
		t.Fatalf("machineCerts: %v", err)
	}
	for _, c := range certs {
		if !c.notAfter.After(c.notBefore) {
			t.Errorf("certificate valid %s..%s", c.notBefore, c.notAfter)
		}
	}
}
