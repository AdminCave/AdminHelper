// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"reflect"
	"strings"
	"testing"
	"time"
	"unicode/utf8"

	"adminhelper-agent/internal/credentials"
)

// register adds a sensor for the test and removes it afterwards.
func register(t *testing.T, name string, sensor Sensor) {
	t.Helper()
	old, had := sensors[name]
	sensors[name] = sensor
	t.Cleanup(func() {
		if had {
			sensors[name] = old
		} else {
			delete(sensors, name)
		}
	})
}

var start = time.Unix(1762700000, 0)

func TestAnUnknownSensorIsInvalid(t *testing.T) {
	res := Run(context.Background(), Probe{ID: "c1", Sensor: "nope", TimeoutS: 10}, start, nil)

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
	register(t, "fake", func(ctx context.Context, p Probe, _ string) (map[string]any, error) {
		deadline, _ = ctx.Deadline()
		return map[string]any{"status": "OK", "token": "read along"}, nil
	})

	before := time.Now()
	res := Run(context.Background(), Probe{ID: "c1", Sensor: "fake", TimeoutS: 7, Fields: []string{"status"}}, start, nil)
	after := time.Now()

	if res.Status != StatusOK || res.Error != "" || res.Values["status"] != "OK" || res.TS != start.Unix() {
		t.Fatalf("result = %+v", res)
	}
	if _, ok := res.Values["token"]; ok || len(res.Values) != 1 {
		t.Errorf("values = %v, want the asked field status alone", res.Values)
	}
	if deadline.Before(before.Add(7*time.Second)) || deadline.After(after.Add(7*time.Second)) {
		t.Errorf("the sensor's deadline is %s after the run's start, want the probe's 7 s", deadline.Sub(before))
	}
}

func TestASensorWithoutValuesSendsAnEmptyMap(t *testing.T) {
	register(t, "fake", func(context.Context, Probe, string) (map[string]any, error) { return nil, nil })

	res := Run(context.Background(), Probe{ID: "c1", Sensor: "fake", TimeoutS: 1}, start, nil)

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
	register(t, "slow", func(ctx context.Context, p Probe, _ string) (map[string]any, error) {
		<-ctx.Done()
		return map[string]any{"x": 1}, ctx.Err()
	})

	res := Run(context.Background(), Probe{ID: "c1", Sensor: "slow", TimeoutS: 1}, start, nil)

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
	register(t, "fake", func(context.Context, Probe, string) (map[string]any, error) {
		return map[string]any{"x": 1}, errors.New("connection refused")
	})

	res := Run(context.Background(), Probe{ID: "c1", Sensor: "fake", TimeoutS: 1}, start, nil)

	if res.Status != StatusError || res.Error != "connection refused" || len(res.Values) != 0 {
		t.Fatalf("result = %+v", res)
	}
}

func TestAPanickingSensorIsAnErrorOfItsProbe(t *testing.T) {
	register(t, "boom", func(context.Context, Probe, string) (map[string]any, error) {
		panic("secret-value-in-panic")
	})

	res := Run(context.Background(), Probe{ID: "c1", Sensor: "boom", TimeoutS: 1}, start, nil)

	if res.Status != StatusError || res.Error != "the sensor failed unexpectedly" {
		t.Fatalf("result = %+v", res)
	}
	if strings.Contains(res.Error, "secret") {
		t.Errorf("error = %q carries the panic value", res.Error)
	}
}

