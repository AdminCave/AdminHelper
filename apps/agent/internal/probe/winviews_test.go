// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"errors"
	"math"
	"reflect"
	"runtime"
	"strings"
	"testing"
	"time"
)

const repadminCSV = `showrepl_COLUMNS,Destination DSA Site,Destination DSA,Naming Context,Source DSA Site,Source DSA,Transport Type,Number of Failures,Last Failure Time,Last Success Time,Last Failure Status
showrepl_INFO,Site-A,DC1,"DC=example,DC=org",Site-A,DC2,RPC,0,0,2026-11-14 11:50:00,0
showrepl_INFO,Site-A,DC1,"CN=Configuration,DC=example,DC=org",Site-A,dc2,RPC,0,0,2026-11-14 11:00:00,0
showrepl_INFO,Site-A,DC1,"DC=example,DC=org",Site-B,DC3,RPC,4,2026-11-14 11:55:00,2026-11-14 09:00:00,1722
showrepl_INFO,Site-A,DC1,"DC=ForestDnsZones,DC=example,DC=org",Site-B,DC3,RPC,1,2026-11-14 11:55:00,0,8524
`

func TestRepadminValuesCountsLinksPartnersAndTheOldestSuccess(t *testing.T) {
	now := time.Date(2026, 11, 14, 12, 0, 0, 0, time.Local)
	got, err := repadminValues([]byte(repadminCSV), now)
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]any{
		"partners":             2,
		"links":                4,
		"failing_links":        2,
		"never_links":          1,
		"oldest_success_age_s": int64(3 * 3600),
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("repadminValues() = %v, want %v", got, want)
	}
}

func TestRepadminValuesOfALoneDC(t *testing.T) {
	got, err := repadminValues([]byte("showrepl_COLUMNS,Source DSA,Number of Failures,Last Success Time\r\n"), time.Now())
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]any{"partners": 0, "links": 0, "failing_links": 0, "never_links": 0}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("repadminValues() = %v, want %v", got, want)
	}
}

func TestRepadminValuesRefusesAnotherForm(t *testing.T) {
	for name, out := range map[string]string{
		"empty":            "",
		"text output":      "Repository Administration Tool\nDC1\nDSA Options: IS_GC\n",
		"no column header": "showrepl_INFO,Site-A,DC1,x,Site-A,DC2,RPC,0,0,2026-11-14 11:50:00,0\n",
		"missing column":   "showrepl_COLUMNS,Source DSA,Last Success Time\nshowrepl_INFO,DC2,2026-11-14 11:50:00\n",
		"short row":        "showrepl_COLUMNS,Source DSA,Number of Failures,Last Success Time\nshowrepl_INFO,DC2\n",
		"failures no num":  "showrepl_COLUMNS,Source DSA,Number of Failures,Last Success Time\nshowrepl_INFO,DC2,x,0\n",
		"negative":         "showrepl_COLUMNS,Source DSA,Number of Failures,Last Success Time\nshowrepl_INFO,DC2,-1,0\n",
	} {
		if got, err := repadminValues([]byte(out), time.Now()); !errors.Is(err, errRepadminForm) {
			t.Errorf("%s: repadminValues() = %v, %v; want errRepadminForm", name, got, err)
		}
	}
}

func TestAppcmdStoppedCountsWhatIsNotStarted(t *testing.T) {
	sites := `<?xml version="1.0" encoding="UTF-8"?>
<appcmd>
    <SITE SITE.NAME="Default Web Site" SITE.ID="1" bindings="http/*:80:" state="Started" />
    <SITE SITE.NAME="intranet" SITE.ID="2" bindings="https/*:443:" state="Stopped" />
    <SITE SITE.NAME="legacy" SITE.ID="3" bindings="http/*:8080:" state="Unknown" />
</appcmd>`
	total, stopped, err := appcmdStopped([]byte(sites), "SITE")
	if err != nil || total != 3 || stopped != 2 {
		t.Errorf("appcmdStopped(sites) = %d, %d, %v; want 3, 2", total, stopped, err)
	}
	pools := `<appcmd><APPPOOL APPPOOL.NAME="DefaultAppPool" state="Started" /><APPPOOL APPPOOL.NAME="x" /></appcmd>`
	total, stopped, err = appcmdStopped([]byte(pools), "APPPOOL")
	if err != nil || total != 2 || stopped != 1 {
		t.Errorf("appcmdStopped(pools) = %d, %d, %v; want 2, 1", total, stopped, err)
	}
	total, stopped, err = appcmdStopped([]byte(`<appcmd></appcmd>`), "SITE")
	if err != nil || total != 0 || stopped != 0 {
		t.Errorf("appcmdStopped(none) = %d, %d, %v; want 0, 0", total, stopped, err)
	}
}

