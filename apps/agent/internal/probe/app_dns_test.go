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

const rndcStatus = `version: BIND 9.18.33-1~deb12u2-Debian (Extended Support Version) <id:>
running on localhost: Linux x86_64 6.1.0-28-amd64
boot time: Wed, 12 Nov 2026 08:00:00 GMT
last configured: Wed, 12 Nov 2026 08:00:00 GMT
configuration file: /etc/bind/named.conf
CPUs found: 4
worker threads: 4
number of zones: 102 (97 automatic)
debug level: 0
xfers running: 0
xfers deferred: 0
soa queries in progress: 0
query logging is OFF
recursive clients: 12/900/1000
tcp clients: 0/150
TCP high-water: 3
server is up and running`

func TestBindStatusReadsZonesAndRecursiveClients(t *testing.T) {
	calls := stubTools(t, answer{out: rndcStatus})
	values, err := bindStatus(context.Background(), Target{Kind: kindUnit, Name: "named.service"})
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]any{"running": true, "zones": 102, "recursive_clients": 12, "recursive_limit": 1000}
	if !reflect.DeepEqual(values, want) {
		t.Errorf("values %v, want %v", values, want)
	}
	if !reflect.DeepEqual(*calls, [][]string{{"rndc", "status"}}) {
		t.Errorf("calls %q", *calls)
	}
	noneOf(t, values, "localhost", "named.conf")
}

func TestBindThatDoesNotAnswerIsAValue(t *testing.T) {
	stubTools(t, answer{err: &exec.ExitError{}})
	values, err := bindStatus(context.Background(), Target{Kind: kindUnit, Name: "named.service"})
	if err != nil || !reflect.DeepEqual(values, map[string]any{"running": false}) {
		t.Errorf("values %v, error %v, want only running false", values, err)
	}
}

