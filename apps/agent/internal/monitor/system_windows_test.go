// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package monitor

import (
	"context"
	"errors"
	"reflect"
	"testing"
)

func stubW32tm(t *testing.T, out string, err error) {
	t.Helper()
	orig := w32tmStatus
	w32tmStatus = func(context.Context) ([]byte, error) { return []byte(out), err }
	t.Cleanup(func() { w32tmStatus = orig })
}

func TestCollectSystemStateTimeSynchronized(t *testing.T) {
	st := reportState{}
	stubW32tm(t, "Leap Indicator: 3(not synchronized)\r\nSource: Local CMOS Clock\r\n", nil)
	block, _ := collectSystemState(context.Background(), st)
	if !reflect.DeepEqual(wireValue(t, block), wireValue(t, map[string]any{"time_synchronized": false})) {
		t.Errorf("block = %v, want time_synchronized false", block)
	}

	stubW32tm(t, "Leap Indicator: 0(no warning)\r\nSource: time.windows.com,0x9\r\n", nil)
	block, _ = collectSystemState(context.Background(), st)
	if !reflect.DeepEqual(wireValue(t, block), wireValue(t, map[string]any{"time_synchronized": true})) {
		t.Errorf("block = %v, want time_synchronized true", block)
	}
}

func TestCollectSystemStateLeavesTimeOutWhenUnreadable(t *testing.T) {
	for name, stub := range map[string]struct {
		out string
		err error
	}{
		"w32tm failed": {"", errors.New("exit status 1")},
		"unreadable":   {"something else\r\n", nil},
	} {
		t.Run(name, func(t *testing.T) {
			stubW32tm(t, stub.out, stub.err)
			block, _ := collectSystemState(context.Background(), reportState{})
			if !block.empty() {
				t.Errorf("block = %v, want no field", block)
			}
		})
	}
}

func TestCollectSystemStateOnThisHost(t *testing.T) {
	// The real w32tm on the runner: the block is empty or carries a bool, never anything else.
	block, _ := collectSystemState(context.Background(), reportState{})
	if v, ok := wireValue(t, block).(map[string]any)["time_synchronized"]; ok {
		if _, isBool := v.(bool); !isBool {
			t.Errorf("time_synchronized = %#v, want a bool", v)
		}
	}
	t.Logf("system_state on this host: %v", block)
}
