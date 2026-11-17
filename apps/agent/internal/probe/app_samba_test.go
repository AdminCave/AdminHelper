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
	"slices"
	"strings"
	"testing"
	"time"
)

var sambaUnit = Target{Kind: kindUnit, Name: "samba-ad-dc.service"}

// drsAt is a time of replication as samba-tool drs showrepl prints it under sambaEnv.
func drsAt(at time.Time) string {
	return at.UTC().Format(drsTime)
}

// drsLinkJSON is one neighbour of samba-tool drs showrepl --json.
func drsLinkJSON(dsa string, failures int, last string, deleted bool) string {
	return fmt.Sprintf(`{"NC dn": "DC=example,DC=org", "DSA objectGUID": %q, "consecutive failures": %d,`+
		` "last success": %q, "last attempt": %q, "is deleted": %t, "NTDS DN": "CN=NTDS Settings,CN=DC2"}`,
		dsa, failures, last, last, deleted)
}

func TestSambaDRSCountsLinksAndTheOldestSuccess(t *testing.T) {
	at := time.Unix(1_795_000_000, 0)
	stubNow(t, at)
	out := `{"dsa": {"DSA objectGUID": "g0"}, "NTDSConnections": [], "repsFrom": [` +
		drsLinkJSON("g1", 0, drsAt(at.Add(-10*time.Minute)), false) + `,` +
		drsLinkJSON("g1", 2, drsAt(at.Add(-time.Hour)), false) + `,` +
		drsLinkJSON("g2", 0, drsNever, false) + `,` +
		drsLinkJSON("g3", 9, drsNever, true) +
		`], "repsTo": [` +
		drsLinkJSON("g1", 0, drsAt(at), false) + `,` +
		drsLinkJSON("g2", 1, drsAt(at.Add(-2*time.Hour)), false) + `,` +
		// A partition that never changed since the link was made: no notify, no success, no failure.
		drsLinkJSON("g1", 0, drsNever, false) + `,` +
		drsLinkJSON("g3", 4, drsNever, true) + `]}`
	calls := stubToolsEnv(t, answer{out: out})
	got, err := sambaDRS(context.Background(), sambaUnit)
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]any{"partners": 2, "links": 3, "links_failing": 2, "outbound_failing": 1, "last_success_age_s": 3600}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
	if c := (*calls)[0]; !slices.Equal(c.args, []string{"samba-tool", "drs", "showrepl", "--json"}) ||
		!slices.Equal(c.env, sambaEnv) {
		t.Fatalf("call %q with %q", c.args, c.env)
	}
}

func TestSambaDRSWithoutASuccessLeavesTheAgeOut(t *testing.T) {
	stubNow(t, time.Unix(1_795_000_000, 0))
	stubToolsEnv(t, answer{out: `{"repsFrom": [` + drsLinkJSON("g1", 0, drsNever, false) + `], "repsTo": []}`})
	got, err := sambaDRS(context.Background(), sambaUnit)
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]any{"partners": 1, "links": 1, "links_failing": 1, "outbound_failing": 0}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
}

func TestSambaDRSOfTheOnlyDCReportsAnAgeOfZero(t *testing.T) {
	stubNow(t, time.Unix(1_795_000_000, 0))
	for _, out := range []string{
		`{"repsFrom": [], "repsTo": []}`,
		`{"repsFrom": [` + drsLinkJSON("g9", 3, drsNever, true) + `], "repsTo": []}`,
	} {
		stubToolsEnv(t, answer{out: out})
		got, err := sambaDRS(context.Background(), sambaUnit)
		if err != nil {
			t.Fatal(err)
		}
		want := map[string]any{"partners": 0, "links": 0, "links_failing": 0, "outbound_failing": 0, "last_success_age_s": 0}
		if !reflect.DeepEqual(got, want) {
			t.Fatalf("%s: got %v, want %v", out, got, want)
		}
	}
}

