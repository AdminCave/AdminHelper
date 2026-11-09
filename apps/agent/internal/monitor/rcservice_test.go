// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"context"
	"io/fs"
	"os/exec"
	"reflect"
	"slices"
	"strings"
	"testing"
)

// The outputs below are rc.subr's (releng/14.3 and 15.0) and service.sh's; the script fixtures are
// cut from /etc/rc.d of 15.0. On FreeBSD itself services_freebsd_test.go runs the real service(8).
const (
	rcCronRunning      = "cron is running as pid 812.\n"
	rcSshdTwoPids      = "sshd is running as pid 905 1210.\n"
	rcNginxStopped     = "nginx is not running.\n"
	rcNewsyslogStopped = "newsyslog is not running.\n"
	// ftp-proxy's script sets name=ftpproxy: rc.subr prints the name, not the file name.
	rcFtpProxyStopped = "ftpproxy is not running.\n"
	// A script without status (no command, no status_cmd): rc.subr prints its usage to stderr only.
	rcUnknownDirective = ""
	rcNoSuchScript     = "nosuch does not exist in /etc/rc.d or the local startup\n" +
		"directories (/usr/local/etc/rc.d), or is not executable\n"
	// pf's status_cmd runs pfctl -s info.
	rcPfStatus = "Status: Enabled for 0 days 01:02:03           Debug: Urgent\n\nState Table   Total   Rate\n"

	rcNewsyslogScript = `#!/bin/sh
. /etc/rc.subr

name="newsyslog"
desc="Logfile rotation"
rcvar="newsyslog_enable"
required_files="/etc/newsyslog.conf"
command="/usr/sbin/${name}"
start_cmd="newsyslog_start"
stop_cmd=":"
`
	rcNginxScript = `#!/bin/sh
. /etc/rc.subr

name="nginx"
rcvar=nginx_enable
command="/usr/local/sbin/nginx"
pidfile="/var/run/nginx.pid"
`
)

func TestParseRCStatus(t *testing.T) {
	cases := []struct {
		name, out  string
		state, pid string
		ok         bool
	}{
		{"running", rcCronRunning, "active", "812", true},
		{"running with two pids", rcSshdTwoPids, "active", "905", true},
		{"not running", rcNginxStopped, "inactive", "", true},
		{"name differs from the file", rcFtpProxyStopped, "inactive", "", true},
		{"a status_precmd line first", "Checking config.\n" + rcCronRunning, "active", "812", true},
		{"unknown directive", rcUnknownDirective, "", "", false},
		{"no such script", rcNoSuchScript, "", "", false},
		{"status_cmd of its own", rcPfStatus, "", "", false},
		{"no pid", "cron is running as pid .\n", "", "", false},
		{"pid not a number", "cron is running as pid 81x.\n", "", "", false},
		{"no final dot", "cron is running as pid 812\n", "", "", false},
		{"no name", "is not running.\n", "", "", false},
	}
	for _, c := range cases {
		state, pid, ok := parseRCStatus([]byte(c.out))
		if state != c.state || pid != c.pid || ok != c.ok {
			t.Errorf("%s: parseRCStatus = (%q, %q, %v), want (%q, %q, %v)",
				c.name, state, pid, ok, c.state, c.pid, c.ok)
		}
	}
}

func TestRCNothingToStop(t *testing.T) {
	cases := []struct {
		name, script string
		want         bool
	}{
		{"newsyslog", rcNewsyslogScript, true},
		{"single quotes", "name=ddb\nstop_cmd=':'\n", true},
		{"no quotes", "stop_cmd=:\n", true},
		{"indented, with a comment", "case $1 in\n*)\n\tstop_cmd=\":\"  # nothing runs\n;;\nesac\n", true},
		{"a daemon", rcNginxScript, false},
		{"a stop function", "stop_cmd=\"cron_stop\"\n", false},
		{"commented out", "# stop_cmd=\":\"\n", false},
		{"more after the colon", "stop_cmd=\":; kill 1\"\n", false},
		{"another variable", "restart_cmd=\":\"\n", false},
	}
	for _, c := range cases {
		if got := reRCNothingToStop.MatchString(c.script); got != c.want {
			t.Errorf("%s: nothing to stop = %v, want %v", c.name, got, c.want)
		}
	}
}

