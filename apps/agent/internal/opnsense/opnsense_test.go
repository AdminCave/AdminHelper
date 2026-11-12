// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package opnsense

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"reflect"
	"strings"
	"testing"
	"time"
	"unicode/utf8"

	"adminhelper-agent/internal/allowlist"
)

// The fixtures under testdata are rebuilt from the OPNsense core sources (configd actions,
// pluginctl, gateway_status.php, product.php, check.sh, carp_global_status.php,
// legacy_interfaces_details); a live box checks them in the box run.

type call struct {
	args    string
	timeout time.Duration
}

// fakeRunner answers each configctl call from outs, keyed by its space-joined arguments.
type fakeRunner struct {
	t     *testing.T
	outs  map[string][]byte
	errs  map[string]error
	calls []call
}

func (f *fakeRunner) run(_ context.Context, timeout time.Duration, name string, args ...string) ([]byte, error) {
	f.t.Helper()
	if name != Configctl {
		f.t.Fatalf("ran %q, want %q", name, Configctl)
	}
	key := strings.Join(args, " ")
	f.calls = append(f.calls, call{args: key, timeout: timeout})
	if err, ok := f.errs[key]; ok {
		return nil, err
	}
	out, ok := f.outs[key]
	if !ok {
		f.t.Fatalf("unexpected configctl call %q", key)
	}
	return out, nil
}

func fixture(t *testing.T, name string) []byte {
	t.Helper()
	data, err := os.ReadFile("testdata/" + name)
	if err != nil {
		t.Fatal(err)
	}
	return data
}

var fixedNow = time.Date(2026, 11, 9, 10, 0, 0, 0, time.UTC)

func reader(f *fakeRunner) Reader {
	return Reader{
		Run:     f.run,
		ModTime: func(string) (time.Time, error) { return time.Time{}, os.ErrNotExist },
		Now:     func() time.Time { return fixedNow },
	}
}

func read(t *testing.T, view string, outs map[string][]byte) (map[string]any, error) {
	t.Helper()
	f := &fakeRunner{t: t, outs: outs}
	return reader(f).Read(context.Background(), view)
}

func mustRead(t *testing.T, view string, outs map[string][]byte) map[string]any {
	t.Helper()
	fields, err := read(t, view, outs)
	if err != nil {
		t.Fatalf("Read(%s): %v", view, err)
	}
	return fields
}

func assertFields(t *testing.T, got, want map[string]any) {
	t.Helper()
	if !reflect.DeepEqual(got, want) {
		t.Errorf("fields\n got %#v\nwant %#v", got, want)
	}
}

func TestViewsIsTheAllowlist(t *testing.T) {
	want := []string{"carp", "firmware", "gateways", "services", "states"}
	if got := Views(); !reflect.DeepEqual(got, want) {
		t.Fatalf("Views() = %v, want %v", got, want)
	}
}

// The agent starts the calls through allowlist.Run, which refuses one off its list at runtime only.
func TestEveryCallOfTheViewsIsOnTheCommandAllowlist(t *testing.T) {
	for name, v := range views {
		for _, call := range v.calls {
			if !allowlist.Allowed(Configctl, call) {
				t.Errorf("view %s: configctl %q is not on the command allowlist", name, call)
			}
		}
	}
}

func TestReadRunsTheViewsConfigctlCalls(t *testing.T) {
	cases := map[string][]string{
		"services": {"service list"},
		"gateways": {"interface gateways status"},
		"firmware": {"firmware product"},
		"states":   {"filter diag state_size"},
		"carp":     {"interface show carp", "interface list ifconfig"},
	}
	outs := map[string][]byte{
		"service list":              fixture(t, "services.json"),
		"interface gateways status": fixture(t, "gateways.json"),
		"firmware product":          fixture(t, "firmware.json"),
		"filter diag state_size":    fixture(t, "states.txt"),
		"interface show carp":       fixture(t, "carp_global.json"),
		"interface list ifconfig":   fixture(t, "carp_ifconfig.json"),
	}
	for view, want := range cases {
		t.Run(view, func(t *testing.T) {
			f := &fakeRunner{t: t, outs: outs}
			if _, err := reader(f).Read(context.Background(), view); err != nil {
				t.Fatal(err)
			}
			var got []string
			for _, c := range f.calls {
				got = append(got, c.args)
				// configctl's own socket timeout is 120 s; a cap must sit below it.
				if c.timeout <= 0 || c.timeout >= 120*time.Second {
					t.Errorf("%q: timeout %v", c.args, c.timeout)
				}
			}
			if !reflect.DeepEqual(got, want) {
				t.Errorf("calls %v, want %v", got, want)
			}
		})
	}
}

