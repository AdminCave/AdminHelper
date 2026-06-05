// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"context"
	"encoding/json"
	"os/exec"
	"strings"
	"time"
)

// SmartDisk holds the SMART health data of a disk.
type SmartDisk struct {
	Device   string `json:"device"`
	Model    string `json:"model"`
	Serial   string `json:"serial"`
	Protocol string `json:"protocol"` // "ATA" or "NVMe"
	Kind     string `json:"kind"`     // "HDD", "SATA-SSD" or "NVMe"
	Passed   bool   `json:"smart_passed"`
	TempC    int    `json:"temp_c"`
	PowerOnH int    `json:"power_on_hours"`

	// smartctl exit code (bit flags). 0 = all ok.
	SmartctlStatus int `json:"smartctl_status"`

	// ATA-specific (SSDs + HDDs)
	ReallocatedSectors int `json:"reallocated_sectors"`
	SpinRetryCount     int `json:"spin_retry_count"`
	ReallocationEvents int `json:"reallocation_events"`
	PendingSectors     int `json:"pending_sectors"`
	Uncorrectable      int `json:"uncorrectable"`
	ReportedUncorrect  int `json:"reported_uncorrect"`
	UDMACRCErrors      int `json:"udma_crc_errors"`

	// NVMe-specific
	AvailableSparePct int `json:"available_spare_pct,omitempty"`
	PercentageUsed    int `json:"percentage_used,omitempty"`
	MediaErrors       int `json:"media_errors,omitempty"`
	CriticalWarning   int `json:"critical_warning,omitempty"`
}

// collectSmart collects SMART data of all detected devices via smartctl.
// Returns nil if smartctl is not installed (e.g. on VMs).
func collectSmart() []SmartDisk {
	smartctl, err := exec.LookPath("smartctl")
	if err != nil {
		return nil
	}

	// Scan all SMART-capable devices (with a timeout in case the controller hangs)
	ctxScan, cancelScan := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancelScan()
	scanOut, err := exec.CommandContext(ctxScan, smartctl, "--scan", "--json=c").Output()
	if err != nil {
		return nil
	}

	var scanResult struct {
		Devices []struct {
			Name     string `json:"name"`
			InfoName string `json:"info_name"`
			Protocol string `json:"protocol"`
		} `json:"devices"`
	}
	if json.Unmarshal(scanOut, &scanResult) != nil || len(scanResult.Devices) == 0 {
		return nil
	}

	var disks []SmartDisk
	for _, dev := range scanResult.Devices {
		disk := querySmartDevice(smartctl, dev.Name, dev.Protocol)
		if disk != nil {
			disks = append(disks, *disk)
		}
	}

	if len(disks) == 0 {
		return nil
	}
	return disks
}

func querySmartDevice(smartctl, device, protocol string) *SmartDisk {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, smartctl, "--all", "--json=c", device)
	out, err := cmd.Output()

	// smartctl uses bit flags in the exit code. We keep the full code
	// so the server can evaluate bit 0x10 (prefail) as critical.
	exitCode := 0
	if err != nil {
		// Bits 0-2 (1,2,4) = real errors (CLI/device/command)
		// Bits 3-7 (8+)    = warnings, JSON is still usable
		if exitErr, ok := err.(*exec.ExitError); ok {
			exitCode = exitErr.ExitCode()
			if exitCode&0x07 != 0 && len(out) == 0 {
				return nil
			}
		} else {
			return nil
		}
		if len(out) == 0 {
			return nil
		}
	}

	var raw smartctlJSON
	if json.Unmarshal(out, &raw) != nil {
		return nil
	}

	disk := &SmartDisk{
		Device:         device,
		Model:          raw.ModelName,
		Serial:         raw.SerialNumber,
		Passed:         raw.SmartStatus.Passed,
		TempC:          raw.Temperature.Current,
		PowerOnH:       raw.PowerOnTime.Hours,
		SmartctlStatus: exitCode,
	}

	// Determine the protocol from the smartctl output
	proto := strings.ToUpper(raw.Device.Protocol)
	if proto == "" {
		proto = strings.ToUpper(protocol)
	}

	if proto == "NVME" {
		disk.Protocol = "NVMe"
		parseNVMeHealth(disk, &raw)
	} else {
		disk.Protocol = "ATA"
		parseATAHealth(disk, &raw)
	}

	disk.Kind = determineKind(disk.Protocol, raw.RotationRate)
	return disk
}

// determineKind classifies the disk by protocol + rotation rate.
// smartctl returns rotation_rate=0 for SSDs, >0 (RPM) for HDDs.
func determineKind(protocol string, rotationRate int) string {
	if protocol == "NVMe" {
		return "NVMe"
	}
	if rotationRate == 0 {
		return "SATA-SSD"
	}
	return "HDD"
}

func parseATAHealth(disk *SmartDisk, raw *smartctlJSON) {
	for _, attr := range raw.ATASmartAttributes.Table {
		rawVal := attr.Raw.Value
		switch attr.ID {
		case 5:
			disk.ReallocatedSectors = rawVal
		case 10:
			disk.SpinRetryCount = rawVal
		case 187:
			disk.ReportedUncorrect = rawVal
		case 196:
			disk.ReallocationEvents = rawVal
		case 197:
			disk.PendingSectors = rawVal
		case 198:
			disk.Uncorrectable = rawVal
		case 199:
			disk.UDMACRCErrors = rawVal
		}
	}
}

func parseNVMeHealth(disk *SmartDisk, raw *smartctlJSON) {
	nvme := raw.NVMeHealth
	disk.AvailableSparePct = nvme.AvailableSpare
	disk.PercentageUsed = nvme.PercentageUsed
	disk.MediaErrors = nvme.MediaErrors
	disk.CriticalWarning = nvme.CriticalWarning
}

// smartctlJSON maps the relevant fields of the smartctl --json=c output.
type smartctlJSON struct {
	Device struct {
		Protocol string `json:"protocol"`
	} `json:"device"`
	ModelName    string `json:"model_name"`
	SerialNumber string `json:"serial_number"`
	RotationRate int    `json:"rotation_rate"`
	SmartStatus  struct {
		Passed bool `json:"passed"`
	} `json:"smart_status"`
	Temperature struct {
		Current int `json:"current"`
	} `json:"temperature"`
	PowerOnTime struct {
		Hours int `json:"hours"`
	} `json:"power_on_time"`

	// ATA
	ATASmartAttributes struct {
		Table []struct {
			ID  int `json:"id"`
			Raw struct {
				Value int `json:"value"`
			} `json:"raw"`
		} `json:"table"`
	} `json:"ata_smart_attributes"`

	// NVMe
	NVMeHealth struct {
		AvailableSpare  int `json:"available_spare"`
		PercentageUsed  int `json:"percentage_used"`
		MediaErrors     int `json:"media_and_data_integrity_errors"`
		CriticalWarning int `json:"critical_warning"`
	} `json:"nvme_smart_health_information_log"`
}
