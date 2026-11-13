// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"fmt"
	"os/exec"
	"reflect"
	"strings"
	"testing"
	"time"
)

var netNow = time.Date(2026, 11, 13, 12, 0, 0, 0, time.UTC)

// ago is the unix time d before netNow, as wg prints it.
func ago(d time.Duration) string { return fmt.Sprint(netNow.Add(-d).Unix()) }

// noneOf fails the test if the values carry any of secrets.
func noneOf(t *testing.T, values map[string]any, secrets ...string) {
	t.Helper()
	text := fmt.Sprint(values)
	for _, s := range secrets {
		if strings.Contains(text, s) {
			t.Errorf("values %v carry %q", values, s)
		}
	}
}

func TestWgPeersCountsStaleKeepalivePeersOfTheUnitsInterface(t *testing.T) {
	stubNow(t, netNow)
	handshakes := "wg0\tKEYa=\t" + ago(100*time.Second) + "\n" +
		"wg0\tKEYb=\t" + ago(400*time.Second) + "\n" +
		"wg0\tKEYc=\t0\n" +
		"wg0\tKEYd=\t" + ago(5000*time.Second) + "\n" +
		"wg1\tKEYe=\t" + ago(2000*time.Second) + "\n"
	keepalive := "wg0\tKEYa=\t25\nwg0\tKEYb=\t25\nwg0\tKEYc=\t25\nwg0\tKEYd=\toff\nwg1\tKEYe=\t25\n"
	calls := stubTools(t, answer{out: handshakes}, answer{out: keepalive})
	values, err := wgPeers(context.Background(), Target{Kind: kindUnit, Name: "wg-quick@wg0.service"})
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]any{"interfaces": 1, "peers": 4, "keepalive_peers": 3, "stale_warn": 1, "stale_crit": 1,
		"max_handshake_age_s": 400}
	if !reflect.DeepEqual(values, want) {
		t.Errorf("values %v, want %v", values, want)
	}
	wantCalls := [][]string{{"wg", "show", "all", "latest-handshakes"}, {"wg", "show", "all", "persistent-keepalive"}}
	if !reflect.DeepEqual(*calls, wantCalls) {
		t.Errorf("calls %q, want %q", *calls, wantCalls)
	}
	noneOf(t, values, "KEY")
}

func TestWgPeersCountsEveryInterfaceOfAnotherUnit(t *testing.T) {
	stubNow(t, netNow)
	stubTools(t, answer{out: "wg0\tKEYa=\t" + ago(1000*time.Second) + "\nwg1\tKEYe=\t" + ago(10*time.Second) + "\n"},
		answer{out: "wg0\tKEYa=\t25\nwg1\tKEYe=\t25\n"})
	values, err := wgPeers(context.Background(), Target{Kind: kindUnit, Name: "systemd-networkd.service"})
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]any{"interfaces": 2, "peers": 2, "keepalive_peers": 2, "stale_warn": 0, "stale_crit": 1,
		"max_handshake_age_s": 1000}
	if !reflect.DeepEqual(values, want) {
		t.Errorf("values %v, want %v", values, want)
	}
}

func TestWgPeersWithoutKeepalivePeersHasNoAge(t *testing.T) {
	stubNow(t, netNow)
	stubTools(t, answer{out: "wg0\tKEYa=\t0\n"}, answer{out: "wg0\tKEYa=\toff\n"})
	values, err := wgPeers(context.Background(), Target{Kind: kindUnit, Name: "wg-quick@wg0.service"})
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]any{"interfaces": 1, "peers": 1, "keepalive_peers": 0, "stale_warn": 0, "stale_crit": 0}
	if !reflect.DeepEqual(values, want) {
		t.Errorf("values %v, want %v", values, want)
	}
}