func TestAnErrorIsCleanedForTheReport(t *testing.T) {
	long := strings.Repeat("ä", 300)
	register(t, "fake", func(context.Context, Probe, string) (map[string]any, error) {
		return nil, errors.New("a\x00b \xff " + long)
	})

	res := Run(context.Background(), Probe{ID: "c1", Sensor: "fake", TimeoutS: 1}, start, nil)

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
	res := Run(context.Background(), Probe{ID: "c1", Sensor: strings.Repeat("x", 400) + "\x00"}, start, nil)

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

// access holds the stored credentials of a test, by ref: secret and id.
func access(creds map[string][2]string) *Access {
	acc := &Access{Credentials: map[string]credentials.Credential{}}
	for ref, c := range creds {
		acc.Credentials[ref] = credentials.Credential{Secret: c[0], ID: c[1]}
	}
	return acc
}

func TestAProbeGetsTheSecretOfTheCredentialItNames(t *testing.T) {
	got := map[string]string{}
	register(t, "fake", func(_ context.Context, p Probe, secret string) (map[string]any, error) {
		got[p.ID] = secret
		return nil, nil
	})
	acc := access(map[string][2]string{"db": {"pw", "id1"}})

	withCred := Run(context.Background(), Probe{ID: "c1", Sensor: "fake", TimeoutS: 1, Credential: &Credential{Ref: "db", Use: "basic"}}, start, acc)
	without := Run(context.Background(), Probe{ID: "c2", Sensor: "fake", TimeoutS: 1}, start, acc)

	if withCred.Status != StatusOK || without.Status != StatusOK {
		t.Fatalf("results = %+v, %+v", withCred, without)
	}
	if got["c1"] != "pw" || got["c2"] != "" {
		t.Errorf("secrets = %q, want pw for the probe naming db and none for the other", got)
	}
}

func TestAProbeWithoutItsCredentialDoesNotRun(t *testing.T) {
	ran := false
	register(t, "fake", func(context.Context, Probe, string) (map[string]any, error) {
		ran = true
		return nil, nil
	})
	p := Probe{ID: "c1", Sensor: "fake", TimeoutS: 1, Credential: &Credential{Ref: "db", Use: "bearer"}}
	cases := []struct {
		name string
		acc  *Access
		want string
	}{
		{"none read", nil, "no credentials were read"},
		{"not stored", access(map[string][2]string{"web": {"pw", "id1"}}), "adminhelper-agent monitor credential set db"},
		{"store unreadable", &Access{StoreErr: errors.New("credentials.json is open to other accounts")}, "open to other accounts"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			ran = false
			res := Run(context.Background(), p, start, c.acc)
			if res.Status != StatusNoCredential || !strings.Contains(res.Error, c.want) || len(res.Values) != 0 {
				t.Fatalf("result = %+v, want no_credential naming %q", res, c.want)
			}
			if ran {
				t.Error("the sensor ran without the credential")
			}
		})
	}
}

func TestARefusedCredentialRestsItsProbesUntilItIsSetAnew(t *testing.T) {
	calls := 0
	refuse := true
	register(t, "fake", func(_ context.Context, p Probe, _ string) (map[string]any, error) {
		calls++
		if refuse && p.Credential.Ref == "db" {
			return nil, fmt.Errorf("%w: HTTP 401", ErrDenied)
		}
		return map[string]any{"up": true}, nil
	})
	acc := access(map[string][2]string{"db": {"old", "id1"}, "web": {"pw", "id2"}})
	db := Probe{ID: "c1", Sensor: "fake", TimeoutS: 1, Fields: []string{"up"}, Credential: &Credential{Ref: "db", Use: "basic"}}
	web := Probe{ID: "c2", Sensor: "fake", TimeoutS: 1, Fields: []string{"up"}, Credential: &Credential{Ref: "web", Use: "bearer"}}

	if res := Run(context.Background(), db, start, acc); res.Status != StatusDenied || !strings.Contains(res.Error, "HTTP 401") {
		t.Fatalf("first run = %+v, want denied with the target's answer", res)
	}
	if acc.Brake["db"] != "id1" {
		t.Fatalf("brake = %v, want db at the refused id1", acc.Brake)
	}

	refuse = false
	calls = 0
	res := Run(context.Background(), db, start, acc)
	if res.Status != StatusDenied || !strings.Contains(res.Error, "set it anew") || calls != 0 {
		t.Fatalf("second run = %+v after %d sensor calls, want denied without a try", res, calls)
	}
	if res := Run(context.Background(), web, start, acc); res.Status != StatusOK || calls != 1 {
		t.Fatalf("the probe with another credential = %+v, want it to run", res)
	}

	acc.Credentials["db"] = credentials.Credential{Secret: "new", ID: "id3"}
	if res := Run(context.Background(), db, start, acc); res.Status != StatusOK || res.Values["up"] != true {
		t.Fatalf("run after the credential was set anew = %+v, want ok", res)
	}
	if _, braked := acc.Brake["db"]; braked {
		t.Errorf("brake = %v, want db released", acc.Brake)
	}
}

func TestADenialWithoutACredentialIsAnError(t *testing.T) {
	register(t, "fake", func(context.Context, Probe, string) (map[string]any, error) {
		return nil, fmt.Errorf("%w: HTTP 403", ErrDenied)
	})
	acc := access(nil)

	res := Run(context.Background(), Probe{ID: "c1", Sensor: "fake", TimeoutS: 1}, start, acc)

	if res.Status != StatusError || !strings.Contains(res.Error, "HTTP 403") {
		t.Fatalf("result = %+v, want an error: there is no credential to rest", res)
	}
	if len(acc.Brake) != 0 {
		t.Errorf("brake = %v, want none", acc.Brake)
	}
}

