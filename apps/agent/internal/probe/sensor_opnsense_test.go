// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"io/fs"
	"reflect"
	"strings"
	"testing"
	"time"

	"adminhelper-agent/internal/opnsense"
)

// stampInfo is a FileInfo that only knows its modification time.
type stampInfo struct {
	fs.FileInfo
	mod time.Time
}

func (s stampInfo) ModTime() time.Time { return s.mod }

// stubOPNsenseHost makes this host one with configctl (or without) and with a firmware check
// result written at checked (none if zero); statPath answers every other path with ErrNotExist.
func stubOPNsenseHost(t *testing.T, configctl bool, checked time.Time) {
	t.Helper()
	old := statPath
	statPath = func(path string) (fs.FileInfo, error) {
		switch {
		case path == opnsense.Configctl && configctl:
			return stampInfo{}, nil
		case path == "/tmp/pkg_upgrade.json" && !checked.IsZero():
			return stampInfo{mod: checked}, nil
		}
		return nil, fs.ErrNotExist
	}
	t.Cleanup(func() { statPath = old })
}

func opnsenseProbe(view string, fields ...string) Probe {
	return Probe{ID: "fw", Sensor: "opnsense", TimeoutS: 30, Params: map[string]any{"view": view}, Fields: fields}
}

func TestTheOPNsenseSensorIsRegistered(t *testing.T) {
	if sensors["opnsense"] == nil {
		t.Error("sensor opnsense is not registered")
	}
}

func TestTheOPNsenseSensorReadsAViewThroughConfigctl(t *testing.T) {
	stubOPNsenseHost(t, true, time.Time{})
	calls := stubTools(t, answer{out: "current 1234\nlimit 813000\n"})
	res := Run(context.Background(), opnsenseProbe("states", "current", "used_pct"), time.Now(), nil)
	if res.Status != StatusOK {
		t.Fatalf("status %s (%s), want ok", res.Status, res.Error)
	}
	want := map[string]any{"current": 1234, "used_pct": 0.2}
	if !reflect.DeepEqual(res.Values, want) {
		t.Errorf("values %v, want only the asked fields %v", res.Values, want)
	}
	if wantCall := [][]string{{opnsense.Configctl, "filter", "diag", "state_size"}}; !reflect.DeepEqual(*calls, wantCall) {
		t.Errorf("calls %q, want %q", *calls, wantCall)
	}
}

func TestTheOPNsenseSensorDatesTheFirmwareCheckThroughItsSeams(t *testing.T) {
	at := time.Date(2026, 11, 10, 12, 0, 0, 0, time.UTC)
	stubNow(t, at)
	stubOPNsenseHost(t, true, at.Add(-90*time.Minute))
	stubTools(t, answer{out: `{"product_version":"26.7.1","product_latest":"26.7.2","product_check":{
		"connection":"ok","repository":"ok","needs_reboot":"1","upgrade_major_version":"",
		"new_packages":[],"upgrade_packages":[{"name":"opnsense"}],"reinstall_packages":[],
		"remove_packages":[],"downgrade_packages":[]}}`})
	got, err := opnsenseSensor(context.Background(), opnsenseProbe("firmware"), "")
	if err != nil {
		t.Fatal(err)
	}
	if got["check_age_s"] != int64(5400) || got["update_reboot"] != true || got["version"] != "26.7.1" {
		t.Errorf("firmware %v, want check_age_s 5400 from the stubbed mtime and clock, update_reboot true", got)
	}
}

func TestTheOPNsenseSensorIsUnsupportedWithoutConfigctl(t *testing.T) {
	stubOPNsenseHost(t, false, time.Time{})
	calls := stubTools(t)
	res := Run(context.Background(), opnsenseProbe("services", "total"), time.Now(), nil)
	if res.Status != StatusUnsupported || !strings.Contains(res.Error, "no OPNsense") {
		t.Errorf("status %s (%s), want unsupported", res.Status, res.Error)
	}
	if len(*calls) != 0 {
		t.Errorf("ran %q on a host without configctl", *calls)
	}
}

func TestTheOPNsenseSensorFailsWhenConfigctlCannotBeChecked(t *testing.T) {
	old := statPath
	statPath = func(string) (fs.FileInfo, error) { return nil, fs.ErrPermission }
	t.Cleanup(func() { statPath = old })
	calls := stubTools(t)
	_, err := opnsenseSensor(context.Background(), opnsenseProbe("services"), "")
	if err == nil || errors.Is(err, ErrUnsupported) || strings.Contains(err.Error(), opnsense.Configctl) {
		t.Errorf("err %v, want a plain error without the path", err)
	}
	if len(*calls) != 0 {
		t.Errorf("ran %q although configctl could not be checked", *calls)
	}
}

func TestTheOPNsenseSensorRejectsWhatItCannotRun(t *testing.T) {
	stubOPNsenseHost(t, true, time.Time{})
	for name, p := range map[string]Probe{
		"an unknown view": opnsenseProbe("interfaces"),
		"no view":         {Sensor: "opnsense"},
		"a view no text":  {Sensor: "opnsense", Params: map[string]any{"view": 1}},
		"another param":   {Sensor: "opnsense", Params: map[string]any{"view": "carp", "command": "x"}},
		"a target":        {Sensor: "opnsense", Target: &Target{Kind: kindLoopback, PortHint: 443}, Params: map[string]any{"view": "carp"}},
	} {
		calls := stubTools(t)
		p.TimeoutS = 30
		res := Run(context.Background(), p, time.Now(), nil)
		if res.Status != StatusInvalid {
			t.Errorf("%s: status %s (%s), want invalid", name, res.Status, res.Error)
		}
		if len(*calls) != 0 {
			t.Errorf("%s: ran %q", name, *calls)
		}
	}
}

func TestTheOPNsenseSensorReportsAConfigctlFailureAsError(t *testing.T) {
	stubOPNsenseHost(t, true, time.Time{})
	stubTools(t, answer{out: "Action not allowed or missing\n"})
	res := Run(context.Background(), opnsenseProbe("gateways", "down"), time.Now(), nil)
	if res.Status != StatusError || strings.Contains(res.Error, "Action not allowed") {
		t.Errorf("status %s (%s), want error without configd's text", res.Status, res.Error)
	}
}
