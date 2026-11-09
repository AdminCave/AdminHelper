// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"testing"
	"time"
	"unicode/utf8"
)

// register adds a sensor for the test and removes it afterwards.
func register(t *testing.T, name string, sensor Sensor) {
	t.Helper()
	sensors[name] = sensor
	t.Cleanup(func() { delete(sensors, name) })
}

var start = time.Unix(1762700000, 0)

func TestAnUnknownSensorIsInvalid(t *testing.T) {
	res := Run(context.Background(), Probe{ID: "c1", Sensor: "nope", TimeoutS: 10}, start)

	if res.Status != StatusInvalid || res.TS != start.Unix() {
		t.Fatalf("result = %+v, want invalid at %d", res, start.Unix())
	}
	if !strings.Contains(res.Error, `"nope"`) {
		t.Errorf("error = %q, want it to name the sensor", res.Error)
	}
	if res.Values == nil || len(res.Values) != 0 {
		t.Errorf("values = %#v, want an empty map", res.Values)
	}
}

func TestASensorsValuesAreTheResult(t *testing.T) {
	var deadline time.Time
	register(t, "fake", func(ctx context.Context, p Probe) (map[string]any, error) {
		deadline, _ = ctx.Deadline()
		return map[string]any{"status": "OK"}, nil
	})

	before := time.Now()
	res := Run(context.Background(), Probe{ID: "c1", Sensor: "fake", TimeoutS: 7}, start)
	after := time.Now()

	if res.Status != StatusOK || res.Error != "" || res.Values["status"] != "OK" || res.TS != start.Unix() {
		t.Fatalf("result = %+v", res)
	}
	if deadline.Before(before.Add(7*time.Second)) || deadline.After(after.Add(7*time.Second)) {
		t.Errorf("the sensor's deadline is %s after the run's start, want the probe's 7 s", deadline.Sub(before))
	}
}

func TestASensorWithoutValuesSendsAnEmptyMap(t *testing.T) {
	register(t, "fake", func(context.Context, Probe) (map[string]any, error) { return nil, nil })

	res := Run(context.Background(), Probe{ID: "c1", Sensor: "fake", TimeoutS: 1}, start)

	data, err := json.Marshal(res)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(data), `"values":{}`) {
		t.Errorf("wire = %s, want values {} (never null)", data)
	}
	for _, key := range []string{`"ts":`, `"duration_ms":`, `"status":"ok"`, `"error":""`} {
		if !strings.Contains(string(data), key) {
			t.Errorf("wire = %s, want %s", data, key)
		}
	}
}

func TestASensorPastItsTimeoutIsAnError(t *testing.T) {
	register(t, "slow", func(ctx context.Context, p Probe) (map[string]any, error) {
		<-ctx.Done()
		return map[string]any{"x": 1}, ctx.Err()
	})

	res := Run(context.Background(), Probe{ID: "c1", Sensor: "slow", TimeoutS: 1}, start)

	if res.Status != StatusError || res.Error != "timed out after 1s" {
		t.Fatalf("result = %+v, want the error %q", res, "timed out after 1s")
	}
	if len(res.Values) != 0 {
		t.Errorf("values = %v, a failed run sends none", res.Values)
	}
	if res.DurationMS < 900 || res.DurationMS > 5000 {
		t.Errorf("duration_ms = %d, want about 1000", res.DurationMS)
	}
}

func TestASensorsErrorIsTheResult(t *testing.T) {
	register(t, "fake", func(context.Context, Probe) (map[string]any, error) {
		return map[string]any{"x": 1}, errors.New("connection refused")
	})

	res := Run(context.Background(), Probe{ID: "c1", Sensor: "fake", TimeoutS: 1}, start)

	if res.Status != StatusError || res.Error != "connection refused" || len(res.Values) != 0 {
		t.Fatalf("result = %+v", res)
	}
}

func TestAPanickingSensorIsAnErrorOfItsProbe(t *testing.T) {
	register(t, "boom", func(context.Context, Probe) (map[string]any, error) {
		panic("secret-value-in-panic")
	})

	res := Run(context.Background(), Probe{ID: "c1", Sensor: "boom", TimeoutS: 1}, start)

	if res.Status != StatusError || res.Error != "the sensor failed unexpectedly" {
		t.Fatalf("result = %+v", res)
	}
	if strings.Contains(res.Error, "secret") {
		t.Errorf("error = %q carries the panic value", res.Error)
	}
}

func TestAnErrorIsCleanedForTheReport(t *testing.T) {
	long := strings.Repeat("ä", 300)
	register(t, "fake", func(context.Context, Probe) (map[string]any, error) {
		return nil, errors.New("a\x00b \xff " + long)
	})

	res := Run(context.Background(), Probe{ID: "c1", Sensor: "fake", TimeoutS: 1}, start)

	if strings.Contains(res.Error, "\x00") || !utf8.ValidString(res.Error) {
		t.Errorf("error = %q, want no NUL and valid UTF-8", res.Error)
	}
	if n := utf8.RuneCountInString(res.Error); n != maxErrorRunes {
		t.Errorf("error has %d runes, want %d", n, maxErrorRunes)
	}
	if !strings.HasPrefix(res.Error, "ab � ää") {
		t.Errorf("error = %q", res.Error[:20])
	}
}

func TestAnUnknownSensorsNameIsCleaned(t *testing.T) {
	res := Run(context.Background(), Probe{ID: "c1", Sensor: strings.Repeat("x", 400) + "\x00"}, start)

	if strings.Contains(res.Error, "\x00") || utf8.RuneCountInString(res.Error) > maxErrorRunes {
		t.Errorf("error = %q", res.Error)
	}
}

func TestAResultReadBackGoesOutUnchanged(t *testing.T) {
	sent := []byte(`{"ts":1762700000,"duration_ms":12,"status":"ok","values":{"bytes":12345678901234567,"name":"x","ratio":0.5},"error":""}`)

	var res Result
	if err := json.Unmarshal(sent, &res); err != nil {
		t.Fatal(err)
	}
	again, err := json.Marshal(res)
	if err != nil {
		t.Fatal(err)
	}

	if string(again) != string(sent) {
		t.Fatalf("re-sent as %s\nwant %s", again, sent)
	}
}