// sideUnitShow is the answer of systemctl show -p Id,Names,ActiveState,MainPID for units in the state given.
func sideUnitShow(states ...string) string {
	var b strings.Builder
	for i, st := range states {
		if i > 0 {
			b.WriteString("\n")
		}
		fmt.Fprintf(&b, "MainPID=0\nId=%s\nNames=%s\nActiveState=%s\n", sambaSideUnits[i], sambaSideUnits[i], st)
	}
	return b.String()
}

func TestSambaDCUnitsCountsTheActiveSideUnits(t *testing.T) {
	for _, c := range []struct {
		states []string
		want   int
	}{
		{[]string{"inactive", "inactive", "inactive", "inactive", "inactive"}, 0},
		{[]string{"active", "inactive", "failed", "inactive", "inactive"}, 1},
		{[]string{"inactive", "reloading", "active", "inactive", "activating"}, 3},
	} {
		calls := stubToolsEnv(t, answer{out: sideUnitShow(c.states...)})
		got, err := sambaDCUnits(context.Background(), sambaUnit)
		if err != nil {
			t.Fatal(err)
		}
		if want := map[string]any{"side_units_active": c.want}; !reflect.DeepEqual(got, want) {
			t.Errorf("%v: got %v, want %v", c.states, got, want)
		}
		want := append([]string{"systemctl", "show", "-p", "Id,Names,ActiveState,MainPID", "--"}, sambaSideUnits...)
		if a := (*calls)[0].args; !slices.Equal(a, want) {
			t.Fatalf("call %q", a)
		}
	}
}

func TestSambaDCUnitsRefusesAnotherAnswer(t *testing.T) {
	stubToolsEnv(t, answer{out: sideUnitShow("inactive", "active")})
	if got, err := sambaDCUnits(context.Background(), sambaUnit); err == nil {
		t.Fatalf("two of five units read as %v", got)
	}
	stubToolsEnv(t, answer{err: exec.ErrNotFound})
	if _, err := sambaDCUnits(context.Background(), sambaUnit); !errors.Is(err, ErrUnsupported) {
		t.Fatalf("no systemctl: %v", err)
	}
}

func TestSambaDRSRefusesWhatIsNoLinkList(t *testing.T) {
	for _, out := range []string{
		"",
		"repsFrom: none",
		`{"repsFrom": []}`,
		`{"repsTo": []}`,
		`{"repsFrom": [{"DSA objectGUID": "g1", "last success": "NTTIME(0)"}], "repsTo": []}`,
		`{"repsFrom": [{"DSA objectGUID": "g1", "consecutive failures": 0}], "repsTo": []}`,
		`{"repsFrom": [` + drsLinkJSON("g1", -1, drsNever, false) + `], "repsTo": []}`,
		`{"repsFrom": [` + drsLinkJSON("g1", 0, "yesterday", false) + `], "repsTo": []}`,
		`{"repsFrom": [], "repsTo": [` + drsLinkJSON("g1", 0, "2026-11-14T12:00:00Z", false) + `]}`,
	} {
		stubToolsEnv(t, answer{out: out})
		if got, err := sambaDRS(context.Background(), sambaUnit); err == nil {
			t.Errorf("showrepl %q read as %v", out, got)
		}
	}
}

func TestSambaToolFailureQuotesNoStderr(t *testing.T) {
	stubToolsEnv(t, answer{err: toolExit(t, 255, "ERROR: DC1.example.org: CN=NTDS Settings unreachable\n")})
	_, err := sambaDRS(context.Background(), sambaUnit)
	if err == nil || !strings.Contains(err.Error(), "exit 255") || strings.Contains(err.Error(), "example") {
		t.Fatalf("a failed samba-tool = %v", err)
	}
	stubToolsEnv(t, answer{err: notInstalled("samba-tool")})
	if _, err := sambaFSMO(context.Background(), sambaUnit); !errors.Is(err, ErrUnsupported) {
		t.Fatalf("no samba-tool = %v, want unsupported", err)
	}
}

