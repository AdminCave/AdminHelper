// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"reflect"
	"sort"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"
)

// Abbreviated but structurally realistic `smartctl --all --json=c` output of an
// ATA HDD (smartctl 7.x).
const ataFixture = `{
  "json_format_version": [1, 0],
  "smartctl": {"version": [7, 4], "exit_status": 0},
  "device": {"name": "/dev/sda", "info_name": "/dev/sda [SAT]", "type": "sat", "protocol": "ATA"},
  "model_name": "WDC WD40EFRX-68N32N0",
  "serial_number": "WD-WCC7K2ABCDEF",
  "rotation_rate": 5400,
  "smart_status": {"passed": true},
  "temperature": {"current": 34},
  "power_on_time": {"hours": 21340},
  "ata_smart_attributes": {
    "revision": 16,
    "table": [
      {"id": 5,   "name": "Reallocated_Sector_Ct",   "value": 200, "worst": 200, "thresh": 140, "raw": {"value": 3,  "string": "3"}},
      {"id": 10,  "name": "Spin_Retry_Count",        "value": 100, "worst": 100, "thresh": 0,   "raw": {"value": 1,  "string": "1"}},
      {"id": 187, "name": "Reported_Uncorrect",      "value": 100, "worst": 100, "thresh": 0,   "raw": {"value": 4,  "string": "4"}},
      {"id": 194, "name": "Temperature_Celsius",     "value": 116, "worst": 98,  "thresh": 0,   "raw": {"value": 34, "string": "34"}},
      {"id": 196, "name": "Reallocated_Event_Count", "value": 200, "worst": 200, "thresh": 0,   "raw": {"value": 2,  "string": "2"}},
      {"id": 197, "name": "Current_Pending_Sector",  "value": 200, "worst": 200, "thresh": 0,   "raw": {"value": 5,  "string": "5"}},
      {"id": 198, "name": "Offline_Uncorrectable",   "value": 100, "worst": 253, "thresh": 0,   "raw": {"value": 6,  "string": "6"}},
      {"id": 199, "name": "UDMA_CRC_Error_Count",    "value": 200, "worst": 200, "thresh": 0,   "raw": {"value": 7,  "string": "7"}}
    ]
  }
}`

// Abbreviated but structurally realistic `smartctl --all --json=c` output of an
// NVMe SSD (smartctl 7.x).
const nvmeFixture = `{
  "json_format_version": [1, 0],
  "smartctl": {"version": [7, 4], "exit_status": 0},
  "device": {"name": "/dev/nvme0", "info_name": "/dev/nvme0", "type": "nvme", "protocol": "NVMe"},
  "model_name": "Samsung SSD 980 1TB",
  "serial_number": "S649NX0T123456",
  "smart_status": {"passed": true, "nvme": {"value": 0}},
  "temperature": {"current": 41},
  "power_on_time": {"hours": 8760},
  "nvme_smart_health_information_log": {
    "critical_warning": 1,
    "temperature": 41,
    "available_spare": 98,
    "available_spare_threshold": 10,
    "percentage_used": 3,
    "media_and_data_integrity_errors": 2,
    "num_err_log_entries": 12
  }
}`

func mustUnmarshalSmart(t *testing.T, fixture string) *smartctlJSON {
	t.Helper()
	var raw smartctlJSON
	if err := json.Unmarshal([]byte(fixture), &raw); err != nil {
		t.Fatalf("Fixture unmarshalen: %v", err)
	}
	return &raw
}

func TestParseATAHealth(t *testing.T) {
	raw := mustUnmarshalSmart(t, ataFixture)
	disk := &SmartDisk{}
	parseATAHealth(disk, raw)

	cases := []struct {
		name string
		got  int
		want int
	}{
		{"ReallocatedSectors (5)", disk.ReallocatedSectors, 3},
		{"SpinRetryCount (10)", disk.SpinRetryCount, 1},
		{"ReportedUncorrect (187)", disk.ReportedUncorrect, 4},
		{"ReallocationEvents (196)", disk.ReallocationEvents, 2},
		{"PendingSectors (197)", disk.PendingSectors, 5},
		{"Uncorrectable (198)", disk.Uncorrectable, 6},
		{"UDMACRCErrors (199)", disk.UDMACRCErrors, 7},
	}
	for _, c := range cases {
		if c.got != c.want {
			t.Errorf("%s = %d, erwartet %d", c.name, c.got, c.want)
		}
	}
}