func TestTheGuardsAndTheSensorsRefusalsHaveTheirOwnStatus(t *testing.T) {
	cases := []struct {
		err  error
		want string
	}{
		{fmt.Errorf("dial tcp 192.0.2.7:80: %w: 192.0.2.7 is no address of this host", ErrNotAllowed), StatusNotAllowed},
		{fmt.Errorf("%w: method POST", ErrInvalid), StatusInvalid},
		{fmt.Errorf("%w: a container target on Windows", ErrUnsupported), StatusUnsupported},
		{fmt.Errorf("%w: port 8080 listens on ports 80, 443 and none is the hint 8080", ErrAmbiguousTarget), StatusAmbiguousTarget},
	}
	for _, c := range cases {
		t.Run(c.want, func(t *testing.T) {
			register(t, "fake", func(context.Context, Probe, string) (map[string]any, error) {
				return map[string]any{"x": 1}, c.err
			})
			res := Run(context.Background(), Probe{ID: "c1", Sensor: "fake", TimeoutS: 1, Fields: []string{"x"}}, start, nil)
			if res.Status != c.want || res.Error != c.err.Error() || len(res.Values) != 0 {
				t.Fatalf("result = %+v, want %s with the error and no values", res, c.want)
			}
		})
	}
}

func TestKeptBrakeKeepsOnlyCredentialsStillAsRefused(t *testing.T) {
	brake := func() map[string]string { return map[string]string{"same": "id1", "anew": "id2", "deleted": "id3"} }
	acc := access(map[string][2]string{"same": {"a", "id1"}, "anew": {"b", "id9"}})
	acc.Brake = brake()
	if got := acc.KeptBrake(); len(got) != 1 || got["same"] != "id1" {
		t.Errorf("KeptBrake = %v, want same alone", got)
	}

	unread := &Access{StoreErr: errors.New("unreadable"), Brake: brake()}
	if got := unread.KeptBrake(); len(got) != 3 {
		t.Errorf("KeptBrake with unreadable credentials = %v, want every entry", got)
	}

	if got := access(nil).KeptBrake(); got != nil {
		t.Errorf("KeptBrake without a brake = %v, want nil", got)
	}
	var none *Access
	if got := none.KeptBrake(); got != nil {
		t.Errorf("KeptBrake of no access = %v, want nil", got)
	}
}

// registerCounter adds a counting sensor for the test and removes it afterwards.
func registerCounter(t *testing.T, name string, sensor cursorSensor) {
	t.Helper()
	cursorSensors[name] = sensor
	t.Cleanup(func() { delete(cursorSensors, name) })
}

func TestACountingSensorCountsFromTheCursorItsLastRunLeft(t *testing.T) {
	var got []string
	next := "c2"
	registerCounter(t, "counter", func(_ context.Context, _ Probe, cursor string) (map[string]any, string, error) {
		got = append(got, cursor)
		return map[string]any{"count": 4}, next, nil
	})
	acc := &Access{Cursors: map[string]string{"c1": "c1", "other": "o1"}}
	p := Probe{ID: "c1", Sensor: "counter", TimeoutS: 1, Fields: []string{"count"}}

	res := Run(context.Background(), p, start, acc)

	if res.Status != StatusOK || res.Values["count"] != 4 {
		t.Fatalf("result = %+v, want ok with the count", res)
	}
	if !reflect.DeepEqual(acc.Cursors, map[string]string{"c1": "c2", "other": "o1"}) {
		t.Fatalf("cursors = %v, want c1 at the cursor its run left, the other untouched", acc.Cursors)
	}

	// A run that leaves no cursor drops it: the next one starts afresh.
	next = ""
	Run(context.Background(), p, start, acc)
	Run(context.Background(), p, start, acc)

	if !reflect.DeepEqual(got, []string{"c1", "c2", ""}) {
		t.Errorf("the runs got the cursors %q, want c1, c2 and none", got)
	}
	if _, ok := acc.Cursors["c1"]; ok {
		t.Errorf("cursors = %v, want c1 dropped", acc.Cursors)
	}
}

func TestACountingSensorWithoutAccessCountsWithoutACursor(t *testing.T) {
	got := "unset"
	registerCounter(t, "counter", func(_ context.Context, _ Probe, cursor string) (map[string]any, string, error) {
		got = cursor
		return map[string]any{"count": 1}, "c2", nil
	})

	res := Run(context.Background(), Probe{ID: "c1", Sensor: "counter", TimeoutS: 1, Fields: []string{"count"}}, start, nil)

	if res.Status != StatusOK || got != "" {
		t.Fatalf("result = %+v with cursor %q, want ok without one", res, got)
	}
}