func TestSambaFSMOCountsRolesWithoutAValidOwner(t *testing.T) {
	out := "SchemaMasterRole owner: CN=NTDS Settings,CN=DC1,CN=Servers,CN=Default-First-Site-Name,CN=Sites,CN=Configuration,DC=example,DC=org\n" +
		`InfrastructureMasterRole owner: CN=NTDS Settings\0ADEL:6c1b0b5e-0000-4000-8000-000000000000,CN=DC2,CN=Servers,DC=example,DC=org` + "\n" +
		"RidAllocationMasterRole owner: CN=NTDS Settings,CN=DC1,DC=example,DC=org\n" +
		"PdcEmulationMasterRole has no current owner\n" +
		"DomainNamingMasterRole: * The attribute fSMORoleOwner is missing\n" +
		"DomainDnsZonesMasterRole owner: CN=NTDS Settings,CN=DC1,DC=example,DC=org\r\n" +
		"ForestDnsZonesMasterRole owner: CN=NTDS Settings,CN=DC1,DC=example,DC=org\n" +
		"WARNING: something unrelated\n"
	calls := stubToolsEnv(t, answer{out: out})
	got, err := sambaFSMO(context.Background(), sambaUnit)
	if err != nil {
		t.Fatal(err)
	}
	if want := map[string]any{"roles": 7, "roles_without_owner": 3}; !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
	if c := (*calls)[0]; !slices.Equal(c.args, []string{"samba-tool", "fsmo", "show"}) {
		t.Fatalf("call %q", c.args)
	}
	stubToolsEnv(t, answer{out: "Usage: samba-tool fsmo show\n"})
	if got, err := sambaFSMO(context.Background(), sambaUnit); err == nil {
		t.Fatalf("an answer without roles read as %v", got)
	}
}

// smbstatusJSON is smbstatus --json --fast with two sessions, one share connection and no open file.
const smbstatusJSON = `{"timestamp": "2026-11-14T12:00:00+0000", "version": "4.22.3", "smb_conf": "/etc/samba/smb.conf",
 "sessions": {"3412": {"username": "alice", "remote_machine": "192.0.2.7"}, "3413": {"username": "bob"}},
 "tcons": {"3412:57": {"service": "homes", "machine": "192.0.2.7"}},
 "open_files": {}}`

func TestSambaMemberReadsConfigCountsAndWinbind(t *testing.T) {
	calls := stubToolsEnv(t,
		answer{err: toolExit(t, 1, "Load smb config files from /etc/samba/smb.conf\nUnknown parameter\n")},
		answer{out: smbstatusJSON},
		answer{out: "Ping to winbindd succeeded\n"},
		answer{err: toolExit(t, 1, "checking the NETLOGON for domain[EXAMPLE] dc connection failed\n")},
	)
	got, err := sambaMember(context.Background(), sambaUnit)
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]any{"config_ok": false, "sessions": 2, "tcons": 1, "open_files": 0, "winbind_ok": true, "dc_ok": false}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
	var args [][]string
	for _, c := range *calls {
		args = append(args, c.args)
		if !slices.Equal(c.env, sambaEnv) {
			t.Errorf("call %q with %q", c.args, c.env)
		}
	}
	want2 := [][]string{{"testparm", "-s"}, {"smbstatus", "--json", "--fast"}, {"wbinfo", "-p"}, {"wbinfo", "-P"}}
	if !reflect.DeepEqual(args, want2) {
		t.Fatalf("calls %q", args)
	}
}

func TestSambaMemberWithoutWinbindOrSections(t *testing.T) {
	stubToolsEnv(t, answer{out: "[global]\n"}, answer{out: `{"timestamp": "now", "version": "4.19.5"}`},
		answer{err: notInstalled("wbinfo")})
	got, err := sambaMember(context.Background(), sambaUnit)
	if err != nil {
		t.Fatal(err)
	}
	if want := map[string]any{"config_ok": true, "sessions": 0, "tcons": 0, "open_files": 0}; !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
	// winbindd does not answer: its domain controller is not asked.
	calls := stubToolsEnv(t, answer{}, answer{out: smbstatusJSON}, answer{err: context.DeadlineExceeded})
	got, err = sambaMember(context.Background(), sambaUnit)
	if err != nil {
		t.Fatal(err)
	}
	if got["winbind_ok"] != false || got["dc_ok"] != false || len(*calls) != 3 {
		t.Fatalf("got %v after %d calls", got, len(*calls))
	}
}