func TestReadRejectsAnUnknownViewWithoutRunning(t *testing.T) {
	for _, view := range []string{"", "Services", "system", "services;reboot", "../services"} {
		f := &fakeRunner{t: t}
		_, err := reader(f).Read(context.Background(), view)
		if !errors.Is(err, ErrUnknownView) {
			t.Errorf("Read(%q) = %v, want ErrUnknownView", view, err)
		}
		if len(f.calls) != 0 {
			t.Errorf("Read(%q) ran %v", view, f.calls)
		}
	}
}

func TestReadStopsOnACanceledContext(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	f := &fakeRunner{t: t}
	_, err := reader(f).Read(ctx, "services")
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("err = %v, want context.Canceled", err)
	}
	if len(f.calls) != 0 {
		t.Fatalf("ran %v after cancel", f.calls)
	}
}

// The context is canceled once the first of carp's two calls has run.
func TestReadStopsBetweenCallsWhenCanceled(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	f := &fakeRunner{t: t, outs: map[string][]byte{"interface show carp": fixture(t, "carp_global.json")}}
	r := reader(f)
	inner := r.Run
	r.Run = func(ctx context.Context, timeout time.Duration, name string, args ...string) ([]byte, error) {
		out, err := inner(ctx, timeout, name, args...)
		cancel()
		return out, err
	}
	_, err := r.Read(ctx, "carp")
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("err = %v, want context.Canceled", err)
	}
	if len(f.calls) != 1 {
		t.Fatalf("calls %v, want only the first", f.calls)
	}
}

func TestReadMapsRunnerErrorsToTheirKind(t *testing.T) {
	const leak = "LEAKED-OUTPUT /usr/local/sbin/configctl"
	cases := []struct {
		name   string
		err    error
		want   string
		target error
	}{
		{"deadline", fmt.Errorf("execx: %w", context.DeadlineExceeded), "opnsense: services: configctl: context deadline exceeded", context.DeadlineExceeded},
		{"canceled", context.Canceled, "opnsense: services: configctl: context canceled", context.Canceled},
		{"exit", fmt.Errorf("%s: %w", leak, &exec.ExitError{}), "opnsense: services: configctl exited with -1", nil},
		{"not found", &exec.Error{Name: Configctl, Err: exec.ErrNotFound}, "opnsense: services: configctl not found", nil},
		{"missing", fmt.Errorf("%s: %w", leak, os.ErrNotExist), "opnsense: services: configctl not found", nil},
		{"other", errors.New(leak), "opnsense: services: configctl failed", nil},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			f := &fakeRunner{t: t, errs: map[string]error{"service list": c.err}}
			_, err := reader(f).Read(context.Background(), "services")
			if err == nil || err.Error() != c.want {
				t.Fatalf("err = %v, want %q", err, c.want)
			}
			if c.target != nil && !errors.Is(err, c.target) {
				t.Errorf("errors.Is(%v, %v) = false", err, c.target)
			}
			if strings.Contains(err.Error(), "LEAKED") || strings.Contains(err.Error(), "/usr/local") {
				t.Errorf("error carries output or path: %v", err)
			}
		})
	}
}

func TestReadDoesNotParseAfterAFailedSecondCall(t *testing.T) {
	f := &fakeRunner{
		t:    t,
		outs: map[string][]byte{"interface show carp": fixture(t, "carp_global.json")},
		errs: map[string]error{"interface list ifconfig": errors.New("boom")},
	}
	_, err := reader(f).Read(context.Background(), "carp")
	if err == nil || err.Error() != "opnsense: carp: configctl failed" {
		t.Fatalf("err = %v", err)
	}
}

// configd answers with text and exit 0 for its own failures; every parser must refuse it, and
// none may echo it.
func TestParsersRejectConfigdErrorText(t *testing.T) {
	bad := []byte("Action not found\n")
	cases := map[string]map[string][]byte{
		"services": {"service list": bad},
		"gateways": {"interface gateways status": bad},
		"firmware": {"firmware product": bad},
		"states":   {"filter diag state_size": bad},
		"carp":     {"interface show carp": bad, "interface list ifconfig": fixture(t, "carp_ifconfig.json")},
		"carp2":    {"interface show carp": fixture(t, "carp_global.json"), "interface list ifconfig": bad},
	}
	for name, outs := range cases {
		view := strings.TrimSuffix(name, "2")
		t.Run(name, func(t *testing.T) {
			_, err := read(t, view, outs)
			want := "opnsense: " + view + ": unexpected output form"
			if err == nil || err.Error() != want {
				t.Fatalf("err = %v, want %q", err, want)
			}
		})
	}
}