func TestParseATAHealthFixtureMetadata(t *testing.T) {
	raw := mustUnmarshalSmart(t, ataFixture)
	if raw.ModelName != "WDC WD40EFRX-68N32N0" {
		t.Errorf("ModelName = %q", raw.ModelName)
	}
	if !raw.SmartStatus.Passed {
		t.Error("SmartStatus.Passed = false, erwartet true")
	}
	if raw.Temperature.Current != 34 {
		t.Errorf("Temperature.Current = %d, erwartet 34", raw.Temperature.Current)
	}
	if raw.PowerOnTime.Hours != 21340 {
		t.Errorf("PowerOnTime.Hours = %d, erwartet 21340", raw.PowerOnTime.Hours)
	}
}

func TestParseNVMeHealth(t *testing.T) {
	raw := mustUnmarshalSmart(t, nvmeFixture)
	disk := &SmartDisk{}
	parseNVMeHealth(disk, raw)

	cases := []struct {
		name string
		got  int
		want int
	}{
		{"AvailableSparePct", disk.AvailableSparePct, 98},
		{"PercentageUsed", disk.PercentageUsed, 3},
		{"MediaErrors", disk.MediaErrors, 2},
		{"CriticalWarning", disk.CriticalWarning, 1},
	}
	for _, c := range cases {
		if c.got != c.want {
			t.Errorf("%s = %d, erwartet %d", c.name, c.got, c.want)
		}
	}
}

func TestParseHealthMissingSections(t *testing.T) {
	// Degenerate but valid smartctl output (e.g. device without SMART data):
	// the parsers must leave zero values, not panic.
	raw := mustUnmarshalSmart(t, `{"device": {"protocol": "ATA"}, "model_name": "X"}`)

	ata := &SmartDisk{}
	parseATAHealth(ata, raw)
	if ata.ReallocatedSectors != 0 || ata.PendingSectors != 0 || ata.UDMACRCErrors != 0 {
		t.Errorf("ATA-Felder ohne Attribut-Tabelle nicht 0: %+v", ata)
	}

	nvme := &SmartDisk{}
	parseNVMeHealth(nvme, raw)
	if nvme.AvailableSparePct != 0 || nvme.PercentageUsed != 0 || nvme.MediaErrors != 0 {
		t.Errorf("NVMe-Felder ohne Health-Log nicht 0: %+v", nvme)
	}
}

func TestSmartctlJSONInvalid(t *testing.T) {
	// Broken smartctl output must fail at unmarshal time — querySmartDevice
	// returns nil for the device in that case.
	cases := map[string]string{
		"truncated": `{"model_name": "X", "ata_smart_attr`,
		"not json":  `smartctl: /dev/sda: Unable to detect device type`,
		"empty":     ``,
	}
	for name, body := range cases {
		t.Run(name, func(t *testing.T) {
			var raw smartctlJSON
			if err := json.Unmarshal([]byte(body), &raw); err == nil {
				t.Errorf("Unmarshal(%q) erwartete Fehler, bekam keinen", body)
			}
		})
	}
}

func TestDetermineKind(t *testing.T) {
	cases := []struct {
		protocol     string
		rotationRate int
		want         string
	}{
		{"NVMe", 0, "NVMe"},
		{"ATA", 0, "SATA-SSD"},
		{"ATA", 5400, "HDD"},
		{"ATA", 7200, "HDD"},
	}
	for _, c := range cases {
		if got := determineKind(c.protocol, c.rotationRate); got != c.want {
			t.Errorf("determineKind(%q, %d) = %q, erwartet %q",
				c.protocol, c.rotationRate, got, c.want)
		}
	}
}

// `smartctl --scan --json=c` of a host with one SATA disk and one NVMe SSD (smartctl 7.x).
const smartScanFixture = `{"json_format_version":[1,0],"smartctl":{"version":[7,4],"exit_status":0},` +
	`"devices":[{"name":"/dev/sda","info_name":"/dev/sda [SAT]","type":"sat","protocol":"ATA"},` +
	`{"name":"/dev/nvme0","info_name":"/dev/nvme0","type":"nvme","protocol":"NVMe"}]}`

