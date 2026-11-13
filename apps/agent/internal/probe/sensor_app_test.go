// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"
)

func appProbe(view string, target *Target, fields ...string) Probe {
	p := Probe{ID: "app", Sensor: "app", TimeoutS: 30, Target: target, Fields: fields}
	if view != "" {
		p.Params = map[string]any{"view": view}
	}
	return p
}

func unitTarget(name string) *Target { return &Target{Kind: kindUnit, Name: name} }

func TestTheAppSensorIsRegistered(t *testing.T) {
	if sensors["app"] == nil {
		t.Error("sensor app is not registered")
	}
}

func TestTheAppSensorRefusesWhatNoViewTakes(t *testing.T) {
	recordings := appProbe("bbb_recordings", unitTarget("bbb-web.service"))
	extra := appProbe("bbb_recordings", unitTarget("bbb-web.service"))
	extra.Params["path"] = "/etc/shadow"
	cases := map[string]Probe{
		"no view":           appProbe("", unitTarget("bbb-web.service")),
		"unknown view":      appProbe("bbb_conf_check", unitTarget("bbb-web.service")),
		"view of no text":   {ID: "app", Sensor: "app", Target: unitTarget("bbb-web.service"), Params: map[string]any{"view": 1}},
		"another parameter": extra,
		"no target":         appProbe("bbb_recordings", nil),
		"another kind":      appProbe("bbb_recordings", &Target{Kind: kindLoopback, PortHint: 8090}),
		"a bad unit name":   appProbe("bbb_recordings", unitTarget("bbb web")),
	}
	for name, p := range cases {
		t.Run(name, func(t *testing.T) {
			if _, err := appSensor(context.Background(), p, ""); !errors.Is(err, ErrInvalid) {
				t.Errorf("error %v, want ErrInvalid", err)
			}
		})
	}
	stubRecordingDir(t)
	if _, err := appSensor(context.Background(), recordings, ""); err != nil {
		t.Errorf("a valid probe is refused: %v", err)
	}
}

func TestTheAppSensorNamesItsViewsWhenOneIsUnknown(t *testing.T) {
	_, err := appSensor(context.Background(), appProbe("nope", unitTarget("bbb-web.service")), "")
	if err == nil || !strings.Contains(err.Error(), "bbb_recordings") {
		t.Errorf("error %v, want the views named", err)
	}
}

func TestTheAppSensorRunsThroughRunWithOnlyTheAskedFields(t *testing.T) {
	at := time.Date(2026, 11, 13, 12, 0, 0, 0, time.UTC)
	stubNow(t, at)
	root := stubRecordingDir(t)
	failMarker(t, root, "sanity", "abc-1.fail", at.Add(-time.Hour))
	res := Run(context.Background(), appProbe("bbb_recordings", unitTarget("bbb-web.service"), "failed"), at, nil)
	if res.Status != StatusOK {
		t.Fatalf("status %s (%s), want ok", res.Status, res.Error)
	}
	if len(res.Values) != 1 || res.Values["failed"] != 1 {
		t.Errorf("values %v, want only failed=1", res.Values)
	}
}

// unitView: the view reads a unit alone.
func unitView(v appView) bool { return len(v.kinds) == 1 && v.kinds[0] == kindUnit }