func TestACountingRunTheRunEndedOrThatPanickedKeepsItsCursor(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	registerCounter(t, "ended", func(context.Context, Probe, string) (map[string]any, string, error) {
		// The agent's run ends under the sensor (its deadline, a stop): runDueProbes keeps the probe's
		// last result, so the cursor of that result stays.
		cancel()
		return nil, "", context.Canceled
	})
	registerCounter(t, "boom", func(context.Context, Probe, string) (map[string]any, string, error) {
		panic("failed")
	})
	acc := &Access{Cursors: map[string]string{"c1": "c1", "c2": "c2"}}

	ended := Run(ctx, Probe{ID: "c1", Sensor: "ended", TimeoutS: 1}, start, acc)
	boom := Run(context.Background(), Probe{ID: "c2", Sensor: "boom", TimeoutS: 1}, start, acc)

	if ended.Status != StatusError || boom.Status != StatusError {
		t.Fatalf("results = %+v and %+v, want errors", ended, boom)
	}
	if !reflect.DeepEqual(acc.Cursors, map[string]string{"c1": "c1", "c2": "c2"}) {
		t.Errorf("cursors = %v, want both kept", acc.Cursors)
	}
}

func TestACountingSensorPastItsTimeoutDropsItsCursor(t *testing.T) {
	registerCounter(t, "slow", func(ctx context.Context, _ Probe, cursor string) (map[string]any, string, error) {
		<-ctx.Done()
		return nil, "", ctx.Err()
	})
	acc := &Access{Cursors: map[string]string{"c1": "c1"}}

	res := Run(context.Background(), Probe{ID: "c1", Sensor: "slow", TimeoutS: 1}, start, acc)

	if res.Status != StatusError || res.Error != "timed out after 1s" {
		t.Fatalf("result = %+v, want the timeout", res)
	}
	if len(acc.Cursors) != 0 {
		t.Errorf("cursors = %v, want c1 dropped: the probe's own timeout is no end of the run", acc.Cursors)
	}
}

func TestKeptCursorsKeepsOnlyThoseOfCountingProbesOfThePlan(t *testing.T) {
	noop := func(context.Context, Probe, string) (map[string]any, string, error) { return nil, "", nil }
	registerCounter(t, "counter", noop)
	register(t, "fake", func(context.Context, Probe, string) (map[string]any, error) { return nil, nil })
	acc := &Access{Cursors: map[string]string{"counts": "a", "switched": "b", "gone": "c"}}
	probes := []Probe{
		{ID: "counts", Sensor: "counter"},
		{ID: "switched", Sensor: "fake"},
		{ID: "fresh", Sensor: "counter"},
	}

	if got := acc.KeptCursors(probes); !reflect.DeepEqual(got, map[string]string{"counts": "a"}) {
		t.Errorf("kept = %v, want counts alone", got)
	}
	if got := acc.KeptCursors(probes[1:]); got != nil {
		t.Errorf("kept = %v without a counting probe with a cursor, want nil", got)
	}
	if got := (*Access)(nil).KeptCursors(probes); got != nil {
		t.Errorf("kept without access = %v, want nil", got)
	}
}