func TestBindStatusFailsWhatItCannotRead(t *testing.T) {
	for name, out := range map[string]string{
		"no zone count":         "server is up and running",
		"zones not a number":    "number of zones: many (0 automatic)\n",
		"clients of other form": "number of zones: 1 (0 automatic)\nrecursive clients: 1/2\n",
	} {
		t.Run(name, func(t *testing.T) {
			stubTools(t, answer{out: out})
			if _, err := bindStatus(context.Background(), Target{}); err == nil {
				t.Error("no error")
			}
		})
	}
	stubTools(t, answer{err: notInstalled("rndc")})
	if _, err := bindStatus(context.Background(), Target{}); !errors.Is(err, ErrUnsupported) {
		t.Errorf("error %v, want ErrUnsupported", err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	stubTools(t, answer{err: context.Canceled})
	if _, err := bindStatus(ctx, Target{}); !errors.Is(err, context.Canceled) {
		t.Errorf("error %v, want the probe's own end", err)
	}
}

const unboundOut = `thread0.num.queries=900
total.num.queries=1000
total.num.queries_timed_out=0
total.requestlist.avg=0.5
total.requestlist.exceeded=3
time.up=3600.5
num.answer.rcode.NOERROR=900
num.answer.rcode.SERVFAIL=62
num.answer.rcode.NXDOMAIN=38
`

func TestUnboundStatsReadsCountersWithoutResettingThem(t *testing.T) {
	calls := stubTools(t, answer{out: unboundOut})
	values, err := unboundStats(context.Background(), Target{Kind: kindUnit, Name: "unbound.service"})
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]any{"queries": int64(1000), "requestlist_exceeded": int64(3), "servfail_pct": 6.2}
	if !reflect.DeepEqual(values, want) {
		t.Errorf("values %v, want %v", values, want)
	}
	if !reflect.DeepEqual(*calls, [][]string{{"unbound-control", "stats_noreset"}}) {
		t.Errorf("calls %q", *calls)
	}
}

func TestUnboundWithoutExtendedStatisticsHasNoServfailShare(t *testing.T) {
	stubTools(t, answer{out: "total.num.queries=0\ntotal.requestlist.exceeded=0\n"})
	values, err := unboundStats(context.Background(), Target{})
	want := map[string]any{"queries": int64(0), "requestlist_exceeded": int64(0)}
	if err != nil || !reflect.DeepEqual(values, want) {
		t.Errorf("values %v, error %v, want %v", values, err, want)
	}
}

func TestUnboundStatsFailsWhatItCannotRead(t *testing.T) {
	for name, a := range map[string]answer{
		"no queries":      {out: "total.requestlist.exceeded=0\n"},
		"not a number":    {out: "total.num.queries=x\ntotal.requestlist.exceeded=0\n"},
		"control refuses": {err: &exec.ExitError{}},
	} {
		t.Run(name, func(t *testing.T) {
			stubTools(t, a)
			if _, err := unboundStats(context.Background(), Target{}); err == nil {
				t.Error("no error")
			}
		})
	}
	stubTools(t, answer{err: notInstalled("unbound-control")})
	if _, err := unboundStats(context.Background(), Target{}); !errors.Is(err, ErrUnsupported) {
		t.Errorf("error %v, want ErrUnsupported", err)
	}
}

func TestChronyTrackingReadsSyncStratumAndOffset(t *testing.T) {
	for name, tc := range map[string]struct {
		out  string
		want map[string]any
	}{
		"synced": {
			"C0A80001,ntp.example.org,3,1731500000.123456789,-0.000123456,0.000010000,0.000050000," +
				"-12.345,0.001,0.050,0.012345678,0.001234567,64.2,Normal\n",
			map[string]any{"synced": true, "stratum": 3, "offset_abs_ms": 0.123},
		},
		"unsynced": {
			"00000000,,0,0.000000000,0.000000000,0.000000000,0.000000000,0.000,0.000,0.000,1.000000000," +
				"1.000000000,0.0,Not synchronised\n",
			map[string]any{"synced": false, "stratum": 0, "offset_abs_ms": 0.0},
		},
	} {
		t.Run(name, func(t *testing.T) {
			calls := stubTools(t, answer{out: tc.out})
			values, err := chronyTracking(context.Background(), Target{Kind: kindUnit, Name: "chrony.service"})
			if err != nil {
				t.Fatal(err)
			}
			if !reflect.DeepEqual(values, tc.want) {
				t.Errorf("values %v, want %v", values, tc.want)
			}
			if !reflect.DeepEqual(*calls, [][]string{{"chronyc", "-c", "tracking"}}) {
				t.Errorf("calls %q", *calls)
			}
			noneOf(t, values, "example", "C0A80001")
		})
	}
}

func TestChronyTrackingFailsWhatItCannotRead(t *testing.T) {
	for name, out := range map[string]string{
		"too few fields":     "C0A80001,x,3,0,0.1\n",
		"stratum not number": "C0A80001,x,y,0,0.1,0,0,0,0,0,0,0,0,Normal\n",
		"offset not number":  "C0A80001,x,3,0,z,0,0,0,0,0,0,0,0,Normal\n",
		"empty":              "",
	} {
		t.Run(name, func(t *testing.T) {
			stubTools(t, answer{out: out})
			if _, err := chronyTracking(context.Background(), Target{}); err == nil {
				t.Error("no error")
			}
		})
	}
	stubTools(t, answer{err: notInstalled("chronyc")})
	if _, err := chronyTracking(context.Background(), Target{}); !errors.Is(err, ErrUnsupported) {
		t.Errorf("error %v, want ErrUnsupported", err)
	}
}

func TestNtpsecStatusReadsSyncStratumAndOffset(t *testing.T) {
	for name, tc := range map[string]struct {
		out  string
		want map[string]any
	}{
		"synced":         {"leap=00, stratum=2, offset=-1.234567\n", map[string]any{"synced": true, "stratum": 2, "offset_abs_ms": 1.235}},
		"leap as digit":  {"leap=0, stratum=2, offset=0.5\n", map[string]any{"synced": true, "stratum": 2, "offset_abs_ms": 0.5}},
		"alarm":          {"leap=11, stratum=16, offset=0.000000\n", map[string]any{"synced": false, "stratum": 16, "offset_abs_ms": 0.0}},
		"stratum 16":     {"leap=00, stratum=16, offset=0\n", map[string]any{"synced": false, "stratum": 16, "offset_abs_ms": 0.0}},
		"wrapped output": {"leap=01,\nstratum=1, offset=12.5\n", map[string]any{"synced": true, "stratum": 1, "offset_abs_ms": 12.5}},
	} {
		t.Run(name, func(t *testing.T) {
			calls := stubTools(t, answer{out: tc.out})
			values, err := ntpsecStatus(context.Background(), Target{Kind: kindUnit, Name: "ntpsec.service"})
			if err != nil {
				t.Fatal(err)
			}
			if !reflect.DeepEqual(values, tc.want) {
				t.Errorf("values %v, want %v", values, tc.want)
			}
			if !reflect.DeepEqual(*calls, [][]string{{"ntpq", "-c", "rv 0 leap,stratum,offset"}}) {
				t.Errorf("calls %q", *calls)
			}
		})
	}
}

func TestNtpsecStatusFailsWhatItCannotRead(t *testing.T) {
	for name, out := range map[string]string{
		"no leap":      "stratum=2, offset=0\n",
		"leap unknown": "leap=xx, stratum=2, offset=0\n",
		"no offset":    "leap=00, stratum=2\n",
		"refused":      "***Request timed out\n",
	} {
		t.Run(name, func(t *testing.T) {
			stubTools(t, answer{out: out})
			if _, err := ntpsecStatus(context.Background(), Target{}); err == nil {
				t.Error("no error")
			}
		})
	}
	stubTools(t, answer{err: notInstalled("ntpq")})
	if _, err := ntpsecStatus(context.Background(), Target{}); !errors.Is(err, ErrUnsupported) {
		t.Errorf("error %v, want ErrUnsupported", err)
	}
}

func TestTheDNSAndTimeViewsAreViewsOfUnits(t *testing.T) {
	for _, view := range []string{"bind_status", "unbound_stats", "chrony_tracking", "ntpsec_status"} {
		if v, ok := appViews[view]; !ok || !unitView(v) {
			t.Errorf("view %s: %v, want a view of a unit", view, v)
		}
	}
}