func TestParsersRejectNullAndEmptyOutput(t *testing.T) {
	for _, out := range []string{"", "null", "  \n", "{}", "[]"} {
		for view, key := range map[string]string{
			"services": "service list",
			"firmware": "firmware product",
			"states":   "filter diag state_size",
		} {
			// [] is a valid, empty service list.
			if view == "services" && out == "[]" {
				continue
			}
			if _, err := read(t, view, map[string][]byte{key: []byte(out)}); err == nil {
				t.Errorf("%s accepted %q", view, out)
			}
		}
		if out == "[]" || out == "{}" {
			continue
		}
		if _, err := read(t, "gateways", map[string][]byte{"interface gateways status": []byte(out)}); err == nil {
			t.Errorf("gateways accepted %q", out)
		}
	}
}

func TestServices(t *testing.T) {
	fields := mustRead(t, "services", map[string][]byte{"service list": fixture(t, "services.json")})
	assertFields(t, fields, map[string]any{
		"total":         4,
		"running":       2,
		"stopped":       2,
		"stopped_names": "dhcpd,openvpn[1]",
	})
}

func TestServicesEmpty(t *testing.T) {
	fields := mustRead(t, "services", map[string][]byte{"service list": []byte("[]\n")})
	assertFields(t, fields, map[string]any{"total": 0, "running": 0, "stopped": 0, "stopped_names": ""})
}

func TestServicesRejectsAnEntryWithoutNameOrStatus(t *testing.T) {
	for _, out := range []string{
		`[{"name":"configd"}]`,
		`[{"status":"x is running."}]`,
		`[{"name":"","status":"x is running."}]`,
		`[{"name":"configd","status":42}]`,
		`["configd"]`,
	} {
		if _, err := read(t, "services", map[string][]byte{"service list": []byte(out)}); err == nil {
			t.Errorf("accepted %s", out)
		}
	}
}

func TestServicesNamesAreCutTo256Runes(t *testing.T) {
	var b strings.Builder
	b.WriteString("[")
	for i := range 60 {
		if i > 0 {
			b.WriteString(",")
		}
		fmt.Fprintf(&b, `{"name":"dienst-%02d-ä","status":"dienst-%02d is not running."}`, i, i)
	}
	b.WriteString("]")
	fields := mustRead(t, "services", map[string][]byte{"service list": []byte(b.String())})
	names, _ := fields["stopped_names"].(string)
	if n := utf8.RuneCountInString(names); n != maxTextRunes {
		t.Fatalf("stopped_names has %d runes, want %d", n, maxTextRunes)
	}
	if !strings.HasPrefix(names, "dienst-00-ä,dienst-01-ä") || !strings.HasSuffix(names, "…") {
		t.Fatalf("stopped_names = %q", names)
	}
	if fields["stopped"] != 60 {
		t.Fatalf("stopped = %v", fields["stopped"])
	}
}

func TestGateways(t *testing.T) {
	fields := mustRead(t, "gateways", map[string][]byte{"interface gateways status": fixture(t, "gateways.json")})
	assertFields(t, fields, map[string]any{
		"total":          4,
		"down":           1,
		"degraded":       1,
		"forced_down":    1,
		"down_names":     "WAN2_GW",
		"degraded_names": "LTE_GW",
		"max_loss_pct":   100.0,
		"max_delay_ms":   250.4,
	})
}

func TestGatewaysEmptyHasNoMeasurement(t *testing.T) {
	fields := mustRead(t, "gateways", map[string][]byte{"interface gateways status": []byte("[]\n")})
	assertFields(t, fields, map[string]any{
		"total": 0, "down": 0, "degraded": 0, "forced_down": 0, "down_names": "", "degraded_names": "",
	})
}

func TestGatewaysRejectsUnknownForms(t *testing.T) {
	for _, out := range []string{
		`{"GW":{"status":"pending","loss":"~","delay":"~"}}`,
		`{"GW":{"status":"none","loss":"1.0","delay":"~"}}`,
		`{"GW":{"status":"none","loss":"~","delay":"-1.0 ms"}}`,
		`{"GW":{"status":"none","loss":"~"}}`,
		`{"GW":"none"}`,
		`[{"status":"none","loss":"~","delay":"~"}]`,
	} {
		if _, err := read(t, "gateways", map[string][]byte{"interface gateways status": []byte(out)}); err == nil {
			t.Errorf("accepted %s", out)
		}
	}
}