func TestSambaMemberRefusesWhatItCannotRead(t *testing.T) {
	stubToolsEnv(t, answer{err: notInstalled("testparm")})
	if _, err := sambaMember(context.Background(), sambaUnit); !errors.Is(err, ErrUnsupported) {
		t.Fatalf("no testparm = %v, want unsupported", err)
	}
	stubToolsEnv(t, answer{}, answer{err: notInstalled("smbstatus")})
	if _, err := sambaMember(context.Background(), sambaUnit); !errors.Is(err, ErrUnsupported) {
		t.Fatalf("no smbstatus = %v, want unsupported", err)
	}
	for _, out := range []string{"", "sessions: 2", `{"sessions": []}`, `{"tcons": 3}`, `{"open_files": "none"}`} {
		stubToolsEnv(t, answer{}, answer{out: out})
		if got, err := sambaMember(context.Background(), sambaUnit); err == nil {
			t.Errorf("smbstatus %q read as %v", out, got)
		}
	}
	stubToolsEnv(t, answer{}, answer{out: smbstatusJSON}, answer{err: errors.New("fork failed")})
	if _, err := sambaMember(context.Background(), sambaUnit); err == nil {
		t.Fatal("a wbinfo that cannot start reads as a state")
	}
}

// An smbstatus before Samba 4.17 knows no --json and exits 1: the counts go, smb.conf and winbind stay.
func TestSambaMemberWithoutSmbstatusJSONKeepsConfigAndWinbind(t *testing.T) {
	calls := stubToolsEnv(t,
		answer{},
		answer{err: toolExit(t, 1, "smbstatus: unknown option --json\n")},
		answer{},
		answer{err: toolExit(t, 1, "")},
	)
	got, err := sambaMember(context.Background(), sambaUnit)
	if err != nil {
		t.Fatalf("sambaMember = %v", err)
	}
	want := map[string]any{"config_ok": true, "winbind_ok": true, "dc_ok": false}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
	if len(*calls) != 4 {
		t.Fatalf("calls = %v", *calls)
	}
}

func TestSambaTrust(t *testing.T) {
	for _, tc := range []struct {
		a    answer
		want bool
	}{
		{answer{out: "checking the trust secret for domain EXAMPLE via RPC calls succeeded\n"}, true},
		{answer{err: toolExit(t, 1, "checking the trust secret for domain EXAMPLE via RPC calls failed\n")}, false},
		{answer{err: context.DeadlineExceeded}, false},
	} {
		calls := stubToolsEnv(t, tc.a)
		got, err := sambaTrust(context.Background(), sambaUnit)
		if err != nil {
			t.Fatal(err)
		}
		if want := map[string]any{"trust_ok": tc.want}; !reflect.DeepEqual(got, want) {
			t.Errorf("got %v, want %v", got, want)
		}
		if c := (*calls)[0]; !slices.Equal(c.args, []string{"wbinfo", "-t"}) {
			t.Errorf("call %q", c.args)
		}
	}
	stubToolsEnv(t, answer{err: notInstalled("wbinfo")})
	if _, err := sambaTrust(context.Background(), sambaUnit); !errors.Is(err, ErrUnsupported) {
		t.Fatalf("no wbinfo = %v, want unsupported", err)
	}
	// The deadline of the probe itself is no failed check.
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	stubToolsEnv(t, answer{err: context.DeadlineExceeded})
	if got, err := sambaTrust(ctx, sambaUnit); err == nil {
		t.Fatalf("a probe past its deadline read as %v", got)
	}
}

func TestDirectoryViewsAreBoundToTheirKinds(t *testing.T) {
	for _, view := range []string{"samba_dc_units", "samba_drs", "samba_fsmo", "samba_member", "samba_trust", "lmn_devices", "lmn_linbo"} {
		if v, ok := appViews[view]; !ok || !slices.Equal(v.kinds, unitKinds) || v.uses != nil {
			t.Errorf("view %s: %+v", view, v)
		}
	}
}