func TestWgPeersFailsWhatItCannotRead(t *testing.T) {
	stubNow(t, netNow)
	unit := Target{Kind: kindUnit, Name: "wg-quick@wg0.service"}
	cases := map[string][]answer{
		"interface down":    {{out: "wg1\tKEYe=\t0\n"}, {out: "wg1\tKEYe=\toff\n"}},
		"a line too short":  {{out: "wg0\tKEYa=\n"}},
		"a time not a time": {{out: "wg0\tKEYa=\tsoon\n"}, {out: "wg0\tKEYa=\t25\n"}},
		"wg fails":          {{err: &exec.ExitError{}}},
	}
	for name, answers := range cases {
		t.Run(name, func(t *testing.T) {
			stubTools(t, answers...)
			if _, err := wgPeers(context.Background(), unit); err == nil {
				t.Error("no error")
			}
		})
	}
	stubTools(t, answer{err: notInstalled("wg")})
	if _, err := wgPeers(context.Background(), unit); !errors.Is(err, ErrUnsupported) {
		t.Errorf("error %v, want ErrUnsupported", err)
	}
}

const f2bStatus = "Status\n|- Number of jail:\t3\n`- Jail list:\tsshd, recidive, postfix\n"

// f2bJail is a status of fail2ban-client status <jail>, with a file list of files or, for a journal
// backend (journal true), journal matches.
func f2bJail(name, files string, journal bool, banned int, ips string) string {
	source := "   `- File list:\t" + files + "\n"
	if journal {
		source = "   `- Journal matches:\t_SYSTEMD_UNIT=postfix.service\n"
	}
	return "Status for the jail: " + name + "\n|- Filter\n|  |- Currently failed:\t1\n|  |- Total failed:\t9\n" +
		source + "`- Actions\n   |- Currently banned:\t" + fmt.Sprint(banned) + "\n   |- Total banned:\t40\n" +
		"   `- Banned IP list:\t" + ips + "\n"
}

func TestFail2banCountsBansAndJailsWithoutFiles(t *testing.T) {
	calls := stubTools(t, answer{out: "Server replied: pong\n"}, answer{out: f2bStatus},
		answer{out: f2bJail("sshd", "/var/log/auth.log", false, 3, "192.0.2.7 198.51.100.9 2001:db8::1")},
		answer{out: f2bJail("recidive", "", false, 12, "203.0.113.5")},
		answer{out: f2bJail("postfix", "", true, 0, "")})
	values, err := fail2ban(context.Background(), Target{Kind: kindUnit, Name: "fail2ban.service"})
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]any{"responding": true, "jails": 3, "banned_total": 15, "max_banned": 12,
		"jails_without_files": 1}
	if !reflect.DeepEqual(values, want) {
		t.Errorf("values %v, want %v", values, want)
	}
	wantCalls := [][]string{{"fail2ban-client", "ping"}, {"fail2ban-client", "status"},
		{"fail2ban-client", "status", "sshd"}, {"fail2ban-client", "status", "recidive"},
		{"fail2ban-client", "status", "postfix"}}
	if !reflect.DeepEqual(*calls, wantCalls) {
		t.Errorf("calls %q, want %q", *calls, wantCalls)
	}
	noneOf(t, values, "192.0.2.7", "203.0.113.5", "2001:db8", "auth.log")
}

func TestFail2banReadsASpaceSeparatedJailList(t *testing.T) {
	stubTools(t, answer{}, answer{out: "Status\n|- Number of jail:\t2\n`- Jail list:\tsshd recidive\n"},
		answer{out: f2bJail("sshd", "/var/log/auth.log", false, 1, "192.0.2.7")},
		answer{out: f2bJail("recidive", "/var/log/fail2ban.log", false, 2, "192.0.2.8")})
	values, err := fail2ban(context.Background(), Target{Kind: kindUnit, Name: "fail2ban.service"})
	if err != nil {
		t.Fatal(err)
	}
	if values["jails"] != 2 || values["banned_total"] != 3 {
		t.Errorf("values %v, want 2 jails, 3 banned", values)
	}
}

