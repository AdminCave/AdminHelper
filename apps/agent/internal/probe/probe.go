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

	"adminhelper-agent/internal/credentials"
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

// Credential names the stored credential a probe uses and how it presents it (bearer, basic,
// redis_auth, header:<name>), never the value.
type Credential struct {
	Ref string `json:"ref"`
	Use string `json:"use"`
}

// The statuses of a result (the monitoring service's probe check reads them).
const (
	StatusOK      = "ok"
	StatusError   = "error"
	StatusInvalid = "invalid"
	// StatusDenied: the target refused the probe's credential (401/403), and the probe waits until
	// the credential is set anew (the access brake).
	StatusDenied = "denied"
	// StatusNotAllowed: the target is no address of this host, or one the agent never probes.
	StatusNotAllowed = "not_allowed"
	// StatusNoCredential: the credential the probe names is not stored on this host.
	StatusNoCredential = "no_credential"
	// StatusUnsupported: the sensor cannot run on this host (no systemd, no docker, a platform
	// without the sensor).
	StatusUnsupported = "unsupported"
	// StatusAmbiguousTarget: the target listens on several ports and none is its port hint.
	StatusAmbiguousTarget = "ambiguous_target"
)

// The errors a sensor returns to set a status other than error; it may wrap them.
var (
	// ErrDenied: the target refused the credential (HTTP 401/403, or the protocol's own refusal).
	ErrDenied = errors.New("access denied")
	// ErrNotAllowed: the guard refused the target (Guard).
	ErrNotAllowed = errors.New("target not allowed")
	// ErrInvalid: the probe's parameters are none the sensor can run.
	ErrInvalid = errors.New("invalid probe")
	// ErrUnsupported: the sensor cannot run on this host.
	ErrUnsupported = errors.New("not supported on this host")
	// ErrAmbiguousTarget: the target listens on several ports and none is its port hint.
	ErrAmbiguousTarget = errors.New("ambiguous target")
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

// Sensor measures one probe under ctx and returns the values it read; only those the probe's fields
// ask for go out (release). ctx carries the probe's timeout. secret is the stored credential the
// probe names, "" if it names none.
type Sensor func(ctx context.Context, p Probe, secret string) (map[string]any, error)

// sensors are the sensors by name; a probe naming another one (or a cursorSensor) is invalid.
var sensors = map[string]Sensor{}

// A cursorSensor counts what happened since its probe's last run: it gets the cursor that run left
// ("" for none) and returns its values and the cursor the next run starts from ("" to start afresh).
type cursorSensor func(ctx context.Context, p Probe, cursor string) (map[string]any, string, error)

// cursorSensors are the counting sensors by name; Run hands each the cursor of its probe (Access).
var cursorSensors = map[string]cursorSensor{}

// maxErrorRunes caps a result's error text.
const maxErrorRunes = 256

// Access is what the probes of one run may present: the stored credentials and the access brake.
type Access struct {
	// Credentials are the stored credentials by ref (credentials.Load).
	Credentials map[string]credentials.Credential
	// StoreErr is why the stored credentials could not be read; then no probe gets one.
	StoreErr error
	// Brake holds, by ref, the id of a credential whose target refused it: a probe with it does not
	// run again until it is set anew, which gives it a new id. Run adds to it; the report state keeps
	// it from run to run (KeptBrake).
	Brake map[string]string
	// Cursors holds, by probe id, where the last run of a counting sensor stopped (cursorSensor). Run
	// sets it; the report state keeps it from run to run (KeptCursors).
	Cursors map[string]string
}

// cursor returns where the last run of the probe id stopped, "" for nowhere.
func (a *Access) cursor(id string) string {
	if a == nil {
		return ""
	}
	return a.Cursors[id]
}

// setCursor makes cursor where the next run of the probe id starts; "" drops its cursor.
func (a *Access) setCursor(id, cursor string) {
	switch {
	case a == nil:
	case cursor == "":
		delete(a.Cursors, id)
	default:
		if a.Cursors == nil {
			a.Cursors = map[string]string{}
		}
		a.Cursors[id] = cursor
	}
}

// KeptCursors returns the cursors of those of probes that count (cursorSensor). The cursor of a probe
// no longer in the plan, or of one that measures with another sensor now, is done.
func (a *Access) KeptCursors(probes []Probe) map[string]string {
	if a == nil || len(a.Cursors) == 0 {
		return nil
	}
	kept := map[string]string{}
	for _, p := range probes {
		if c, ok := a.Cursors[p.ID]; ok && cursorSensors[p.Sensor] != nil {
			kept[p.ID] = c
		}
	}
	if len(kept) == 0 {
		return nil
	}
	return kept
}

// credential returns the secret p presents, or the status and the reason why p does not run.
func (a *Access) credential(p Probe) (secret, status, why string) {
	if p.Credential == nil {
		return "", "", ""
	}
	ref := p.Credential.Ref
	switch {
	case a == nil:
		return "", StatusNoCredential, "no credentials were read"
	case a.StoreErr != nil:
		return "", StatusNoCredential, a.StoreErr.Error()
	}
	c, ok := a.Credentials[ref]
	if !ok {
		return "", StatusNoCredential, fmt.Sprintf("set it with: adminhelper-agent monitor credential set %s", ref)
	}
	if braked, ok := a.Brake[ref]; ok {
		if braked == c.ID {
			return "", StatusDenied, fmt.Sprintf("credential %s was refused; set it anew to try again", ref)
		}
		// Set anew since its target refused it: the probe runs again.
		delete(a.Brake, ref)
	}
	return c.Secret, "", ""
}

// brake stops the probes with p's credential until it is set anew; false if p presents none.
func (a *Access) brake(p Probe) bool {
	if p.Credential == nil || a == nil {
		return false
	}
	c, ok := a.Credentials[p.Credential.Ref]
	if !ok {
		return false
	}
	if a.Brake == nil {
		a.Brake = map[string]string{}
	}
	a.Brake[p.Credential.Ref] = c.ID
	return true
}

// KeptBrake returns the entries of the brake whose credential is still stored with the id the
// target refused; an entry of a credential set anew or deleted is done. When the credentials could
// not be read, it keeps every entry: nothing says they changed.
func (a *Access) KeptBrake() map[string]string {
	if a == nil || len(a.Brake) == 0 {
		return nil
	}
	kept := map[string]string{}
	for ref, id := range a.Brake {
		if c, ok := a.Credentials[ref]; a.StoreErr != nil || (ok && c.ID == id) {
			kept[ref] = id
		}
	}
	if len(kept) == 0 {
		return nil
	}
	return kept
}

// Run runs p with the sensor it names, under p's timeout and ctx, with the credential p names from
// acc, and returns its result started at start. It never panics: a sensor that does is an error of
// this probe, not of the report.
func Run(ctx context.Context, p Probe, start time.Time, acc *Access) Result {
	res := Result{TS: start.Unix(), Values: map[string]any{}}
	sensor, ok := sensors[p.Sensor]
	counter, counts := cursorSensors[p.Sensor]
	if !ok && !counts {
		res.Status = StatusInvalid
		res.Error = cleanError(fmt.Sprintf("unknown sensor %q", p.Sensor))
		return res
	}
	secret, status, why := acc.credential(p)
	if status != "" {
		res.Status = status
		res.Error = cleanError(why)
		return res
	}
	cursor := acc.cursor(p.ID)
	if counts {
		sensor = func(ctx context.Context, p Probe, _ string) (map[string]any, error) {
			values, next, err := counter(ctx, p, cursor)
			cursor = next
			return values, err
		}
	}
	timeout := time.Duration(p.TimeoutS) * time.Second
	run := ctx
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	began := time.Now()
	values, err := callSensor(ctx, sensor, p, secret)
	res.DurationMS = time.Since(began).Milliseconds()
	if counts && run.Err() == nil {
		// A probe the run ended under keeps its last result (runDueProbes), so it keeps its cursor too.
		acc.setCursor(p.ID, cursor)
	}
	switch {
	case err == nil:
		res.Status = StatusOK
		res.Values = release(values, p.Fields)
	case errors.Is(err, ErrNotAllowed):
		res.Status = StatusNotAllowed
		res.Error = cleanError(err.Error())
	case errors.Is(err, ErrInvalid):
		res.Status = StatusInvalid
		res.Error = cleanError(err.Error())
	case errors.Is(err, ErrUnsupported):
		res.Status = StatusUnsupported
		res.Error = cleanError(err.Error())
	case errors.Is(err, ErrAmbiguousTarget):
		res.Status = StatusAmbiguousTarget
		res.Error = cleanError(err.Error())
	case errors.Is(err, ErrDenied) && acc.brake(p):
		res.Status = StatusDenied
		res.Error = cleanError(err.Error())
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
func callSensor(ctx context.Context, sensor Sensor, p Probe, secret string) (values map[string]any, err error) {
	defer func() {
		if r := recover(); r != nil {
			logger.Errorf("probe %s: sensor %s panicked: %v\n%s", p.ID, p.Sensor, r, debug.Stack())
			values, err = nil, errors.New("the sensor failed unexpectedly")
		}
	}()
	return sensor(ctx, p, secret)
}

// cleanError makes s fit the report: without NUL, which makes the monitoring service refuse the whole
// report, and at most maxErrorRunes runes.
func cleanError(s string) string {
	return cutRunes(s, maxErrorRunes)
}

// cutRunes returns s without NUL, as valid UTF-8 and cut to n runes.
func cutRunes(s string, n int) string {
	s = strings.ToValidUTF8(strings.ReplaceAll(s, "\x00", ""), "�")
	if utf8.RuneCountInString(s) <= n {
		return s
	}
	return string([]rune(s)[:n])
}