func TestACredentialGoesOnlyToTheTargetItWentToFirst(t *testing.T) {
	var got []string
	register(t, "fake", func(_ context.Context, _ Probe, secret string) (map[string]any, error) {
		got = append(got, secret)
		return map[string]any{"up": true}, nil
	})
	register(t, "other", func(_ context.Context, _ Probe, secret string) (map[string]any, error) {
		got = append(got, secret)
		return map[string]any{"up": true}, nil
	})
	first := Probe{ID: "c1", Sensor: "fake", TimeoutS: 1, Fields: []string{"up"},
		Target: &Target{Kind: kindProcess, Name: "nginx", PortHint: 8080, Scheme: "http"},
		Params: map[string]any{"path": "/status"}, Credential: &Credential{Ref: "db", Use: "bearer"}}
	acc := access(map[string][2]string{"db": {"pw", "id1"}})

	if res := Run(context.Background(), first, start, acc); res.Status != StatusOK || len(got) != 1 || got[0] != "pw" {
		t.Fatalf("first run = %+v, secrets %q; want ok with the secret", res, got)
	}
	// Another path of the same target and other fields are the same target.
	same := first
	same.ID, same.Params, same.Fields = "c2", map[string]any{"path": "/health"}, nil
	if res := Run(context.Background(), same, start, acc); res.Status != StatusOK || len(got) != 2 {
		t.Fatalf("the same target = %+v, want ok", res)
	}

	other := func(change func(p *Probe)) Probe {
		p := first
		tg := *first.Target
		p.Target, p.Credential = &tg, &Credential{Ref: "db", Use: "bearer"}
		change(&p)
		return p
	}
	for name, p := range map[string]Probe{
		"sensor": other(func(p *Probe) { p.Sensor = "other" }),
		"use":    other(func(p *Probe) { p.Credential.Use = "basic" }),
		"kind":   other(func(p *Probe) { p.Target.Kind = kindPort }),
		"name":   other(func(p *Probe) { p.Target.Name = "apache2" }),
		"port":   other(func(p *Probe) { p.Target.PortHint = 8081 }),
		"scheme": other(func(p *Probe) { p.Target.Scheme = "https" }),
		"none":   other(func(p *Probe) { p.Target = nil }),
	} {
		got = nil
		res := Run(context.Background(), p, start, acc)
		if res.Status != StatusNotAllowed || !strings.Contains(res.Error, "belongs to another target") || len(got) != 0 {
			t.Errorf("another %s = %+v, secrets %q; want not_allowed without the secret", name, res, got)
		}
	}

	// Set anew, the credential binds again where it goes first.
	acc.Credentials["db"] = credentials.Credential{Secret: "pw2", ID: "id2"}
	moved := other(func(p *Probe) { p.Target.PortHint = 8081 })
	got = nil
	if res := Run(context.Background(), moved, start, acc); res.Status != StatusOK || len(got) != 1 || got[0] != "pw2" {
		t.Fatalf("after it was set anew = %+v, secrets %q; want ok", res, got)
	}
	if res := Run(context.Background(), first, start, acc); res.Status != StatusNotAllowed {
		t.Fatalf("the old target after the new binding = %+v, want not_allowed", res)
	}
}

func TestACredentialOfTheAppSensorIsBoundToItsView(t *testing.T) {
	credView(t)
	appViews["test_cred2"] = appViews["test_cred"]
	t.Cleanup(func() { delete(appViews, "test_cred2") })
	view := func(name string) Probe {
		p := appProbe(name, unitTarget("restic-backup.service"), "ok")
		p.Credential = &Credential{Ref: "repo", Use: usePassword}
		return p
	}
	acc := access(map[string][2]string{"repo": {"pw", "id1"}})
	if res := Run(context.Background(), view("test_cred"), start, acc); res.Status != StatusOK {
		t.Fatalf("first run = %+v, want ok", res)
	}
	if res := Run(context.Background(), view("test_cred2"), start, acc); res.Status != StatusNotAllowed {
		t.Fatalf("another view = %+v, want not_allowed", res)
	}
}

func TestACredentialOfAUnixSocketIsBoundToItsPath(t *testing.T) {
	register(t, "unixsocket", func(context.Context, Probe, string) (map[string]any, error) {
		return map[string]any{"connected": true}, nil
	})
	sock := func(path string) Probe {
		return Probe{ID: "c1", Sensor: "unixsocket", TimeoutS: 1, Fields: []string{"connected"},
			Params: map[string]any{"path": path, "protocol": "redis"}, Credential: &Credential{Ref: "redis", Use: "redis_auth"}}
	}
	acc := access(map[string][2]string{"redis": {"pw", "id1"}})
	if res := Run(context.Background(), sock("/run/redis/redis.sock"), start, acc); res.Status != StatusOK {
		t.Fatalf("first run = %+v, want ok", res)
	}
	if res := Run(context.Background(), sock("/run/other/redis.sock"), start, acc); res.Status != StatusNotAllowed {
		t.Fatalf("another socket = %+v, want not_allowed", res)
	}
}

func TestKeptBindingsKeepOnlyCredentialsStillAsBound(t *testing.T) {
	bindings := func() map[string]Binding {
		return map[string]Binding{"same": {ID: "id1", Target: "a"}, "anew": {ID: "id2", Target: "b"}, "deleted": {ID: "id3", Target: "c"}}
	}
	acc := access(map[string][2]string{"same": {"a", "id1"}, "anew": {"b", "id9"}})
	acc.Bindings = bindings()
	if got := acc.KeptBindings(); len(got) != 1 || got["same"] != (Binding{ID: "id1", Target: "a"}) {
		t.Errorf("KeptBindings = %v, want same alone", got)
	}
	unread := &Access{StoreErr: errors.New("unreadable"), Bindings: bindings()}
	if got := unread.KeptBindings(); len(got) != 3 {
		t.Errorf("KeptBindings with unreadable credentials = %v, want every entry", got)
	}
	var none *Access
	if got := none.KeptBindings(); got != nil {
		t.Errorf("KeptBindings of no access = %v, want nil", got)
	}
}