func TestAppcmdStoppedRefusesAnotherForm(t *testing.T) {
	for name, out := range map[string]string{
		"text":    `SITE "Default Web Site" (id:1,bindings:http/*:80:,state:Started)`,
		"broken":  `<appcmd><SITE state="Started"`,
		"no root": `<config><SITE state="Started" /></config>`,
	} {
		if _, _, err := appcmdStopped([]byte(out), "SITE"); !errors.Is(err, errAppcmdForm) {
			t.Errorf("%s: err = %v, want errAppcmdForm", name, err)
		}
	}
}

func TestDhcpValuesReportsTheFullestScope(t *testing.T) {
	got := dhcpValues([]dhcpScope{{InUse: 50, Free: 50}, {InUse: 82, Free: 18}, {InUse: 191, Free: 9}, {}})
	want := map[string]any{"scopes": 4, "max_used_pct": 95.5, "scopes_over_80": 2, "scopes_over_95": 1}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("dhcpValues() = %v, want %v", got, want)
	}
	// A server without a scope has no use to rate: no rule field, so the check is unknown (R-1465).
	got = dhcpValues(nil)
	want = map[string]any{"scopes": 0}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("dhcpValues(nil) = %v, want %v", got, want)
	}
}

func TestRdsValuesSkipsUnlimitedAndPermanentPacks(t *testing.T) {
	now := time.Date(2026, 11, 14, 12, 0, 0, 0, time.UTC)
	got := rdsValues([]rdsPack{
		{TotalLicenses: 50, IssuedLicenses: 40, ExpirationDate: time.Date(2038, 1, 19, 0, 0, 0, 0, time.UTC)},
		{TotalLicenses: 25, IssuedLicenses: 20, ExpirationDate: now.Add(30*24*time.Hour + time.Hour)},
		{TotalLicenses: math.MaxUint32, IssuedLicenses: 3},
		{TotalLicenses: 5, IssuedLicenses: 0, ExpirationDate: now.Add(-48 * time.Hour)},
	}, now)
	want := map[string]any{"licenses_total": uint64(80), "licenses_issued": uint64(60), "used_pct": 75.0, "min_days_left": 0}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("rdsValues() = %v, want %v", got, want)
	}
	got = rdsValues([]rdsPack{{TotalLicenses: math.MaxUint32, IssuedLicenses: 2}}, now)
	want = map[string]any{"licenses_total": uint64(0), "licenses_issued": uint64(0)}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("rdsValues(built-in only) = %v, want %v", got, want)
	}
}

func TestRdsValuesTakesTheNearestExpiry(t *testing.T) {
	now := time.Date(2026, 11, 14, 12, 0, 0, 0, time.UTC)
	got := rdsValues([]rdsPack{
		{TotalLicenses: 10, ExpirationDate: now.Add(90 * 24 * time.Hour)},
		{TotalLicenses: 10, ExpirationDate: now.Add(30*24*time.Hour + time.Hour)},
	}, now)
	if got["min_days_left"] != 30 {
		t.Errorf("min_days_left = %v, want 30", got["min_days_left"])
	}
}

func TestWuaValues(t *testing.T) {
	now := time.Date(2026, 11, 14, 12, 0, 0, 0, time.UTC)
	got := wuaState{open: 5, security: 2, reboot: true, lastSearch: now.Add(-2 * time.Hour)}.values(now)
	want := map[string]any{"updates_open": 5, "updates_security": 2, "reboot_required": true, "search_age_s": int64(7200)}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("values() = %v, want %v", got, want)
	}
	got = wuaState{}.values(now)
	want = map[string]any{"updates_open": 0, "updates_security": 0, "reboot_required": false}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("values(never searched) = %v, want %v", got, want)
	}
	for sev, want := range map[string]bool{"Critical": true, "Important": true, "Moderate": false, "Low": false, "": false} {
		if wuaSecurity(sev) != want {
			t.Errorf("wuaSecurity(%q) = %v, want %v", sev, !want, want)
		}
	}
}