// smartctlCall is one recorded call of the fake smartctl.
type smartctlCall struct {
	timeout time.Duration
	args    []string
}

// stubSmartctl swaps smartctlCLI for a fake smartctl that is on the PATH: it answers the scan with
// scan and the query of a device with devices[device]. It returns the recorded calls; a device
// without a reply fails the test. The queries run in parallel, hence the lock.
func stubSmartctl(t *testing.T, scan dockerReply, devices map[string]dockerReply) *[]smartctlCall {
	t.Helper()
	old := smartctlCLI
	t.Cleanup(func() { smartctlCLI = old })
	var (
		mu    sync.Mutex
		calls []smartctlCall
	)
	smartctlCLI.lookPath = func(file string) (string, error) { return "/usr/sbin/" + file, nil }
	smartctlCLI.run = func(_ context.Context, timeout time.Duration, name string, args ...string) ([]byte, error) {
		mu.Lock()
		calls = append(calls, smartctlCall{timeout, args})
		mu.Unlock()
		if name != "/usr/sbin/smartctl" {
			t.Errorf("ran %q, want the smartctl found on the PATH", name)
		}
		if args[0] == "--scan" {
			return []byte(scan.out), scan.err
		}
		reply, ok := devices[args[len(args)-1]]
		if !ok {
			t.Errorf("unexpected smartctl call %v", args)
			return nil, errors.New("unexpected call")
		}
		return []byte(reply.out), reply.err
	}
	return &calls
}

func assertSmartAbsent(t *testing.T, disks []SmartDisk, reason, want string) {
	t.Helper()
	if disks != nil || reason != want {
		t.Errorf("collectSmart() = %v, %q; want nil, %q", disks, reason, want)
	}
}

func TestCollectSmartNotInstalled(t *testing.T) {
	calls := stubSmartctl(t, dockerReply{}, nil)
	smartctlCLI.lookPath = func(string) (string, error) { return "", exec.ErrNotFound }
	disks, reason := collectSmart(context.Background())
	assertSmartAbsent(t, disks, reason, "not_installed")
	if len(*calls) != 0 {
		t.Errorf("smartctl was called without a smartctl binary: %v", *calls)
	}
}

func TestCollectSmartScanFailed(t *testing.T) {
	cases := map[string]dockerReply{
		"scan fails":     {err: &exec.Error{Name: "/usr/sbin/smartctl", Err: exec.ErrNotFound}},
		"scan times out": {err: context.DeadlineExceeded},
		// The plain-text scan of a smartctl that ignores --json.
		"scan prints no JSON": {out: "/dev/sda -d sat # /dev/sda [SAT], ATA device\n"},
		"scan prints nothing": {out: ""},
	}
	for name, scan := range cases {
		t.Run(name, func(t *testing.T) {
			calls := stubSmartctl(t, scan, nil)
			disks, reason := collectSmart(context.Background())
			assertSmartAbsent(t, disks, reason, "scan_failed")
			if len(*calls) != 1 {
				t.Errorf("calls = %v, want only the scan", *calls)
			}
		})
	}
}

func TestCollectSmartNoDevices(t *testing.T) {
	cases := map[string]string{
		// smartctl leaves the devices key out when the scan finds none.
		"devices missing": `{"json_format_version":[1,0],"smartctl":{"version":[7,4],"exit_status":0}}`,
		"devices empty":   `{"json_format_version":[1,0],"devices":[]}`,
	}
	for name, out := range cases {
		t.Run(name, func(t *testing.T) {
			calls := stubSmartctl(t, dockerReply{out: out}, nil)
			disks, reason := collectSmart(context.Background())
			assertSmartAbsent(t, disks, reason, "no_devices")
			if len(*calls) != 1 {
				t.Errorf("calls = %v, want only the scan", *calls)
			}
		})
	}
}

