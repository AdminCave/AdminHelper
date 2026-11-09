// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Package probe runs the probes of the monitoring plan (R-1223): each one is a sensor the agent knows,
// run against one target of this host, and its result is what the next report carries.
package probe

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"runtime/debug"
	"strings"
	"time"
	"unicode/utf8"

	"adminhelper-agent/internal/logging"
)

var logger = logging.For("probe")

// Plan is what the monitoring service answers on GET /agent/{id}/plan, plan_version 1.
type Plan struct {
	PlanVersion    int       `json:"plan_version"`
	CatalogVersion string    `json:"catalog_version"`
	Scan           bool      `json:"scan"`
	Discovery      Discovery `json:"discovery"`
	Probes         []Probe   `json:"probes"`
}

// Discovery is what the discovery of this host looks for.
type Discovery struct {
	Markers []Marker `json:"markers"`
}

// Marker is a hint that a module is installed: a path or a package.
type Marker struct {
	ID       string   `json:"id"`
	Paths    []string `json:"paths"`
	Packages []string `json:"packages"`
}

// Probe is one probe check of this host: which sensor runs how often against what.
type Probe struct {
	// ID is the check's id, the key of its result in the report.
	ID         string         `json:"id"`
	Sensor     string         `json:"sensor"`
	IntervalS  int            `json:"interval_s"`
	TimeoutS   int            `json:"timeout_s"`
	Target     *Target        `json:"target"`
	Params     map[string]any `json:"params"`
	Fields     []string       `json:"fields"`
	Credential *Credential    `json:"credential"`
}

// Target names what a probe measures; the agent resolves it to a port of this host.
type Target struct {
	Kind     string `json:"kind"`
	Name     string `json:"name"`
	PortHint int    `json:"port_hint"`
	Scheme   string `json:"scheme"`
}

// Credential names the stored credential a probe uses and how it presents it, never the value.
type Credential struct {
	Ref string `json:"ref"`
	Use string `json:"use"`
}

// The statuses of a result (the monitoring service's probe check reads them).
const (
	StatusOK      = "ok"
	StatusError   = "error"
	StatusInvalid = "invalid"
)

// Result is the last run of one probe. TS is when it started (Unix seconds): the monitoring service
// rates a result by its age, so a result is sent with its own time in every report until the next run.
type Result struct {
	TS         int64          `json:"ts"`
	DurationMS int64          `json:"duration_ms"`
	Status     string         `json:"status"`
	Values     map[string]any `json:"values"`
	Error      string         `json:"error"`
}

// UnmarshalJSON keeps the numbers of Values as they were written (json.Number): a result read back
// from the report state goes out again unchanged, a large integer included.
func (r *Result) UnmarshalJSON(data []byte) error {
	type plain Result
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.UseNumber()
	return dec.Decode((*plain)(r))
}

// Results is the last result of every probe, by probe id.
type Results map[string]Result

// Sensor measures one probe under ctx and returns the values it read. ctx carries the probe's timeout.
type Sensor func(ctx context.Context, p Probe) (map[string]any, error)

// sensors are the sensors by name; a probe naming another one is invalid.
var sensors = map[string]Sensor{}

// maxErrorRunes caps a result's error text.
const maxErrorRunes = 256

// Run runs p with the sensor it names, under p's timeout and ctx, and returns its result started at
// start. It never panics: a sensor that does is an error of this probe, not of the report.
func Run(ctx context.Context, p Probe, start time.Time) Result {
	res := Result{TS: start.Unix(), Values: map[string]any{}}
	sensor, ok := sensors[p.Sensor]
	if !ok {
		res.Status = StatusInvalid
		res.Error = cleanError(fmt.Sprintf("unknown sensor %q", p.Sensor))
		return res
	}
	timeout := time.Duration(p.TimeoutS) * time.Second
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	began := time.Now()
	values, err := callSensor(ctx, sensor, p)
	res.DurationMS = time.Since(began).Milliseconds()
	switch {
	case err == nil:
		res.Status = StatusOK
		if values != nil {
			res.Values = values
		}
	case errors.Is(err, context.DeadlineExceeded):
		res.Status = StatusError
		res.Error = cleanError(fmt.Sprintf("timed out after %s", timeout))
	default:
		res.Status = StatusError
		res.Error = cleanError(err.Error())
	}
	return res
}

// callSensor calls sensor and turns a panic into an error. The panic value goes to the local log only:
// it may hold what the sensor read, and the report must not.
func callSensor(ctx context.Context, sensor Sensor, p Probe) (values map[string]any, err error) {
	defer func() {
		if r := recover(); r != nil {
			logger.Errorf("probe %s: sensor %s panicked: %v\n%s", p.ID, p.Sensor, r, debug.Stack())
			values, err = nil, errors.New("the sensor failed unexpectedly")
		}
	}()
	return sensor(ctx, p)
}

// cleanError makes s fit the report: without NUL, which makes the monitoring service refuse the whole
// report, and at most maxErrorRunes runes.
func cleanError(s string) string {
	s = strings.ToValidUTF8(strings.ReplaceAll(s, "\x00", ""), "�")
	if utf8.RuneCountInString(s) <= maxErrorRunes {
		return s
	}
	return string([]rune(s)[:maxErrorRunes])
}