func TestWinEventsWindowFollowsTheInterval(t *testing.T) {
	for interval, want := range map[int]time.Duration{
		0:      time.Hour,
		-5:     time.Hour,
		300:    5 * time.Minute,
		86400:  24 * time.Hour,
		604800: 24 * time.Hour,
	} {
		if got := winEventsWindow(interval); got != want {
			t.Errorf("winEventsWindow(%d) = %v, want %v", interval, got, want)
		}
	}
}

func TestMachineCertValuesCountsExpiredAndTheNextExpiry(t *testing.T) {
	now := time.Date(2026, 11, 14, 12, 0, 0, 0, time.UTC)
	got := machineCertValues([]time.Time{now.Add(-time.Hour), now.Add(400 * 24 * time.Hour), now.Add(20*24*time.Hour + time.Hour), now}, now)
	want := map[string]any{"certs": 4, "expired": 2, "min_days_left": 20}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("machineCertValues() = %v, want %v", got, want)
	}
	got = machineCertValues(nil, now)
	want = map[string]any{"certs": 0, "expired": 0}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("machineCertValues(nil) = %v, want %v", got, want)
	}
}

func TestTheWindowsViewsAreUnsupportedElsewhere(t *testing.T) {
	if runtime.GOOS == "windows" {
		return // there the views read the host; the CI's Windows job builds them
	}
	ctx := t.Context()
	for name, read := range map[string]func() (map[string]any, error){
		"ad_replication": func() (map[string]any, error) { return adReplication(ctx, Target{}) },
		"dhcp_scopes":    func() (map[string]any, error) { return dhcpScopes(ctx, Target{}) },
		"iis_state":      func() (map[string]any, error) { return iisState(ctx, Target{}) },
		"rds_licenses":   func() (map[string]any, error) { return rdsLicenses(ctx, Target{}) },
		"win_updates":    func() (map[string]any, error) { return winUpdates(ctx) },
		"win_certs":      func() (map[string]any, error) { return winCerts(ctx) },
		"win_events":     func() (map[string]any, error) { return winEvents(ctx, time.Hour) },
		"hyperv":         func() (map[string]any, error) { return hypervState(ctx, Target{}) },
		"dfsr":           func() (map[string]any, error) { return dfsrState(ctx, Target{}) },
		"print":          func() (map[string]any, error) { return printState(ctx, Target{}) },
		"mssql_events":   func() (map[string]any, error) { return mssqlEvents(ctx, Target{}) },
		"wsus":           func() (map[string]any, error) { return wsusState(ctx, Target{}) },
		"storage":        func() (map[string]any, error) { return storageHealth(ctx) },
		"defender":       func() (map[string]any, error) { return defenderStatus(ctx) },
		"win_backup":     func() (map[string]any, error) { return winBackup(ctx) },
		"veeam_windows":  func() (map[string]any, error) { return veeamWindows(ctx, Target{}) },
	} {
		if _, err := read(); !errors.Is(err, ErrUnsupported) {
			t.Errorf("%s: err = %v, want ErrUnsupported", name, err)
		}
	}
}

func TestTheHostSensorTakesTheWindowsViews(t *testing.T) {
	// By name only: a call would start a real Windows Update search and read the event log on
	// Windows.
	for _, view := range []string{"win_updates", "win_certs", "storage", "defender", "win_backup"} {
		if _, ok := hostViews[view]; !ok {
			t.Errorf("host view %s is missing", view)
		}
	}
	if winEventsView != "win_events" {
		t.Errorf("winEventsView = %q", winEventsView)
	}
	for _, view := range []string{"ad_replication", "dhcp_scopes", "iis_state", "rds_licenses",
		"hyperv", "dfsr", "print", "mssql_events", "wsus", "cups_queues", "veeam_windows"} {
		if _, ok := appViews[view]; !ok {
			t.Errorf("app view %s is missing", view)
		}
	}
}