func TestCollectSmartNoDeviceReadable(t *testing.T) {
	// The scan found disks but not one query gave readable SMART data (hung, did not start, no JSON):
	// that is a failed read, not a host without SMART-capable devices.
	stubSmartctl(t, dockerReply{out: smartScanFixture}, map[string]dockerReply{
		"/dev/sda":   {err: context.DeadlineExceeded},
		"/dev/nvme0": {out: "not json"},
	})
	disks, reason := collectSmart(context.Background())
	assertSmartAbsent(t, disks, reason, "scan_failed")
}

func TestCollectSmartDisks(t *testing.T) {
	calls := stubSmartctl(t, dockerReply{out: smartScanFixture}, map[string]dockerReply{
		"/dev/sda":   {out: ataFixture},
		"/dev/nvme0": {out: nvmeFixture},
	})
	disks, reason := collectSmart(context.Background())
	if reason != "" {
		t.Errorf("reason = %q, want none with disks", reason)
	}
	var devices []string
	for _, d := range disks {
		devices = append(devices, d.Device+" "+d.Kind)
	}
	sort.Strings(devices)
	if want := []string{"/dev/nvme0 NVMe", "/dev/sda HDD"}; !reflect.DeepEqual(devices, want) {
		t.Errorf("disks = %v, want %v", devices, want)
	}

	// The scan keeps its 15s cap, every device query its own 30s one.
	want := map[string]time.Duration{"--scan": 15 * time.Second, "/dev/sda": 30 * time.Second,
		"/dev/nvme0": 30 * time.Second}
	got := map[string]time.Duration{}
	for _, c := range *calls {
		if c.args[0] == "--scan" {
			got["--scan"] = c.timeout
		} else {
			got[c.args[len(c.args)-1]] = c.timeout
		}
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("timeouts = %v, want %v", got, want)
	}
}

func TestCollectSmartSomeDisksReadable(t *testing.T) {
	// One readable disk is SMART data: the unreadable one drops out, there is no absence reason.
	stubSmartctl(t, dockerReply{out: smartScanFixture}, map[string]dockerReply{
		"/dev/sda":   {err: context.DeadlineExceeded},
		"/dev/nvme0": {out: nvmeFixture},
	})
	disks, reason := collectSmart(context.Background())
	if reason != "" || len(disks) != 1 || disks[0].Device != "/dev/nvme0" {
		t.Errorf("collectSmart() = %v, %q; want only /dev/nvme0 and no reason", disks, reason)
	}
}

func TestCollectSmartPassesItsContextToEveryCall(t *testing.T) {
	// The scan and each device query run under the collector's context, not a fresh one: that
	// is what lets the end of the run's context stop them.
	type ctxKey struct{}
	stubSmartctl(t, dockerReply{out: smartScanFixture}, map[string]dockerReply{
		"/dev/sda": {out: ataFixture}, "/dev/nvme0": {out: nvmeFixture},
	})
	fake := smartctlCLI.run
	var mu sync.Mutex
	got := map[string]bool{}
	smartctlCLI.run = func(c context.Context, timeout time.Duration, name string, args ...string) ([]byte, error) {
		mu.Lock()
		got[args[len(args)-1]] = c.Value(ctxKey{}) == t.Name()
		mu.Unlock()
		return fake(c, timeout, name, args...)
	}
	collectSmart(context.WithValue(context.Background(), ctxKey{}, t.Name()))
	if len(got) != 3 {
		t.Fatalf("smartctl calls = %v, want the scan and two devices", got)
	}
	for call, ok := range got {
		if !ok {
			t.Errorf("the call ending in %s did not get the collector's context", call)
		}
	}
}

