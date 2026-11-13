// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"net"
	"reflect"
	"strings"
	"testing"
	"time"
)

// pm2JList has the form of pm2 jlist (checked against pm2 7.1.2), shortened: an app online with a
// secret in its environment, one errored after 15 restarts, one stopped.
const pm2JList = `[{"pid":62,"name":"shop","pm2_env":{"name":"shop","env":{"SECRET_X":"s3cr3t"},"SECRET_X":"s3cr3t",` +
	`"status":"online","restart_time":0,"unstable_restarts":0,"pm_id":0},"pm_id":0,"monit":{"memory":1,"cpu":0}},` +
	`{"pid":0,"name":"worker","pm2_env":{"name":"worker","status":"errored","restart_time":15,"unstable_restarts":0},"pm_id":1},` +
	`{"pid":0,"name":"cron","pm2_env":{"name":"cron","status":"stopped","restart_time":2,"unstable_restarts":1},"pm_id":2}]`

// stubPM2 makes /home/<user> the home of every user and serves the daemon's socket when running; it
// returns the sockets dialed.
func stubPM2(t *testing.T, running bool) *[]string {
	t.Helper()
	var dialed []string
	oldHome, oldDial := pm2Home, pm2Dial
	pm2Home = func(name string) (string, error) {
		if name == "nobody-here" {
			return "", errors.New("user: unknown user nobody-here")
		}
		return "/home/" + name, nil
	}
	pm2Dial = func(_ context.Context, path string) (net.Conn, error) {
		dialed = append(dialed, path)
		if !running {
			return nil, errNoListener
		}
		client, server := net.Pipe()
		t.Cleanup(func() { _ = server.Close() })
		return client, nil
	}
	t.Cleanup(func() { pm2Home, pm2Dial = oldHome, oldDial })
	return &dialed
}

func TestPM2AppsCountsTheAppsAsTheUserOfTheUnit(t *testing.T) {
	dialed := stubPM2(t, true)
	calls := stubTools(t, answer{out: pm2JList})

	res := Run(context.Background(), appProbe("pm2_apps", unitTarget("pm2-web.service"),
		"apps", "apps_errored", "apps_stopped", "restarts"), time.Now(), nil)

	if res.Status != StatusOK {
		t.Fatalf("result = %+v, want ok", res)
	}
	want := map[string]any{"apps": 3, "apps_errored": 1, "apps_stopped": 1, "restarts": int64(17)}
	if !reflect.DeepEqual(res.Values, want) {
		t.Errorf("values = %v, want %v", res.Values, want)
	}
	noneOf(t, res.Values, "shop", "worker", "cron", "s3cr3t", "web")
	if want := [][]string{{"runuser", "-u", "web", "--", "pm2", "jlist"}}; !reflect.DeepEqual(*calls, want) {
		t.Errorf("calls = %q, want %q", *calls, want)
	}
	if strings.Join(*dialed, " ") != "/home/web/.pm2/rpc.sock" {
		t.Errorf("dialed %q, want the daemon's socket in the user's home", *dialed)
	}

	stubTools(t, answer{out: "[]\n"})
	if got, err := pm2Apps(context.Background(), Target{Kind: kindUnit, Name: "pm2-web"}); err != nil ||
		!reflect.DeepEqual(got, map[string]any{"apps": 0, "apps_errored": 0, "apps_stopped": 0, "restarts": int64(0)}) {
		t.Errorf("no apps = %v, %v", got, err)
	}
}

func TestPM2AppsStartsNoDaemonAndRunsNothingAsRoot(t *testing.T) {
	for name, c := range map[string]struct {
		unit    string
		running bool
		dials   int
		want    string
	}{
		"no daemon":     {"pm2-web.service", false, 1, "does not run"},
		"root":          {"pm2-root.service", true, 0, "other than root"},
		"no pm2":        {"nginx.service", true, 0, "no pm2"},
		"an odd user":   {"pm2-We b.service", true, 0, "no pm2"},
		"unknown user":  {"pm2-nobody-here.service", true, 0, "is unknown"},
		"a pm2 service": {"pm2.service", true, 0, "no pm2"},
	} {
		t.Run(name, func(t *testing.T) {
			dialed := stubPM2(t, c.running)
			calls := stubTools(t)
			_, err := pm2Apps(context.Background(), Target{Kind: kindUnit, Name: c.unit})
			if !errors.Is(err, ErrUnsupported) || !strings.Contains(err.Error(), c.want) {
				t.Errorf("pm2Apps = %v, want unsupported: %s", err, c.want)
			}
			if len(*calls) != 0 || len(*dialed) != c.dials {
				t.Errorf("ran %q and dialed %q, want no call and %d dials", *calls, *dialed, c.dials)
			}
		})
	}
}

func TestPM2AppsWithoutItsToolsIsUnsupported(t *testing.T) {
	for name, a := range map[string]answer{
		"no runuser": {err: notInstalled("runuser")},
		"no pm2":     {err: toolExit(t, 127, "runuser: failed to execute pm2: No such file or directory")},
	} {
		t.Run(name, func(t *testing.T) {
			stubPM2(t, true)
			stubTools(t, a)
			if _, err := pm2Apps(context.Background(), Target{Kind: kindUnit, Name: "pm2-web"}); !errors.Is(err, ErrUnsupported) {
				t.Errorf("pm2Apps = %v, want unsupported", err)
			}
		})
	}
}

func TestPM2AppsFailsOnAnAnswerOfAnotherForm(t *testing.T) {
	for name, a := range map[string]answer{
		"the banner of a new daemon": {out: "\n   -------------\n__/\\\\\\\\\n[PM2] Spawning PM2 daemon\n[]"},
		"no status":                  {out: `[{"pm2_env":{"restart_time":0}}]`},
		"no restarts":                {out: `[{"pm2_env":{"status":"online"}}]`},
		"no pm2_env":                 {out: `[{"name":"shop"}]`},
		"an object":                  {out: `{"status":"online"}`},
		"a failure":                  {err: toolExit(t, 1, "[PM2][ERROR] Daemon not launched")},
	} {
		t.Run(name, func(t *testing.T) {
			stubPM2(t, true)
			stubTools(t, a)
			_, err := pm2Apps(context.Background(), Target{Kind: kindUnit, Name: "pm2-web"})
			if err == nil || errors.Is(err, ErrUnsupported) || !strings.HasPrefix(err.Error(), "pm2: ") {
				t.Errorf("pm2Apps = %v, want an error of pm2", err)
			}
		})
	}
}
