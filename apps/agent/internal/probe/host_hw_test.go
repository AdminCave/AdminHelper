// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"slices"
	"strings"
	"testing"
	"time"
)

// stubPaths makes statPath find exactly paths.
func stubPaths(t *testing.T, paths ...string) {
	t.Helper()
	old := statPath
	statPath = func(name string) (os.FileInfo, error) {
		if slices.Contains(paths, name) {
			return nil, nil
		}
		return nil, fs.ErrNotExist
	}
	t.Cleanup(func() { statPath = old })
}

// storcliReport is the shape storcli.py reads, with one controller of each kind of finding: a
// degraded VD, a failed and a rebuilding PD next to healthy ones, and a cache vault not optimal.
const storcliReport = `{"Controllers":[
 {"Command Status":{"Controller":0,"Status":"Success","Description":"None"},
  "Response Data":{
   "Basics":{"Controller":0,"Model":"X","Serial Number":"SV00000000"},
   "Status":{"Controller Status":"Optimal","BBU Status":"NA"},
   "VD LIST":[{"DG/VD":"0/0","TYPE":"RAID1","State":"Optl"},{"DG/VD":"1/1","TYPE":"RAID5","State":"Dgrd"}],
   "PD LIST":[{"EID:Slt":"252:0","State":"Onln"},{"EID:Slt":"252:1","State":"Failed"},
              {"EID:Slt":"252:2","State":"Rbld"},{"EID:Slt":"252:3","State":"GHS"},
              {"EID:Slt":"252:4","State":"UGood"},{"EID:Slt":"252:5","State":"JBOD"}],
   "Cachevault_Info":[{"Model":"CVPM02","State":"Degraded","Temp":"25C"}]}},
 {"Command Status":{"Controller":1,"Status":"Success"},
  "Response Data":{
   "Status":{"Controller Status":"Degraded","BBU Status":32},
   "VD LIST":[{"State":"Optl"}],"PD LIST":[{"State":"Onln"},{"State":"DHS"}]}}
]}`

func TestRaidCtrlCountsStorcliFindings(t *testing.T) {
	stubPaths(t, storcliPath)
	calls := stubTools(t, answer{out: storcliReport})
	got, err := raidCtrl(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]any{"controllers": 2, "ctrl_bad": 1, "vd_not_optimal": 1, "pd_failed": 2, "bbu_bad": 2}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("raid %v, want %v", got, want)
	}
	if want := [][]string{append([]string{storcliPath}, storcliArgs...)}; !reflect.DeepEqual(*calls, want) {
		t.Errorf("calls %q, want %q", *calls, want)
	}
}

func TestRaidCtrlTakesTheHealthyBatteryCodes(t *testing.T) {
	for _, bbu := range []string{`0`, `8`, `4096`, `"4096"`, `"NA"`} {
		stubPaths(t, storcliPath)
		stubTools(t, answer{out: `{"Controllers":[{"Command Status":{"Status":"Success"},"Response Data":` +
			`{"Status":{"Controller Status":"OK","BBU Status":` + bbu + `}}}]}`})
		got, err := raidCtrl(context.Background())
		if err != nil {
			t.Fatalf("%s: %v", bbu, err)
		}
		if got["bbu_bad"] != 0 || got["ctrl_bad"] != 0 {
			t.Errorf("%s: %v, want a healthy battery and controller", bbu, got)
		}
	}
}

func TestRaidCtrlRunsPerccliOnlyWithoutStorcli(t *testing.T) {
	healthy := `{"Controllers":[{"Command Status":{"Status":"Success"},"Response Data":{"Status":{"Controller Status":"Optimal"}}}]}`
	stubPaths(t, storcliPath, perccliPath)
	calls := stubTools(t, answer{out: healthy})
	if _, err := raidCtrl(context.Background()); err != nil {
		t.Fatal(err)
	}
	if len(*calls) != 1 || (*calls)[0][0] != storcliPath {
		t.Errorf("calls %q, want storcli alone", *calls)
	}
	stubPaths(t, perccliPath)
	calls = stubTools(t, answer{out: healthy})
	if _, err := raidCtrl(context.Background()); err != nil {
		t.Fatal(err)
	}
	if len(*calls) != 1 || (*calls)[0][0] != perccliPath {
		t.Errorf("calls %q, want perccli", *calls)
	}
}