var winNow = time.Date(2026, 11, 14, 12, 0, 0, 0, time.UTC)

func TestHypervValuesCountsGuestsAndSkipsTheHost(t *testing.T) {
	vms := []hypervVM{
		{Name: "HV01", EnabledState: 2, HealthState: 25}, // the host's own row
		{Name: "6F2D1C3A-1B2C-4D5E-8F90-A1B2C3D4E5F6", EnabledState: 2, HealthState: 5, ReplicationHealth: 1},
		{Name: "0a1b2c3d-0000-1111-2222-333344445555", EnabledState: 3, HealthState: 20, ReplicationHealth: 3},
		{Name: "11111111-2222-3333-4444-555555555555", EnabledState: 32768, HealthState: 5, ReplicationHealth: 2},
	}
	beats := []hypervHeartbeat{{OperationalStatus: []uint16{2}}, {OperationalStatus: []uint16{12}},
		{OperationalStatus: []uint16{13}}, {OperationalStatus: []uint16{7, 2}}, {}}
	settings := []hypervSetting{
		{VirtualSystemType: "Microsoft:Hyper-V:System:Realized", CreationTime: winNow.Add(-1000 * time.Hour)},
		{VirtualSystemType: hypervCheckpoint, CreationTime: winNow.Add(-48 * time.Hour)},
		{VirtualSystemType: hypervCheckpoint, CreationTime: winNow.Add(-2 * time.Hour)},
	}
	want := map[string]any{"vms": 3, "vms_running": 1, "vms_unhealthy": 1, "heartbeat_lost": 2,
		"replication_warning": 1, "replication_critical": 1, "checkpoints": 2,
		"oldest_checkpoint_age_s": int64(48 * 3600)}
	if got := hypervValues(vms, beats, settings, winNow); !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v\nwant %v", got, want)
	}
	if got := hypervValues(nil, nil, nil, winNow); got["vms"] != 0 || got["oldest_checkpoint_age_s"] != nil {
		t.Fatalf("a host without VMs: %v", got)
	}
}

func TestDfsrValuesCountsFoldersNotInNormalOperation(t *testing.T) {
	got := dfsrValues([]dfsrFolder{{State: 4}, {State: 5}, {State: 2}, {State: 4}}, 1, 0)
	want := map[string]any{"folders": 4, "folders_error": 1, "folders_not_normal": 2,
		"stopped_events_24h": 1, "offline_too_long_24h": 0}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
}

func TestStorageValuesLeavesOutWhatTheHostLacks(t *testing.T) {
	s := storageState{
		shadows:    []shadowCopy{{InstallDate: winNow.Add(-30 * time.Hour)}, {InstallDate: winNow.Add(-6 * time.Hour)}},
		physical:   []storageDisk{{HealthStatus: 0}, {HealthStatus: 2}, {HealthStatus: 5}},
		virtual:    []storageDisk{{HealthStatus: 1}},
		quotas:     []fsrmQuota{{Size: 100, Usage: 90}, {Size: 100, Usage: 89}, {Size: 0, Usage: 5}},
		volumes:    []encVolume{{ProtectionStatus: 1, VolumeType: 0}, {ProtectionStatus: 0, VolumeType: 1}, {ProtectionStatus: 0, VolumeType: 2}},
		hasDisks:   true,
		hasQuotas:  true,
		hasVolumes: true,
	}
	want := map[string]any{"shadow_copies": 2, "newest_shadow_age_s": int64(6 * 3600),
		"disks": 3, "disks_unhealthy": 1, "vdisks": 1, "vdisks_unhealthy": 1,
		"quotas": 3, "quotas_over_90": 1, "volumes": 2, "volumes_unprotected": 1}
	if got := storageValues(s, winNow); !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v\nwant %v", got, want)
	}
	if got := storageValues(storageState{}, winNow); !reflect.DeepEqual(got, map[string]any{"shadow_copies": 0}) {
		t.Fatalf("a host without Storage Spaces, FSRM and BitLocker: %v", got)
	}
}

