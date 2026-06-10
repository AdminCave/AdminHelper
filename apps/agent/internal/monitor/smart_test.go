// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"encoding/json"
	"testing"
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