const ssacliStatus = `
Smart Array P420i in Slot 0 (Embedded)
   Controller Status: OK
   Cache Status: OK
   Battery/Capacitor Status: Failed (Replace Batteries)

Smart Array P822 in Slot 2
   Controller Status: OK
   Cache Status: Not Configured
`

const ssacliConfig = `
Smart Array P420i in Slot 0 (Embedded)    (sn: 0014380000000000)

   Array A (SAS, Unused Space: 0  MB)

      logicaldrive 1 (279.37 GB, RAID 1, OK)

      physicaldrive 1I:2:1 (port 1I:box 2:bay 1, SAS HDD, 300 GB, OK)
      physicaldrive 1I:2:2 (port 1I:box 2:bay 2, SAS HDD, 300 GB, OK)

   Array B (SAS, Unused Space: 0  MB)

      logicaldrive 2 (558.7 GB, RAID 5, Interim Recovery Mode)

      physicaldrive 1I:2:3 (port 1I:box 2:bay 3, SAS HDD, 300 GB, Failed)
      physicaldrive 1I:2:4 (port 1I:box 2:bay 4, SAS HDD, 300 GB, OK)
      physicaldrive 1I:2:5 (port 1I:box 2:bay 5, SAS HDD, 300 GB, OK, spare)
`

func TestRaidCtrlCountsSsacliFindings(t *testing.T) {
	stubPaths(t, ssacliPath)
	calls := stubTools(t, answer{out: ssacliStatus}, answer{out: ssacliConfig})
	got, err := raidCtrl(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]any{"controllers": 2, "ctrl_bad": 0, "vd_not_optimal": 1, "pd_failed": 1, "bbu_bad": 1}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("raid %v, want %v", got, want)
	}
	if len(*calls) != 2 {
		t.Errorf("calls %q, want status and config", *calls)
	}
}