func TestFirmware(t *testing.T) {
	f := &fakeRunner{t: t, outs: map[string][]byte{"firmware product": fixture(t, "firmware.json")}}
	r := reader(f)
	var statted string
	r.ModTime = func(path string) (time.Time, error) {
		statted = path
		return fixedNow.Add(-90 * time.Second), nil
	}
	fields, err := r.Read(context.Background(), "firmware")
	if err != nil {
		t.Fatal(err)
	}
	if statted != "/tmp/pkg_upgrade.json" {
		t.Errorf("statted %q", statted)
	}
	assertFields(t, fields, map[string]any{
		"version":          "26.7.1",
		"latest":           "26.7.2",
		"checked":          true,
		"connection":       "ok",
		"repository":       "ok",
		"updates":          3,
		"update_available": true,
		"update_reboot":    true,
		"check_age_s":      int64(90),
	})
	if s := fmt.Sprint(fields); strings.Contains(s, "MARKER") {
		t.Errorf("mirror or license left the parser: %s", s)
	}
}

func TestFirmwareUnchecked(t *testing.T) {
	f := &fakeRunner{t: t, outs: map[string][]byte{"firmware product": fixture(t, "firmware_unchecked.json")}}
	r := reader(f)
	r.ModTime = func(string) (time.Time, error) {
		t.Fatal("stat without a check")
		return time.Time{}, nil
	}
	fields, err := r.Read(context.Background(), "firmware")
	if err != nil {
		t.Fatal(err)
	}
	assertFields(t, fields, map[string]any{"version": "26.7.1", "checked": false})
}

func TestFirmwareRebootOnlyWithAnUpdate(t *testing.T) {
	out := `{"product_version":"26.7.1","product_latest":"26.7.1","product_check":{"connection":"ok",` +
		`"repository":"ok","needs_reboot":"1","new_packages":[],"upgrade_packages":[],` +
		`"reinstall_packages":[],"downgrade_packages":[],"remove_packages":[],` +
		`"upgrade_major_version":"27.1"}}`
	fields := mustRead(t, "firmware", map[string][]byte{"firmware product": []byte(out)})
	if fields["update_available"] != false || fields["update_reboot"] != false || fields["updates"] != 0 {
		t.Errorf("fields %v", fields)
	}
	if fields["major_upgrade"] != "27.1" {
		t.Errorf("major_upgrade = %v", fields["major_upgrade"])
	}
	if _, ok := fields["check_age_s"]; ok {
		t.Errorf("check_age_s without a file: %v", fields["check_age_s"])
	}
}

func TestFirmwareCheckAgeNeverNegative(t *testing.T) {
	f := &fakeRunner{t: t, outs: map[string][]byte{"firmware product": fixture(t, "firmware.json")}}
	r := reader(f)
	r.ModTime = func(string) (time.Time, error) { return fixedNow.Add(time.Hour), nil }
	fields, err := r.Read(context.Background(), "firmware")
	if err != nil {
		t.Fatal(err)
	}
	if fields["check_age_s"] != int64(0) {
		t.Errorf("check_age_s = %v", fields["check_age_s"])
	}
}

func TestFirmwareRejectsUnknownForms(t *testing.T) {
	for _, out := range []string{
		`[]`,
		`{"product_latest":"26.7.2"}`,
		`{"product_version":"","product_latest":""}`,
		`{"product_version":"26.7.1"}`,
		`{"product_version":"26.7.1","product_latest":"","product_check":{"repository":"ok"}}`,
		`{"product_version":"26.7.1","product_latest":"","product_check":"ok"}`,
	} {
		if _, err := read(t, "firmware", map[string][]byte{"firmware product": []byte(out)}); err == nil {
			t.Errorf("accepted %s", out)
		}
	}
}

func TestStates(t *testing.T) {
	fields := mustRead(t, "states", map[string][]byte{"filter diag state_size": fixture(t, "states.txt")})
	assertFields(t, fields, map[string]any{"current": 1234, "limit": 813000, "used_pct": 0.2})
}

func TestStatesIdleAndFull(t *testing.T) {
	fields := mustRead(t, "states", map[string][]byte{"filter diag state_size": []byte("current 0\nlimit 100\n")})
	assertFields(t, fields, map[string]any{"current": 0, "limit": 100, "used_pct": 0.0})
	fields = mustRead(t, "states", map[string][]byte{"filter diag state_size": []byte("limit 1000\ncurrent 999\ncurrent 5\n")})
	assertFields(t, fields, map[string]any{"current": 999, "limit": 1000, "used_pct": 99.9})
}

