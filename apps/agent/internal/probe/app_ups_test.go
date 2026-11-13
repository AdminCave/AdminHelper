// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"os/exec"
	"reflect"
	"testing"
)

// staleExit is upsc's exit for a UPS upsd has no fresh data for (clients/upsc.c fatalx).
func staleExit(text string) error {
	return &exec.ExitError{Stderr: []byte("Error: " + text + "\n")}
}

func TestNutUPSCountsTheStatesOfEveryUPS(t *testing.T) {
	calls := stubTools(t,
		answer{out: "eaton\nrack-b\nold\nlost\n"},
		// On battery and low, with the serial and the model upsc prints as well.
		answer{out: "battery.charge: 18\nbattery.runtime: 240\ndevice.serial: SN12345\nups.status: OB DISCHRG LB\n"},
		// Online, charging, overloaded, with a battery to replace and an unknown token.
		answer{out: "battery.charge: 96.5\nbattery.runtime: 1800\nups.status: OL CHRG OVER RB ECO\n"},
		// A driver without runtime or charge, in forced shutdown.
		answer{out: "ups.status: OB LB FSD\n"},
		answer{err: staleExit("Data stale")},
	)
	got, err := nutUPS(context.Background(), Target{Kind: kindUnit, Name: "nut-server.service"})
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]any{
		"ups": 4, "on_battery": 2, "low_battery": 2, "fsd": 1, "overload": 1, "replace_battery": 1,
		"stale": 1, "min_runtime_s": 240, "min_charge_pct": 18.0,
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("nut %v, want %v", got, want)
	}
	wantCalls := [][]string{
		{"upsc", "-l", "localhost"}, {"upsc", "eaton@localhost"}, {"upsc", "rack-b@localhost"},
		{"upsc", "old@localhost"}, {"upsc", "lost@localhost"},
	}
	if !reflect.DeepEqual(*calls, wantCalls) {
		t.Errorf("calls %q, want %q", *calls, wantCalls)
	}
}

func TestNutUPSCountsADisconnectedDriverAsStale(t *testing.T) {
	stubTools(t, answer{out: "ups\n"}, answer{err: staleExit("Driver not connected")})
	got, err := nutUPS(context.Background(), Target{})
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]any{
		"ups": 1, "on_battery": 0, "low_battery": 0, "fsd": 0, "overload": 0, "replace_battery": 0, "stale": 1,
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("nut %v, want %v without runtime and charge", got, want)
	}
}

func TestNutUPSReportsZeroWithoutAUPS(t *testing.T) {
	stubTools(t, answer{out: ""})
	got, err := nutUPS(context.Background(), Target{})
	if err != nil {
		t.Fatal(err)
	}
	if got["ups"] != 0 || got["stale"] != 0 {
		t.Errorf("nut %v, want zero UPSes", got)
	}
}

func TestNutUPSFailsWhatItCannotRead(t *testing.T) {
	for name, answers := range map[string][]answer{
		"upsd down":         {{err: staleExit("Connection failure: Connection refused")}},
		"a UPS fails":       {{out: "ups\n"}, {err: staleExit("Unknown UPS")}},
		"a name with a @":   {{out: "ups@nas\n"}},
		"a name with a -":   {{out: "-x\n"}},
		"a runtime no num":  {{out: "ups\n"}, {out: "battery.runtime: soon\nups.status: OL\n"}},
		"a charge negative": {{out: "ups\n"}, {out: "battery.charge: -1\nups.status: OL\n"}},
	} {
		t.Run(name, func(t *testing.T) {
			stubTools(t, answers...)
			if _, err := nutUPS(context.Background(), Target{}); err == nil {
				t.Error("no error")
			}
		})
	}
	stubTools(t, answer{err: notInstalled("upsc")})
	if _, err := nutUPS(context.Background(), Target{}); !errors.Is(err, ErrUnsupported) {
		t.Errorf("error %v, want ErrUnsupported", err)
	}
}

// apcStatus is a report of apcaccess -u status in apcupsd's line form (src/lib/apcstatus.c), with the
// lines the view does not read.
const apcStatus = `APC      : 001,036,0868
DATE     : 2026-11-13 10:00:00 +0100
HOSTNAME : nas
UPSNAME  : rack
SERIALNO : AS1234567890
STATUS   : ONBATT LOWBATT
BCHARGE  : 42.0
TIMELEFT : 7.5
NUMXFERS : 3
END APC  : 2026-11-13 10:00:01 +0100
`

func TestApcupsdReadsStatusChargeRuntimeAndTransfers(t *testing.T) {
	calls := stubTools(t, answer{out: apcStatus})
	got, err := apcupsd(context.Background(), Target{Kind: kindUnit, Name: "apcupsd.service"})
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]any{
		"online": false, "on_battery": true, "low_battery": true, "commlost": false,
		"charge_pct": 42.0, "runtime_s": 450, "transfers": 3,
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("apcupsd %v, want %v", got, want)
	}
	if !reflect.DeepEqual(*calls, [][]string{{"apcaccess", "-u", "status"}}) {
		t.Errorf("calls %q", *calls)
	}
}

func TestApcupsdReadsCommlostAndAReportWithUnits(t *testing.T) {
	stubTools(t, answer{out: "STATUS   : COMMLOST \nBCHARGE  : 100.0 Percent\nTIMELEFT :  45.0 Minutes\n"})
	got, err := apcupsd(context.Background(), Target{})
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]any{
		"online": false, "on_battery": false, "low_battery": false, "commlost": true,
		"charge_pct": 100.0, "runtime_s": 2700,
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("apcupsd %v, want %v", got, want)
	}
}

func TestApcupsdFailsWhatItCannotRead(t *testing.T) {
	for name, a := range map[string]answer{
		"daemon down":      {err: &exec.ExitError{}},
		"no status":        {out: "BCHARGE  : 42.0\n"},
		"a charge no num":  {out: "STATUS   : ONLINE\nBCHARGE  : full\n"},
		"a runtime below0": {out: "STATUS   : ONLINE\nTIMELEFT : -1.0\n"},
	} {
		t.Run(name, func(t *testing.T) {
			stubTools(t, a)
			if _, err := apcupsd(context.Background(), Target{}); err == nil {
				t.Error("no error")
			}
		})
	}
	stubTools(t, answer{err: notInstalled("apcaccess")})
	if _, err := apcupsd(context.Background(), Target{}); !errors.Is(err, ErrUnsupported) {
		t.Errorf("error %v, want ErrUnsupported", err)
	}
}

func TestTheUPSViewsAreViewsOfUnits(t *testing.T) {
	for _, view := range []string{"nut_ups", "apcupsd"} {
		if v, ok := appViews[view]; !ok || !unitView(v) {
			t.Errorf("view %s: %v, want a view of a unit", view, v)
		}
	}
}