func TestPrintValuesCountsFaultsAndTheOldestJob(t *testing.T) {
	printers := []printer{{}, {DetectedErrorState: 3}, {DetectedErrorState: 8}, {ExtendedPrinterStatus: 7}, {WorkOffline: true}}
	jobs := []printJob{{StatusMask: 16, TimeSubmitted: winNow.Add(-10 * time.Minute)},
		{StatusMask: 2 | 16, TimeSubmitted: winNow.Add(-3 * time.Hour)}, {StatusMask: 1024}}
	want := map[string]any{"printers": 5, "printers_error": 3, "jobs": 3, "jobs_error": 2,
		"oldest_job_age_s": int64(3 * 3600)}
	if got := printValues(printers, jobs, winNow); !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
}

func TestDefenderValues(t *testing.T) {
	threats := []mpThreat{{InitialDetectionTime: winNow.Add(-time.Hour)}, {InitialDetectionTime: winNow.Add(-50 * time.Hour)}, {}}
	got := defenderValues(mpStatus{RealTimeProtectionEnabled: true, AntivirusEnabled: true, AntivirusSignatureAge: 2}, "SxS Passive Mode", threats, winNow)
	want := map[string]any{"realtime_on": true, "antivirus_on": true, "detections_24h": 1, "signature_age_d": 2, "passive": true}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
	// Never updated is the oldest age there is, so the >= 4 rule rates it critical (R-1481).
	got = defenderValues(mpStatus{AntivirusSignatureAge: mpSignatureNever}, "", nil, winNow)
	if got["signature_age_d"] != mpSignatureNever {
		t.Fatalf("signatures never updated must report age %d: %v", mpSignatureNever, got)
	}
	if _, ok := got["passive"]; ok {
		t.Fatalf("an unknown mode read as a state: %v", got)
	}
}

func TestMssqlSourceTakesOnlyAnSQLServerService(t *testing.T) {
	for unit, want := range map[string]string{"MSSQLSERVER": "MSSQLSERVER", "MSSQL$SQLEXPRESS.service": "MSSQL$SQLEXPRESS"} {
		if got, err := mssqlSource(unit); err != nil || got != want {
			t.Errorf("%s: %q, %v; want %q", unit, got, err, want)
		}
	}
	for _, unit := range []string{"MSSQL$", "SQLSERVERAGENT", "MSSQL$a'b", "MSSQL$" + strings.Repeat("x", 17), "mssqlserver"} {
		if _, err := mssqlSource(unit); !errors.Is(err, ErrInvalid) {
			t.Errorf("%s: err = %v, want ErrInvalid", unit, err)
		}
	}
}

func TestFreeValues(t *testing.T) {
	if got := freeValues(25, 200); !reflect.DeepEqual(got, map[string]any{"content_free_bytes": uint64(25), "content_free_pct": 12.5}) {
		t.Fatalf("got %v", got)
	}
	if got := freeValues(0, 0); !reflect.DeepEqual(got, map[string]any{"content_free_bytes": uint64(0)}) {
		t.Fatalf("no total: %v", got)
	}
}

func TestWinBackupValues(t *testing.T) {
	got := winBackupValues(winNow.Add(-26*time.Hour), true, 2, winNow)
	want := map[string]any{"last_failed": true, "failures_24h": 2, "last_success_age_s": int64(26 * 3600)}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
	if got := winBackupValues(time.Time{}, false, 0, winNow); !reflect.DeepEqual(got, map[string]any{"last_failed": false, "failures_24h": 0}) {
		t.Fatalf("never a success: %v", got)
	}
}

func TestVeeamWindowsValuesTakesTheResultFromTheLevel(t *testing.T) {
	for level, want := range map[uint8]string{0: "success", 4: "success", 3: "warning", 2: "failed", 1: "failed"} {
		got := veeamWindowsValues(true, winNow.Add(-time.Hour), level, winNow)
		if got["last_result"] != want || got["last_run_age_s"] != int64(3600) || got["runs"] != 1 {
			t.Errorf("level %d: %v, want %s", level, got, want)
		}
	}
	if got := veeamWindowsValues(false, time.Time{}, 0, winNow); !reflect.DeepEqual(got, map[string]any{"runs": 0}) {
		t.Fatalf("no job end: %v", got)
	}
}