func TestCollectSmartStopsAtTheEndOfTheContext(t *testing.T) {
	// The queries run in parallel, so the loop checks the context before it starts each one, and every
	// query that runs ends with it: a disk read before stays, a query the context ended drops out.
	// nvme0 comes first, so its query has started before the hanging ones the cancel waits for.
	const scan = `{"json_format_version":[1,0],"devices":[` +
		`{"name":"/dev/nvme0","info_name":"/dev/nvme0","type":"nvme","protocol":"NVMe"},` +
		`{"name":"/dev/sda","info_name":"/dev/sda [SAT]","type":"sat","protocol":"ATA"},` +
		`{"name":"/dev/sdb","info_name":"/dev/sdb [SAT]","type":"sat","protocol":"ATA"}]}`

	t.Run("ended by the scan", func(t *testing.T) {
		ctx, cancel := context.WithCancel(context.Background())
		defer cancel()
		calls := stubSmartctl(t, dockerReply{out: scan}, map[string]dockerReply{
			"/dev/nvme0": {out: nvmeFixture}, "/dev/sda": {out: ataFixture}, "/dev/sdb": {out: ataFixture},
		})
		fake := smartctlCLI.run
		smartctlCLI.run = func(c context.Context, timeout time.Duration, name string, args ...string) ([]byte, error) {
			out, err := fake(c, timeout, name, args...)
			if args[0] == "--scan" {
				cancel() // the scan still answers, but no device query may start after it
			}
			return out, err
		}
		disks, reason := collectSmart(ctx)
		assertSmartAbsent(t, disks, reason, "scan_failed")
		if len(*calls) != 1 {
			t.Errorf("calls = %v, want only the scan", *calls)
		}
	})

	t.Run("ended during the queries", func(t *testing.T) {
		ctx, cancel := context.WithCancel(context.Background())
		defer cancel()
		calls := stubSmartctl(t, dockerReply{out: scan}, map[string]dockerReply{
			"/dev/nvme0": {out: nvmeFixture}, "/dev/sda": {}, "/dev/sdb": {},
		})
		fake := smartctlCLI.run
		hanging := make(chan string, 2)
		smartctlCLI.run = func(c context.Context, timeout time.Duration, name string, args ...string) ([]byte, error) {
			out, err := fake(c, timeout, name, args...)
			if dev := args[len(args)-1]; dev != "/dev/nvme0" && args[0] != "--scan" {
				// A hanging disk: its query ends only with its context, as runTimed's does.
				hanging <- dev
				select {
				case <-c.Done():
					return nil, c.Err()
				case <-time.After(5 * time.Second):
					t.Errorf("the query of %s did not end with the collector's context", dev)
					return nil, context.DeadlineExceeded
				}
			}
			return out, err
		}
		go func() {
			for range 2 {
				select {
				case <-hanging:
				case <-time.After(5 * time.Second):
				}
			}
			cancel()
		}()
		disks, reason := collectSmart(ctx)
		if reason != "" || len(disks) != 1 || disks[0].Device != "/dev/nvme0" {
			t.Errorf("collectSmart() = %v, %q; want only /dev/nvme0 and no reason", disks, reason)
		}
		if len(*calls) != 4 {
			t.Errorf("calls = %v, want the scan and three queries", *calls)
		}
	})
}

// What smartctl 7.4 prints for a disk it cannot open (here: run without root), with exit status 2:
// no smart_status, the reason only in the messages.
const smartOpenFailedFixture = `{"json_format_version":[1,0],"smartctl":{"version":[7,4],"pre_release":false,` +
	`"svn_revision":"5530","platform_info":"x86_64-linux-6.12.107+deb13-amd64","build_info":"(local build)",` +
	`"argv":["smartctl","--all","--json=c","/dev/sda"],"messages":[{"string":"Smartctl open device: /dev/sda ` +
	`failed: Permission denied","severity":"error"}],"exit_status":2},` +
	`"local_time":{"time_t":1792394492,"asctime":"Mon Oct 19 09:21:32 2026 CEST"}}`

// smartctlHelperEnv tells TestHelperSmartctlProcess, run as a child process, which exit status to end with.
const smartctlHelperEnv = "AH_SMARTCTL_HELPER_EXIT"

// TestHelperSmartctlProcess is no test of its own: smartctlExit starts the test binary as its child
// process, which then ends with the exit status smartctlHelperEnv names. Without it, it returns at once.
func TestHelperSmartctlProcess(t *testing.T) {
	if code, err := strconv.Atoi(os.Getenv(smartctlHelperEnv)); err == nil {
		os.Exit(code)
	}
}

// smartctlExit returns what runTimed reports for a smartctl that ends with code: the real
// *exec.ExitError of a child process, which querySmartDevice asserts on, on every platform.
func smartctlExit(t *testing.T, code int) error {
	t.Helper()
	t.Setenv(smartctlHelperEnv, strconv.Itoa(code))
	_, err := runTimed(context.Background(), time.Minute, os.Args[0], "-test.run=^TestHelperSmartctlProcess$")
	var exitErr *exec.ExitError
	if !errors.As(err, &exitErr) || exitErr.ExitCode() != code {
		t.Fatalf("helper process: err = %v, want an ExitError with status %d", err, code)
	}
	return err
}