func TestFail2banThatDoesNotAnswerIsAValue(t *testing.T) {
	for name, err := range map[string]error{"refused": &exec.ExitError{}, "hangs": context.DeadlineExceeded} {
		t.Run(name, func(t *testing.T) {
			calls := stubTools(t, answer{err: err})
			values, err := fail2ban(context.Background(), Target{Kind: kindUnit, Name: "fail2ban.service"})
			if err != nil {
				t.Fatal(err)
			}
			if !reflect.DeepEqual(values, map[string]any{"responding": false}) || len(*calls) != 1 {
				t.Errorf("values %v after %d calls, want only responding false", values, len(*calls))
			}
		})
	}
}

func TestFail2banFailsWhatItCannotRead(t *testing.T) {
	many := "Status\n`- Jail list:\t" + strings.TrimSuffix(strings.Repeat("j, ", maxJails+1), ", ") + "\n"
	cases := map[string][]answer{
		"no jail list":         {{}, {out: "Status\n|- Number of jail:\t0\n"}},
		"too many jails":       {{}, {out: many}},
		"no banned count":      {{}, {out: f2bStatus}, {out: "Status for the jail: sshd\n"}},
		"a count not a number": {{}, {out: f2bStatus}, {out: "   |- Currently banned:\tmany\n"}},
		"status fails":         {{}, {err: &exec.ExitError{}}},
	}
	for name, answers := range cases {
		t.Run(name, func(t *testing.T) {
			stubTools(t, answers...)
			if _, err := fail2ban(context.Background(), Target{Kind: kindUnit, Name: "fail2ban.service"}); err == nil {
				t.Error("no error")
			}
		})
	}
	stubTools(t, answer{err: notInstalled("fail2ban-client")})
	if _, err := fail2ban(context.Background(), Target{}); !errors.Is(err, ErrUnsupported) {
		t.Errorf("error %v, want ErrUnsupported", err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	stubTools(t, answer{err: context.Canceled})
	if _, err := fail2ban(ctx, Target{}); !errors.Is(err, context.Canceled) {
		t.Errorf("error %v, want the probe's own end, not responding false", err)
	}
}

func TestCrowdsecBouncersCountsStaleOnesNotRevoked(t *testing.T) {
	stubNow(t, netNow)
	at := func(d time.Duration) string { return netNow.Add(-d).Format(time.RFC3339Nano) }
	list := `[{"name":"fw-bouncer","ip_address":"192.0.2.4","revoked":true,"last_pull":null},
{"name":"nginx-bouncer","ip_address":"192.0.2.5","revoked":false,"last_pull":"` + at(time.Minute) + `","version":"v1.0"},
{"name":"old-bouncer","ip_address":"192.0.2.6","revoked":false,"last_pull":"` + at(20*time.Minute) + `"},
{"name":"new-bouncer","ip_address":"","revoked":false,"last_pull":null}]`
	calls := stubTools(t, answer{out: list})
	values, err := crowdsecBouncers(context.Background(), Target{Kind: kindUnit, Name: "crowdsec.service"})
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]any{"bouncers": 3, "stale_bouncers": 2, "max_pull_age_s": 1200}
	if !reflect.DeepEqual(values, want) {
		t.Errorf("values %v, want %v", values, want)
	}
	if want := [][]string{{"cscli", "bouncers", "list", "-o", "json"}}; !reflect.DeepEqual(*calls, want) {
		t.Errorf("calls %q, want %q", *calls, want)
	}
	noneOf(t, values, "nginx-", "old-", "new-", "v1.0", "192.0.2")
}

func TestCrowdsecBouncersOfNone(t *testing.T) {
	for _, out := range []string{"null\n", "[]\n"} {
		stubTools(t, answer{out: out})
		values, err := crowdsecBouncers(context.Background(), Target{})
		if err != nil {
			t.Fatal(err)
		}
		if want := map[string]any{"bouncers": 0, "stale_bouncers": 0}; !reflect.DeepEqual(values, want) {
			t.Errorf("%q: values %v, want %v", out, values, want)
		}
	}
}

func TestCrowdsecBouncersFailsWhatItCannotRead(t *testing.T) {
	for name, a := range map[string]answer{
		"not json":          {out: "Name  IP Address\n"},
		"no array":          {out: `{"name":"x"}`},
		"a time not RFC":    {out: `[{"last_pull":"yesterday"}]`},
		"no access to LAPI": {err: &exec.ExitError{}},
	} {
		t.Run(name, func(t *testing.T) {
			stubTools(t, a)
			if _, err := crowdsecBouncers(context.Background(), Target{}); err == nil {
				t.Error("no error")
			}
		})
	}
	stubTools(t, answer{err: notInstalled("cscli")})
	if _, err := crowdsecBouncers(context.Background(), Target{}); !errors.Is(err, ErrUnsupported) {
		t.Errorf("error %v, want ErrUnsupported", err)
	}
}

func TestTailscaleStatusReadsStateHealthAndKeyExpiry(t *testing.T) {
	stubNow(t, netNow)
	expiry := func(d time.Duration) string { return netNow.Add(d).Format(time.RFC3339) }
	cases := map[string]struct {
		out  string
		want map[string]any
	}{
		"running, key in 20.5 days": {
			`{"BackendState":"Running","Health":["a","b"],"Self":{"HostName":"box","TailscaleIPs":["100.64.0.1"],"KeyExpiry":"` +
				expiry(20*24*time.Hour+12*time.Hour) + `"}}`,
			map[string]any{"backend_running": true, "health_warnings": 2, "key_expiry_days": 20}},
		"stopped, key expired half a day ago": {
			`{"BackendState":"Stopped","Health":null,"Self":{"KeyExpiry":"` + expiry(-12*time.Hour) + `"}}`,
			map[string]any{"backend_running": false, "health_warnings": 0, "key_expiry_days": -1}},
		"expiry off": {
			`{"BackendState":"Running","Health":[],"Self":{"HostName":"box"}}`,
			map[string]any{"backend_running": true, "health_warnings": 0}},
		"needs login, no self": {
			`{"BackendState":"NeedsLogin","Self":null}`,
			map[string]any{"backend_running": false, "health_warnings": 0}},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			calls := stubTools(t, answer{out: c.out})
			values, err := tailscaleStatus(context.Background(), Target{Kind: kindUnit, Name: "tailscaled.service"})
			if err != nil {
				t.Fatal(err)
			}
			if !reflect.DeepEqual(values, c.want) {
				t.Errorf("values %v, want %v", values, c.want)
			}
			if want := [][]string{{"tailscale", "status", "--json", "--peers=false"}}; !reflect.DeepEqual(*calls, want) {
				t.Errorf("calls %q, want %q", *calls, want)
			}
			noneOf(t, values, "box", "100.64")
		})
	}
}

func TestTailscaleStatusFailsWhatItCannotRead(t *testing.T) {
	for name, a := range map[string]answer{
		"not json":         {out: "100.64.0.1 box linux -\n"},
		"no backend state": {out: `{"Health":[]}`},
		"daemon down":      {err: &exec.ExitError{}},
	} {
		t.Run(name, func(t *testing.T) {
			stubTools(t, a)
			if _, err := tailscaleStatus(context.Background(), Target{}); err == nil {
				t.Error("no error")
			}
		})
	}
	stubTools(t, answer{err: notInstalled("tailscale")})
	if _, err := tailscaleStatus(context.Background(), Target{}); !errors.Is(err, ErrUnsupported) {
		t.Errorf("error %v, want ErrUnsupported", err)
	}
}

func TestTheNetSecurityViewsAreViewsOfUnits(t *testing.T) {
	for _, view := range []string{"wg_peers", "fail2ban", "crowdsec_bouncers", "tailscale_status"} {
		if v, ok := appViews[view]; !ok || !unitView(v) {
			t.Errorf("view %s: %v, want a view of a unit", view, v)
		}
	}
}