func TestStatesRejectsUnknownForms(t *testing.T) {
	for _, out := range []string{
		"current 10\nlimit 0\n",
		"current 10\n",
		"limit 100\n",
		"current ten\nlimit 100\n",
		"current -1\nlimit 100\n",
		"current 10 entries\nlimit 100\n",
		"current 10\nlimit 100\nsearches 5\n",
	} {
		if _, err := read(t, "states", map[string][]byte{"filter diag state_size": []byte(out)}); err == nil {
			t.Errorf("accepted %q", out)
		}
	}
}

func carpOuts(t *testing.T, global, ifconfig []byte) map[string][]byte {
	t.Helper()
	return map[string][]byte{"interface show carp": global, "interface list ifconfig": ifconfig}
}

func TestCarp(t *testing.T) {
	fields := mustRead(t, "carp", carpOuts(t, fixture(t, "carp_global.json"), fixture(t, "carp_ifconfig.json")))
	assertFields(t, fields, map[string]any{
		"vips": 3, "master": 2, "backup": 1, "init": 0, "demotion": 0, "maintenance": false,
	})
}

func TestCarpWithoutVips(t *testing.T) {
	fields := mustRead(t, "carp", carpOuts(t, fixture(t, "carp_global.json"), fixture(t, "carp_ifconfig_novip.json")))
	assertFields(t, fields, map[string]any{
		"vips": 0, "master": 0, "backup": 0, "init": 0, "demotion": 0, "maintenance": false,
	})
}

func TestCarpDemotedInMaintenance(t *testing.T) {
	global := []byte(`{"demotion":"240","allow":"1","maintenancemode":true,"status_msg":""}`)
	ifconfig := []byte(`{"vtnet0":{"carp":[{"status":"INIT"},{"status":"BACKUP"}]}}`)
	fields := mustRead(t, "carp", carpOuts(t, global, ifconfig))
	assertFields(t, fields, map[string]any{
		"vips": 2, "master": 0, "backup": 1, "init": 1, "demotion": 240, "maintenance": true,
	})
}

// The demotion sysctl is signed; OPNsense resets it by writing a negative difference.
func TestCarpAcceptsASignedOrNumericDemotion(t *testing.T) {
	ifconfig := fixture(t, "carp_ifconfig_novip.json")
	for raw, want := range map[string]int{`"-240"`: -240, `-3`: -3, `17`: 17} {
		global := []byte(`{"demotion":` + raw + `,"maintenancemode":false}`)
		fields := mustRead(t, "carp", carpOuts(t, global, ifconfig))
		if fields["demotion"] != want {
			t.Errorf("demotion %s = %v, want %d", raw, fields["demotion"], want)
		}
	}
}

func TestCarpRejectsUnknownForms(t *testing.T) {
	ifconfig := fixture(t, "carp_ifconfig.json")
	global := fixture(t, "carp_global.json")
	for _, c := range []struct{ global, ifconfig string }{
		{`{"demotion":"x","maintenancemode":false}`, string(ifconfig)},
		{`{"demotion":"1.5","maintenancemode":false}`, string(ifconfig)},
		{`{"demotion":"0"}`, string(ifconfig)},
		{`{"demotion":"0","maintenancemode":"0"}`, string(ifconfig)},
		{string(global), `{"vtnet0":{"carp":{"1":{"status":"PRIMARY"}}}}`},
		{string(global), `{"vtnet0":{"carp":{"1":{"vhid":"1"}}}}`},
		{string(global), `{"vtnet0":{"carp":"MASTER"}}`},
	} {
		if _, err := read(t, "carp", carpOuts(t, []byte(c.global), []byte(c.ifconfig))); err == nil {
			t.Errorf("accepted %s / %s", c.global, c.ifconfig)
		}
	}
}

func TestTruthyFollowsPHPEmpty(t *testing.T) {
	for raw, want := range map[string]bool{
		``: false, `null`: false, `false`: false, `0`: false, `""`: false, `"0"`: false,
		`[]`: false, `{}`: false, `true`: true, `1`: true, `"1"`: true, `"yes"`: true,
	} {
		if got := truthy([]byte(raw)); got != want {
			t.Errorf("truthy(%s) = %v, want %v", raw, got, want)
		}
	}
}
