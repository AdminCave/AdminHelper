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

// credView registers a view that takes a password and hands it to a command, as the backup views do.
func credView(t *testing.T) *[][]string {
	t.Helper()
	var envs [][]string
	appViews["test_cred"] = appView{kinds: unitKinds, uses: []string{usePassword},
		readCred: func(ctx context.Context, _ Target, c appCredential) (map[string]any, error) {
			env, err := passwordEnv(c, "RESTIC_PASSWORD")
			if err != nil {
				return nil, err
			}
			if _, err := runToolEnv(ctx, toolTimeout, env, "restic", "version"); err != nil {
				return nil, err
			}
			envs = append(envs, env)
			return map[string]any{"ok": true}, nil
		}}
	old := runToolEnv
	runToolEnv = func(context.Context, time.Duration, []string, string, ...string) ([]byte, error) { return nil, nil }
	t.Cleanup(func() {
		delete(appViews, "test_cred")
		runToolEnv = old
	})
	return &envs
}

func TestAViewTakesTheCredentialOfItsUseOnly(t *testing.T) {
	envs := credView(t)
	p := appProbe("test_cred", unitTarget("restic-backup.service"), "ok")
	p.Credential = &Credential{Ref: "repo", Use: usePassword}
	acc := access(map[string][2]string{"repo": {"s3cr3t", "id1"}})

	if res := Run(context.Background(), p, start, acc); res.Status != StatusOK {
		t.Fatalf("a password for its view = %+v, want ok", res)
	}
	if len(*envs) != 1 || strings.Join((*envs)[0], ",") != "RESTIC_PASSWORD=s3cr3t" {
		t.Errorf("environment %q, want the password in RESTIC_PASSWORD alone", *envs)
	}

	for name, use := range map[string]string{"bearer": useBearer, "a header": "header:X-Key", "basic": useBasic} {
		q := p
		q.Credential = &Credential{Ref: "repo", Use: use}
		if _, err := appSensor(context.Background(), q, "s3cr3t"); !errors.Is(err, ErrInvalid) {
			t.Errorf("%s for a password view = %v, want ErrInvalid", name, err)
		}
	}

	// Without a credential the view runs without one.
	q := p
	q.Credential = nil
	if _, err := appSensor(context.Background(), q, ""); err != nil {
		t.Errorf("no credential = %v, want the view to run", err)
	}
	if len(*envs) != 2 || (*envs)[1] != nil {
		t.Errorf("environment without a credential %q, want none", (*envs)[1:])
	}
}

func TestAViewWithoutUsesRefusesEveryCredential(t *testing.T) {
	stubRecordingDir(t)
	for _, use := range []string{usePassword, useBearer, "header:Authorization"} {
		p := appProbe("bbb_recordings", unitTarget("bbb-web.service"))
		p.Credential = &Credential{Ref: "x", Use: use}
		if _, err := appSensor(context.Background(), p, "secret"); !errors.Is(err, ErrInvalid) {
			t.Errorf("a credential for %s = %v, want ErrInvalid", use, err)
		}
	}
}

func TestAPasswordIsNeverQuotedAndNeverEmpty(t *testing.T) {
	for name, c := range map[string]appCredential{
		"empty":     {use: usePassword},
		"NUL":       {use: usePassword, secret: "ab\x00cd"},
		"wrong use": {use: useBearer, secret: "s3cr3t"},
	} {
		env, err := passwordEnv(c, "BORG_PASSPHRASE")
		if !errors.Is(err, ErrInvalid) || env != nil || (c.secret != "" && strings.Contains(err.Error(), c.secret)) {
			t.Errorf("%s = %q, %v; want ErrInvalid without the secret", name, env, err)
		}
	}
}

func TestOtherSensorsRefuseAPassword(t *testing.T) {
	for _, sensor := range []string{"http", "tls", "dns"} {
		p := Probe{Sensor: sensor, Credential: &Credential{Ref: "x", Use: usePassword}}
		if _, err := credentialUse(p, useBearer, useBasic, useHeader, useRedisAuth); !errors.Is(err, ErrInvalid) {
			t.Errorf("%s with a password = %v, want ErrInvalid", sensor, err)
		}
	}
}