func TestRaidCtrlCountsASsacliControllerNotOk(t *testing.T) {
	stubPaths(t, ssacliPath)
	stubTools(t, answer{out: "Smart Array P420i in Slot 0 (Embedded)\n   Controller Status: Failed\n"}, answer{out: ""})
	got, err := raidCtrl(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if got["controllers"] != 1 || got["ctrl_bad"] != 1 {
		t.Errorf("raid %v, want one controller, counted bad", got)
	}
}

func TestRaidCtrlRejectsAnSsacliReportOfAnotherForm(t *testing.T) {
	for name, outs := range map[string][]answer{
		"no controller line": {{out: "Error: No controllers detected.\n"}},
		"a drive without parentheses": {
			{out: ssacliStatus}, {out: "      physicaldrive 1I:2:1 SV00000000 OK\n"},
		},
	} {
		stubPaths(t, ssacliPath)
		stubTools(t, outs...)
		_, err := raidCtrl(context.Background())
		if err == nil || strings.Contains(err.Error(), "SV0") {
			t.Errorf("%s: err %v, want an error without the drive line", name, err)
		}
	}
}

func TestRaidCtrlIsUnsupportedWithoutACli(t *testing.T) {
	stubPaths(t)
	calls := stubTools(t)
	if _, err := raidCtrl(context.Background()); !errors.Is(err, ErrUnsupported) {
		t.Errorf("err %v, want unsupported", err)
	}
	if len(*calls) != 0 {
		t.Errorf("ran %q", *calls)
	}
}

func TestRaidCtrlRejectsAReportOfAnotherFormWithoutASerial(t *testing.T) {
	for name, out := range map[string]string{
		"no json":       "CLI Version = 007.1\nController = 0\n",
		"no controller": `{"Controllers":[]}`,
		"a failed call": `{"Controllers":[{"Command Status":{"Status":"Failure","Description":"SV00000000 busy"}}]}`,
		"a bbu word":    `{"Controllers":[{"Command Status":{"Status":"Success"},"Response Data":{"Status":{"BBU Status":"Bad"}}}]}`,
	} {
		stubPaths(t, storcliPath)
		stubTools(t, answer{out: out})
		_, err := raidCtrl(context.Background())
		if err == nil || strings.Contains(err.Error(), "SV0") {
			t.Errorf("%s: err %v, want an error without the serial", name, err)
		}
	}
}

func TestRaidCtrlHidesWhatTheCliWrote(t *testing.T) {
	stubPaths(t, storcliPath)
	stubTools(t, answer{err: &exec.ExitError{Stderr: []byte("controller SV00000000 not found")}})
	_, err := raidCtrl(context.Background())
	if err == nil || strings.Contains(err.Error(), "SV0") {
		t.Errorf("err %v, want an error without the stderr line", err)
	}
}

func TestHardwareViewsTakeTurns(t *testing.T) {
	release, err := takeHwSlot(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	defer release()
	stubPaths(t, storcliPath)
	calls := stubTools(t)
	// The deadline is what this test checks: the waiting view ends with its probe, not with the slot.
	ctx, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
	defer cancel()
	if _, err := raidCtrl(ctx); !errors.Is(err, context.DeadlineExceeded) {
		t.Errorf("err %v, want the wait for the other view to end with the probe", err)
	}
	if len(*calls) != 0 {
		t.Errorf("ran %q while another view held the slot", *calls)
	}
}

// stubIpmi gives the IPMI view a device and a state directory of its own.
func stubIpmi(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	old := ipmiCacheDir
	ipmiCacheDir = func() string { return dir }
	t.Cleanup(func() { ipmiCacheDir = old })
	stubPaths(t, "/dev/ipmi0")
	return dir
}

// writeOnDump is a runTool that answers `sdr dump` by writing the file it names, and elist with out.
func writeOnDump(t *testing.T, out string, calls *[][]string) {
	t.Helper()
	old := runTool
	runTool = func(_ context.Context, _ time.Duration, name string, args ...string) ([]byte, error) {
		checkAllowed(t, name, args)
		*calls = append(*calls, append([]string{name}, args...))
		if len(args) == 3 && args[1] == "dump" {
			return nil, os.WriteFile(args[2], []byte("sdr"), 0o600)
		}
		return []byte(out), nil
	}
	t.Cleanup(func() { runTool = old })
}

// elist lines in the format of ipmi_sdr_print_sensor_fc: name | number | state | entity | reading.
const ipmiElist = `CPU Temp         | 30h | ok  |  3.1 | 40 degrees C
System Temp      | 31h | unc |  7.1 | 46 degrees C
FAN 1            | 41h | lcr | 29.1 | 300 RPM
FAN 2            | 42h | ns  | 29.2 | No Reading
PS1 Status       | C8h | ok  | 10.1 | Presence detected
Vcore            | 50h | cr  |  3.1 | 1.6 Volts
Watchdog         | 70h | ns  |  7.1 | Event-Only
`

func TestIpmiSensorsCountsStatesFromAFreshCache(t *testing.T) {
	dir := stubIpmi(t)
	var calls [][]string
	writeOnDump(t, ipmiElist, &calls)
	got, err := ipmiSensors(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if want := map[string]any{"sensors": 5, "critical": 2, "noncritical": 1}; !reflect.DeepEqual(got, want) {
		t.Errorf("ipmi %v, want %v", got, want)
	}
	cache := filepath.Join(dir, sdrCacheName)
	want := [][]string{{"ipmitool", "sdr", "dump", cache + ".new"}, {"ipmitool", "-S", cache, "sdr", "elist"}}
	if !reflect.DeepEqual(calls, want) {
		t.Errorf("calls %q, want %q", calls, want)
	}
	if _, err := os.Stat(cache + ".new"); !errors.Is(err, fs.ErrNotExist) {
		t.Errorf("the dump file stayed: %v", err)
	}
	// The next run takes the cache as it is.
	calls = nil
	if _, err := ipmiSensors(context.Background()); err != nil {
		t.Fatal(err)
	}
	if len(calls) != 1 || calls[0][1] != "-S" {
		t.Errorf("calls %q, want elist alone", calls)
	}
}

func TestIpmiSensorsDumpsAStaleCacheAnew(t *testing.T) {
	dir := stubIpmi(t)
	cache := filepath.Join(dir, sdrCacheName)
	if err := os.WriteFile(cache, []byte("old"), 0o600); err != nil {
		t.Fatal(err)
	}
	old := time.Now().Add(-sdrCacheMaxAge - time.Hour)
	if err := os.Chtimes(cache, old, old); err != nil {
		t.Fatal(err)
	}
	var calls [][]string
	writeOnDump(t, ipmiElist, &calls)
	if _, err := ipmiSensors(context.Background()); err != nil {
		t.Fatal(err)
	}
	if len(calls) != 2 || calls[0][2] != "dump" {
		t.Errorf("calls %q, want a dump first", calls)
	}
	if raw, _ := os.ReadFile(cache); string(raw) != "sdr" {
		t.Errorf("cache %q, want the new dump", raw)
	}
}

func TestIpmiSensorsRemovesAFailedDump(t *testing.T) {
	dir := stubIpmi(t)
	old := runTool
	runTool = func(_ context.Context, _ time.Duration, name string, args ...string) ([]byte, error) {
		checkAllowed(t, name, args)
		_ = os.WriteFile(args[2], []byte("half"), 0o600)
		return nil, &exec.ExitError{}
	}
	t.Cleanup(func() { runTool = old })
	if _, err := ipmiSensors(context.Background()); err == nil {
		t.Fatal("no error")
	}
	for _, name := range []string{sdrCacheName, sdrCacheName + ".new"} {
		if _, err := os.Stat(filepath.Join(dir, name)); !errors.Is(err, fs.ErrNotExist) {
			t.Errorf("%s stayed after a failed dump: %v", name, err)
		}
	}
}

func TestIpmiSensorsIsUnsupportedWithoutADevice(t *testing.T) {
	stubIpmi(t)
	stubPaths(t)
	calls := stubTools(t)
	if _, err := ipmiSensors(context.Background()); !errors.Is(err, ErrUnsupported) {
		t.Errorf("err %v, want unsupported", err)
	}
	if len(*calls) != 0 {
		t.Errorf("ran %q without a device", *calls)
	}
}

func TestIpmiSensorsRejectsALineOfAnotherFormWithoutTheSensorName(t *testing.T) {
	for name, out := range map[string]string{
		"a state":   "Secret Sensor    | 30h | weird |  3.1 | 40 degrees C\n",
		"no column": "Secret Sensor 40 degrees C\n",
	} {
		stubIpmi(t)
		var calls [][]string
		writeOnDump(t, out, &calls)
		_, err := ipmiSensors(context.Background())
		if err == nil || strings.Contains(err.Error(), "Secret") {
			t.Errorf("%s: err %v, want an error without the sensor name", name, err)
		}
	}
}

func TestTheHostSensorReadsTheHardwareViews(t *testing.T) {
	stubIpmi(t)
	var calls [][]string
	writeOnDump(t, ipmiElist, &calls)
	res := Run(context.Background(), hostProbe("ipmi_sensors", "critical"), time.Now(), nil)
	if res.Status != StatusOK || !reflect.DeepEqual(res.Values, map[string]any{"critical": 2}) {
		t.Errorf("ipmi: status %s (%s) values %v", res.Status, res.Error, res.Values)
	}
	stubPaths(t)
	if res := Run(context.Background(), hostProbe("raid_ctrl"), time.Now(), nil); res.Status != StatusUnsupported {
		t.Errorf("raid: status %s (%s), want unsupported", res.Status, res.Error)
	}
}
