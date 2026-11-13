// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"reflect"
	"testing"
	"time"
)

func hostProbe(view string, fields ...string) Probe {
	return Probe{ID: "host", Sensor: "host", TimeoutS: 30, Params: map[string]any{"view": view}, Fields: fields}
}

func TestTheHostSensorIsRegistered(t *testing.T) {
	if sensors["host"] == nil {
		t.Error("sensor host is not registered")
	}
}

func TestTheHostSensorReadsAView(t *testing.T) {
	stubSysBlock(t, map[string]string{"md0/md/array_state": "clean", "md0/md/degraded": "1"})
	res := Run(context.Background(), hostProbe("mdadm", "arrays", "degraded"), time.Now(), nil)
	if res.Status != StatusOK {
		t.Fatalf("status %s (%s), want ok", res.Status, res.Error)
	}
	if want := map[string]any{"arrays": 1, "degraded": 1}; !reflect.DeepEqual(res.Values, want) {
		t.Errorf("values %v, want only the asked fields %v", res.Values, want)
	}
}

func TestTheHostSensorRejectsWhatItCannotRun(t *testing.T) {
	for name, p := range map[string]Probe{
		"an unknown view": hostProbe("zfs"),
		"no view":         {Sensor: "host"},
		"a view no text":  {Sensor: "host", Params: map[string]any{"view": 1}},
		"another param":   {Sensor: "host", Params: map[string]any{"view": "lvm_thin", "command": "x"}},
		"a target":        {Sensor: "host", Target: &Target{Kind: kindLoopback, PortHint: 443}, Params: map[string]any{"view": "mdadm"}},
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