func TestParseRCEnabled(t *testing.T) {
	out := "/etc/rc.d/syslogd\n/etc/rc.d/cron\n/usr/local/etc/rc.d/nginx\n" +
		// The same name in a local_startup directory and in /etc/rc.d: service(8) runs the latter.
		"/usr/local/etc/rc.d/devd\n/etc/rc.d/devd\n/etc/rc.d/sshd\n/usr/local/etc/rc.d/sshd\n" +
		// The same name in two local_startup directories: the first one listed.
		"/usr/local/etc/rc.d/zabbix\n/opt/rc.d/zabbix\n" +
		// Names service(8) would not take, and lines that are no path.
		"/etc/rc.d/-e\n/etc/rc.d/.hidden\n/etc/rc.d/..\nrc.d/relative\n/\n\n  /etc/rc.d/devfs  \n"
	want := []rcScript{
		{"cron", "/etc/rc.d/cron"},
		{"devd", "/etc/rc.d/devd"},
		{"devfs", "/etc/rc.d/devfs"},
		{"nginx", "/usr/local/etc/rc.d/nginx"},
		{"sshd", "/etc/rc.d/sshd"},
		{"syslogd", "/etc/rc.d/syslogd"},
		{"zabbix", "/usr/local/etc/rc.d/zabbix"},
	}
	if got := parseRCEnabled([]byte(out)); !reflect.DeepEqual(got, want) {
		t.Errorf("parseRCEnabled = %v, want %v", got, want)
	}
}

func TestRCScriptName(t *testing.T) {
	for _, name := range []string{"cron", "ftp-proxy", "adminhelper_frpc", "php_fpm", "php-fpm.8.3", "_x"} {
		if !reRCScriptName.MatchString(name) {
			t.Errorf("%q rejected, service(8) takes it", name)
		}
	}
	for _, name := range []string{"", ".", "..", ".hidden", "-e", "-j", "../cron", "a/b", "cron status",
		"nginx\n", "cron;id", "ftp proxy", "ö"} {
		if reRCScriptName.MatchString(name) {
			t.Errorf("%q accepted", name)
		}
	}
}

// rcCall is one answer of fakeService: the output of service(8) and how it ended.
type rcCall struct {
	out string
	err error
}

// fakeService answers each service(8) call from answers, keyed by its arguments joined by blanks;
// an unknown call fails the test. It returns the calls made, in order.
func fakeService(t *testing.T, answers map[string]rcCall) (rcRun, *[]string) {
	t.Helper()
	var calls []string
	return func(_ context.Context, args ...string) ([]byte, error) {
		key := strings.Join(args, " ")
		calls = append(calls, key)
		a, ok := answers[key]
		if !ok {
			t.Errorf("unexpected call: service %s", key)
			return nil, &exec.Error{Name: "service", Err: exec.ErrNotFound}
		}
		return []byte(a.out), a.err
	}, &calls
}

// rcFiles reads the script files from files; any other path does not exist.
func rcFiles(files map[string]string) func(string) ([]byte, error) {
	return func(name string) ([]byte, error) {
		if s, ok := files[name]; ok {
			return []byte(s), nil
		}
		return nil, &fs.PathError{Op: "open", Path: name, Err: fs.ErrNotExist}
	}
}

