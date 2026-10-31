// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"context"
	"encoding/json"
	"os/exec"
	"strings"
	"sync"
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

	// NVMe-specific. NO omitempty: a critical 0 (e.g. available_spare=0 =
	// spare exhausted) must stay in the JSON so the server can tell it apart
	// from "never reported". The protocol field keeps ATA/NVMe distinguishable.
	AvailableSparePct int `json:"available_spare_pct"`
	PercentageUsed    int `json:"percentage_used"`
	MediaErrors       int `json:"media_errors"`
	CriticalWarning   int `json:"critical_warning"`
}

// smartctlCLI indirects collectSmart's smartctl lookup and calls so tests can drive every path without
// smartctl (same reason as dockerCLI).
var smartctlCLI = struct {
	lookPath func(file string) (string, error)
	run      func(ctx context.Context, timeout time.Duration, name string, args ...string) ([]byte, error)
}{exec.LookPath, runTimed}

// collectSmart collects SMART data of all detected devices via smartctl. Without a single disk it
// returns why instead, which the report sends as smart_absent, so a host without smartctl does not
// pass for one without disks: not_installed (no smartctl, e.g. on VMs), scan_failed (the scan failed,
// hung or printed no JSON, or no device it found gave readable SMART data) or no_devices (the scan
// found none). ctx ends every smartctl call; once it has ended, no further device is queried, and the
// disks read before stay in the result.
func collectSmart(ctx context.Context) ([]SmartDisk, string) {
	smartctl, err := smartctlCLI.lookPath("smartctl")
	if err != nil {
		return nil, "not_installed"
	}

	// Scan all SMART-capable devices (with a timeout in case the controller hangs)
	scanOut, err := smartctlCLI.run(ctx, 15*time.Second, smartctl, "--scan", "--json=c")
	if err != nil {
		return nil, "scan_failed"
	}

	var scanResult struct {
		Devices []struct {
			Name     string `json:"name"`
			InfoName string `json:"info_name"`
			Type     string `json:"type"`
			Protocol string `json:"protocol"`
		} `json:"devices"`
	}
	if json.Unmarshal(scanOut, &scanResult) != nil {
		return nil, "scan_failed"
	}
	if len(scanResult.Devices) == 0 {
		return nil, "no_devices"
	}

	// Query devices in parallel: querySmartDevice has a 30s per-device timeout, so a serial loop
	// over an 8-disk NAS with a couple of sluggish drives can blow the oneshot run's 60s budget and
	// get killed by systemd. The smartctl calls are independent (5.8).
	var (
		mu    sync.Mutex
		wg    sync.WaitGroup
		disks []SmartDisk
	)
	for _, dev := range scanResult.Devices {
		if ctx.Err() != nil {
			break
		}
		wg.Add(1)
		go func(name, id, devType, proto string) {
			defer wg.Done()
			if d := querySmartDevice(ctx, smartctl, name, devType, proto); d != nil {
				d.Device = id
				mu.Lock()
				disks = append(disks, *d)
				mu.Unlock()
			}
		}(dev.Name, smartDiskID(dev.Name, dev.InfoName, dev.Type), dev.Type, dev.Protocol)
	}
	wg.Wait()

	if len(disks) == 0 {
		// querySmartDevice drops only a query without usable JSON (did not start, hung, no or
		// unreadable output, or exit bit 0 or 1: smartctl did not parse its command line or could not
		// open the device), so no disk at all is a failed read, not a host without devices.
		return nil, "scan_failed"
	}
	return disks, ""
}

// smartDiskID names a disk in the report. The scan names all disks behind a MegaRAID or sssraid
// controller like the controller (/dev/bus/N, /dev/bsg/sssraidN), and only its info_name tells them
// apart (smartmontools os_linux.cpp: "/dev/bus/0 [megaraid_disk_00]"); the service names the disk's
// metrics after it and matches ignore_devices against it. The scan's, not the query's: opening the
// device appends " [SAT]" when smartctl finds a SATA disk behind the controller. Every other disk
// keeps its name, without a suffix such as [SAT].
func smartDiskID(name, infoName, devType string) string {
	if infoName != "" && (strings.HasPrefix(devType, "megaraid,") || strings.HasPrefix(devType, "sssraid,")) {
		return infoName
	}
	return name
}

func querySmartDevice(ctx context.Context, smartctl, device, devType, protocol string) *SmartDisk {
	// The scan type goes along as -d: some types only the scan knows (megaraid,N on /dev/bus/N, which
	// a query without -d cannot detect), the others it detects from the name as the query would. Not
	// scsi: the scan names every /dev/sdX without a USB bridge scsi without opening it, a SATA disk
	// too, and -d scsi switches off the SAT detection on open (smartmontools os_linux.cpp,
	// linux_scsi_device::autodetect_open), so the disk would come without its ATA attributes.
	args := []string{"--all", "--json=c"}
	if devType != "" && devType != "scsi" {
		args = append(args, "-d", devType)
	}
	out, err := smartctlCLI.run(ctx, 30*time.Second, smartctl, append(args, device)...)

	// smartctl uses bit flags in the exit code. We keep the full code
	// so the server can evaluate bit 0x10 (prefail) as critical.
	exitCode := 0
	if err != nil {
		exitErr, ok := err.(*exec.ExitError)
		if !ok || len(out) == 0 {
			return nil // no usable JSON
		}
		exitCode = exitErr.ExitCode()
		// smartctl(8), EXIT STATUS: bit 0 (1) = command line did not parse, bit 1 (2) = device open
		// failed. smartctl read nothing then, and its JSON without smart_status would pass for a
		// failed SMART check, so the disk drops out. Bits 2-7 come with the data it read: the disk
		// stays with the full exit code.
		if exitCode&0x03 != 0 {
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