func TestCollectSmartOpenFailed(t *testing.T) {
	// smartctl(8), EXIT STATUS: bit 0 is a command line that did not parse, bit 1 a device that did
	// not open, so smartctl read nothing, and its JSON without smart_status would pass for a failed
	// SMART check: the disk drops out. The other bits come with what it read: the disk stays, with the
	// full exit status.
	cases := []struct {
		name string
		sda  string
		code int
		want []string
	}{
		{"bit 0", smartOpenFailedFixture, 1, []string{"/dev/nvme0 0"}},
		{"bit 1", smartOpenFailedFixture, 2, []string{"/dev/nvme0 0"}},
		{"bit 2", ataFixture, 4, []string{"/dev/nvme0 0", "/dev/sda 4"}},
		{"bit 6", ataFixture, 64, []string{"/dev/nvme0 0", "/dev/sda 64"}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			stubSmartctl(t, dockerReply{out: smartScanFixture}, map[string]dockerReply{
				"/dev/sda":   {out: c.sda, err: smartctlExit(t, c.code)},
				"/dev/nvme0": {out: nvmeFixture},
			})
			disks, reason := collectSmart(context.Background())
			var got []string
			for _, d := range disks {
				got = append(got, fmt.Sprintf("%s %d", d.Device, d.SmartctlStatus))
			}
			sort.Strings(got)
			if reason != "" || !reflect.DeepEqual(got, c.want) {
				t.Errorf("collectSmart() = %v, %q; want %v and no reason", got, reason, c.want)
			}
		})
	}

	t.Run("no other disk", func(t *testing.T) {
		// The disk smartctl could not open is the only one: no disk gave readable SMART data.
		const scan = `{"json_format_version":[1,0],"smartctl":{"version":[7,4],"exit_status":0},` +
			`"devices":[{"name":"/dev/sda","info_name":"/dev/sda [SAT]","type":"sat","protocol":"ATA"}]}`
		stubSmartctl(t, dockerReply{out: scan}, map[string]dockerReply{
			"/dev/sda": {out: smartOpenFailedFixture, err: smartctlExit(t, 2)},
		})
		disks, reason := collectSmart(context.Background())
		assertSmartAbsent(t, disks, reason, "scan_failed")
	})
}

func TestCollectSmartPassesScanType(t *testing.T) {
	// Two disks behind a MegaRAID controller share /dev/bus/0, and only the type from the scan
	// (megaraid,N) tells smartctl which one to read: without -d it cannot detect the device type.
	// scsi is the exception, the scan line smartctl 7.4 prints for a plain /dev/sdX: -d scsi would
	// switch off the SAT detection on open, and a SATA disk would come without its ATA attributes.
	const scan = `{"json_format_version":[1,0],"smartctl":{"version":[7,4],"exit_status":0},"devices":[` +
		`{"name":"/dev/bus/0","info_name":"/dev/bus/0 [megaraid_disk_00]","type":"megaraid,0","protocol":"SCSI"},` +
		`{"name":"/dev/bus/0","info_name":"/dev/bus/0 [megaraid_disk_01]","type":"megaraid,1","protocol":"SCSI"},` +
		`{"name":"/dev/sda","info_name":"/dev/sda","type":"scsi","protocol":"SCSI"},` +
		`{"name":"/dev/nvme0","info_name":"/dev/nvme0","type":"nvme","protocol":"NVMe"}]}`
	calls := stubSmartctl(t, dockerReply{out: scan}, map[string]dockerReply{
		"/dev/bus/0": {out: ataFixture},
		"/dev/sda":   {out: ataFixture},
		"/dev/nvme0": {out: nvmeFixture},
	})
	disks, reason := collectSmart(context.Background())
	if reason != "" || len(disks) != 4 {
		t.Errorf("collectSmart() = %v, %q; want four disks and no reason", disks, reason)
	}
	var queries []string
	for _, c := range *calls {
		if c.args[0] != "--scan" {
			queries = append(queries, strings.Join(c.args, " "))
		}
	}
	sort.Strings(queries)
	want := []string{
		"--all --json=c -d megaraid,0 /dev/bus/0",
		"--all --json=c -d megaraid,1 /dev/bus/0",
		"--all --json=c -d nvme /dev/nvme0",
		"--all --json=c /dev/sda",
	}
	if !reflect.DeepEqual(queries, want) {
		t.Errorf("queries = %q, want %q", queries, want)
	}
}