// rcHostAnswers is a host whose enabled scripts are those of a fresh 15.0 install plus nginx; netif
// has no status of its own.
func rcHostAnswers(t *testing.T) map[string]rcCall {
	t.Helper()
	exit1 := smartctlExit(t, 1) // any child's real ExitError; rc.subr's status exits 1 when not running
	return map[string]rcCall{
		"-e": {"/etc/rc.d/netif\n/etc/rc.d/devd\n/etc/rc.d/syslogd\n/etc/rc.d/newsyslog\n" +
			"/etc/rc.d/cron\n/usr/local/etc/rc.d/nginx\n", nil},
		"cron status":      {rcCronRunning, nil},
		"devd status":      {"devd is running as pid 420.\n", nil},
		"netif status":     {rcUnknownDirective, exit1},
		"newsyslog status": {rcNewsyslogStopped, exit1},
		"nginx status":     {rcNginxStopped, exit1},
		"syslogd status":   {"syslogd is running as pid 610.\n", nil},
	}
}

func TestRCServiceHealth(t *testing.T) {
	run, calls := fakeService(t, rcHostAnswers(t))
	files := rcFiles(map[string]string{
		"/etc/rc.d/newsyslog":       rcNewsyslogScript,
		"/usr/local/etc/rc.d/nginx": rcNginxScript,
	})
	got := dockerWire(t, rcServiceHealth(context.Background(), run, files))
	// netif does not answer status and stays out; newsyslog has nothing to stop and is no candidate.
	want := wantDockerWire(t, `{"failed": [], "enabled_inactive": ["nginx"],
		"all_services": [
			{"unit": "cron", "active_state": "active", "enabled_state": "enabled"},
			{"unit": "devd", "active_state": "active", "enabled_state": "enabled"},
			{"unit": "newsyslog", "active_state": "inactive", "enabled_state": "enabled"},
			{"unit": "nginx", "active_state": "inactive", "enabled_state": "enabled"},
			{"unit": "syslogd", "active_state": "active", "enabled_state": "enabled"}],
		"counts": {"active": 3, "total": 5}}`)
	if !reflect.DeepEqual(got, want) {
		t.Errorf("health = %v, want %v", got, want)
	}
	wantCalls := []string{"-e", "cron status", "devd status", "netif status", "newsyslog status",
		"nginx status", "syslogd status"}
	if !reflect.DeepEqual(*calls, wantCalls) {
		t.Errorf("calls = %q, want %q", *calls, wantCalls)
	}
}

func TestRCServiceHealthUnreadableScript(t *testing.T) {
	// A file that cannot be read proves nothing: the inactive service stays a candidate.
	run, _ := fakeService(t, rcHostAnswers(t))
	got := rcServiceHealth(context.Background(), run, rcFiles(nil))
	if want := []string{"newsyslog", "nginx"}; !reflect.DeepEqual(got["enabled_inactive"], want) {
		t.Errorf("enabled_inactive = %v, want %v", got["enabled_inactive"], want)
	}
}

func TestRCServiceHealthListFails(t *testing.T) {
	// Without `service -e` nothing is known: no inventory, no counts (they would claim 0 of 0), and the
	// error, so the server does not read the empty block as all OK.
	for name, tc := range map[string]struct {
		err  error
		want string
	}{
		"exit status": {smartctlExit(t, 1), "service -e failed: exit status 1"},
		"timed out":   {context.DeadlineExceeded, "service -e failed: timed out after 15s"},
		"not started": {&exec.Error{Name: "/usr/sbin/service", Err: exec.ErrNotFound},
			"service -e failed: service did not start"},
	} {
		t.Run(name, func(t *testing.T) {
			run, calls := fakeService(t, map[string]rcCall{"-e": {"/etc/rc.d/cron\n", tc.err}})
			got := dockerWire(t, rcServiceHealth(context.Background(), run, rcFiles(nil)))
			want := wantDockerWire(t, `{"failed": [], "enabled_inactive": [], "all_services": [],
				"error": "`+tc.want+`"}`)
			if !reflect.DeepEqual(got, want) {
				t.Errorf("health = %v, want %v", got, want)
			}
			if !reflect.DeepEqual(*calls, []string{"-e"}) {
				t.Errorf("calls = %q, want -e only", *calls)
			}
		})
	}
}