func TestCollectSmartControllerDiskIDs(t *testing.T) {
	// The disks behind a MegaRAID or sssraid controller share the scan name, so the report names them
	// by the scan's info_name (smartmontools os_linux.cpp), which the service keys metrics and
	// ignore_devices on. Not by the info_name of the query: ataFixture answers every query with
	// "/dev/sda [SAT]". Every other disk keeps its name, without a suffix such as [SAT].
	const scan = `{"json_format_version":[1,0],"smartctl":{"version":[7,4],"exit_status":0},"devices":[` +
		`{"name":"/dev/bus/0","info_name":"/dev/bus/0 [megaraid_disk_00]","type":"megaraid,0","protocol":"SCSI"},` +
		`{"name":"/dev/bus/0","info_name":"/dev/bus/0 [megaraid_disk_01]","type":"megaraid,1","protocol":"SCSI"},` +
		`{"name":"/dev/bsg/sssraid0","info_name":"/dev/bsg/sssraid0 [sssraid_disk_00_01]","type":"sssraid,0,1",` +
		`"protocol":"SCSI"},` +
		`{"name":"/dev/sda","info_name":"/dev/sda [SAT]","type":"sat","protocol":"ATA"},` +
		`{"name":"/dev/nvme0","info_name":"/dev/nvme0","type":"nvme","protocol":"NVMe"}]}`
	calls := stubSmartctl(t, dockerReply{out: scan}, map[string]dockerReply{
		"/dev/bus/0":        {out: ataFixture},
		"/dev/bsg/sssraid0": {out: ataFixture},
		"/dev/sda":          {out: ataFixture},
		"/dev/nvme0":        {out: nvmeFixture},
	})
	disks, reason := collectSmart(context.Background())
	var devices []string
	for _, d := range disks {
		devices = append(devices, d.Device)
	}
	sort.Strings(devices)
	wantDevices := []string{
		"/dev/bsg/sssraid0 [sssraid_disk_00_01]",
		"/dev/bus/0 [megaraid_disk_00]",
		"/dev/bus/0 [megaraid_disk_01]",
		"/dev/nvme0",
		"/dev/sda",
	}
	if reason != "" || !reflect.DeepEqual(devices, wantDevices) {
		t.Errorf("collectSmart() = %q, %q; want %q and no reason", devices, reason, wantDevices)
	}

	// The queries still go to the device name, the type picks the disk behind the controller.
	var queries []string
	for _, c := range *calls {
		if c.args[0] != "--scan" {
			queries = append(queries, strings.Join(c.args, " "))
		}
	}
	sort.Strings(queries)
	wantQueries := []string{
		"--all --json=c -d megaraid,0 /dev/bus/0",
		"--all --json=c -d megaraid,1 /dev/bus/0",
		"--all --json=c -d nvme /dev/nvme0",
		"--all --json=c -d sat /dev/sda",
		"--all --json=c -d sssraid,0,1 /dev/bsg/sssraid0",
	}
	if !reflect.DeepEqual(queries, wantQueries) {
		t.Errorf("queries = %q, want %q", queries, wantQueries)
	}

	t.Run("no info_name", func(t *testing.T) {
		// A scan line without info_name leaves the device name.
		const scan = `{"json_format_version":[1,0],"devices":[` +
			`{"name":"/dev/bus/0","type":"megaraid,0","protocol":"SCSI"}]}`
		stubSmartctl(t, dockerReply{out: scan}, map[string]dockerReply{"/dev/bus/0": {out: ataFixture}})
		disks, reason := collectSmart(context.Background())
		if reason != "" || len(disks) != 1 || disks[0].Device != "/dev/bus/0" {
			t.Errorf("collectSmart() = %v, %q; want only /dev/bus/0 and no reason", disks, reason)
		}
	})
}