func TestRCServiceHealthStatusDoesNotAnswer(t *testing.T) {
	// A status call that hangs, is canceled or does not start ends the round: each such call waits
	// pluginTimeout. What was read stays, the error names the script, and the counts are left out.
	for name, tc := range map[string]struct {
		err  error
		want string
	}{
		"timed out": {context.DeadlineExceeded, "service devd status failed: timed out after 15s"},
		"canceled":  {context.Canceled, "service devd status failed: canceled before it ended"},
		"not started": {&exec.Error{Name: "/usr/sbin/service", Err: exec.ErrNotFound},
			"service devd status failed: service did not start"},
	} {
		t.Run(name, func(t *testing.T) {
			answers := rcHostAnswers(t)
			answers["devd status"] = rcCall{"", tc.err}
			run, calls := fakeService(t, answers)
			got := dockerWire(t, rcServiceHealth(context.Background(), run, rcFiles(nil)))
			want := wantDockerWire(t, `{"failed": [], "enabled_inactive": [],
				"all_services": [{"unit": "cron", "active_state": "active", "enabled_state": "enabled"}],
				"error": "`+tc.want+`"}`)
			if !reflect.DeepEqual(got, want) {
				t.Errorf("health = %v, want %v", got, want)
			}
			if want := []string{"-e", "cron status", "devd status"}; !reflect.DeepEqual(*calls, want) {
				t.Errorf("calls = %q, want %q", *calls, want)
			}
		})
	}
}

func TestRCWatchedServices(t *testing.T) {
	exit1 := smartctlExit(t, 1)
	run, calls := fakeService(t, map[string]rcCall{
		"cron status":   {rcCronRunning, nil},
		"sshd status":   {rcSshdTwoPids, nil},
		"nginx status":  {rcNginxStopped, exit1},
		"netif status":  {rcUnknownDirective, exit1},
		"nosuch status": {rcNoSuchScript, exit1},
		"pf status":     {rcPfStatus, nil},
	})
	names := []string{"cron", "sshd", "nginx", "netif", "nosuch", "pf", "../cron", "-e", "cron status"}
	got := dockerWire(t, map[string]any{"watched": rcWatchedServices(context.Background(), run, names)})
	want := wantDockerWire(t, `{"watched": [
		{"name": "cron", "running": true, "pid": "812"},
		{"name": "sshd", "running": true, "pid": "905"},
		{"name": "nginx", "running": false, "pid": null},
		{"name": "netif", "running": false, "pid": null},
		{"name": "nosuch", "running": false, "pid": null},
		{"name": "pf", "running": false, "pid": null},
		{"name": "../cron", "running": false, "pid": null},
		{"name": "-e", "running": false, "pid": null},
		{"name": "cron status", "running": false, "pid": null}]}`)
	if !reflect.DeepEqual(got, want) {
		t.Errorf("watched = %v, want %v", got, want)
	}
	// The names service(8) would not take never reach it.
	for _, c := range *calls {
		if name, _, _ := strings.Cut(c, " status"); !slices.Contains(names[:6], name) {
			t.Errorf("service called for %q", c)
		}
	}
	if len(*calls) != 6 {
		t.Errorf("calls = %q, want the six valid names", *calls)
	}
}

func TestRCWatchedServicesStopsAfterAHang(t *testing.T) {
	// After a call that did not answer no name is asked further; all of them are not running.
	run, calls := fakeService(t, map[string]rcCall{
		"cron status": {"", context.DeadlineExceeded},
	})
	got := dockerWire(t, map[string]any{
		"watched": rcWatchedServices(context.Background(), run, []string{"cron", "sshd", "nginx"}),
	})
	want := wantDockerWire(t, `{"watched": [
		{"name": "cron", "running": false, "pid": null},
		{"name": "sshd", "running": false, "pid": null},
		{"name": "nginx", "running": false, "pid": null}]}`)
	if !reflect.DeepEqual(got, want) {
		t.Errorf("watched = %v, want %v", got, want)
	}
	if !reflect.DeepEqual(*calls, []string{"cron status"}) {
		t.Errorf("calls = %q, want cron only", *calls)
	}
}
