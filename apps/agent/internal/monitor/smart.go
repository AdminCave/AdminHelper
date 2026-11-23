// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"context"
	"encoding/json"
	"fmt"
	"os/exec"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

// SmartAbsent is the smart_absent block: why the report carries no smart list.
type SmartAbsent struct {
	Reason string `json:"reason"`
}

// SmartDisk holds the SMART health data of a disk.
type SmartDisk struct {
	Device string `json:"device"`
	Model  string `json:"model"`
	Serial string `json:"serial"`
	// WWN in the form lsblk shows; left out when smartctl reports none. The monitoring service
	// keys the disk by it (ADR 0004 §4) and falls back to model + serial without it.
	WWN      string `json:"wwn,omitempty"`
	Protocol string `json:"protocol"` // "ATA" or "NVMe"
	Kind     string `json:"kind"`     // "HDD", "SATA-SSD" or "NVMe"
	// Standby: the disk slept (STANDBY or SLEEP) and was not queried, so every other field is empty;
	// the service keeps its last state (R-1569).
	Standby bool `json:"standby,omitempty"`
	// Nil when smartctl reported no smart_status (SMART disabled or unsupported): the
	// field is left out, so the service reads the health as unknown, not as failed.
	Passed   *bool `json:"smart_passed,omitempty"`
	TempC    int   `json:"temp_c"`
	PowerOnH int   `json:"power_on_hours"`

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
	// The goroutines finish in any order: list the disks by device, so two reports of one host agree.
	sort.Slice(disks, func(i, j int) bool { return disks[i].Device < disks[j].Device })

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

// smartStandbyStatus is the exit status smartctl ends with for a disk in STANDBY or SLEEP (-n
// standby,3). Odd and above 1, so no status of a query: bit 0 (the command line did not parse) comes alone.
const smartStandbyStatus = 3

func querySmartDevice(ctx context.Context, smartctl, device, devType, protocol string) *SmartDisk {
	// The scan type goes along as -d: some types only the scan knows (megaraid,N on /dev/bus/N, which
	// a query without -d cannot detect), the others it detects from the name as the query would. Not
	// scsi: the scan names every /dev/sdX without a USB bridge scsi without opening it, a SATA disk
	// too, and -d scsi switches off the SAT detection on open (smartmontools os_linux.cpp,
	// linux_scsi_device::autodetect_open), so the disk would come without its ATA attributes.
	args := []string{"--all", "--json=c"}
	nvme := strings.EqualFold(protocol, "NVMe") || devType == "nvme"
	if !nvme {
		// A query wakes a sleeping HDD (every report, R-1569); -n is for ATA and SCSI only (smartctl(8)).
		args = append(args, "-n", "standby,"+strconv.Itoa(smartStandbyStatus))
	}
	if devType != "" && devType != "scsi" {
		args = append(args, "-d", devType)
	}
	out, err := smartctlCLI.run(ctx, 30*time.Second, smartctl, append(args, device)...)

	// smartctl uses bit flags in the exit code. We keep the full code
	// so the server can evaluate bit 0x10 (prefail) as critical.
	exitCode := 0
	if err != nil {
		exitErr, ok := err.(*exec.ExitError)
		if ok && !nvme && exitErr.ExitCode() == smartStandbyStatus {
			// Only -n ends with this status: bit 0 (command line) never comes with another bit.
			return &SmartDisk{Device: device, Standby: true}
		}
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

	var passed *bool
	if raw.SmartStatus != nil {
		passed = &raw.SmartStatus.Passed
	}
	disk := &SmartDisk{
		Device:         device,
		Model:          raw.ModelName,
		Serial:         raw.SerialNumber,
		WWN:            smartWWN(&raw),
		Passed:         passed,
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
	// ATA world wide name, split as smartmontools ata_get_wwn: 4-bit NAA, 24-bit OUI, 36-bit ID.
	WWN *struct {
		NAA uint64 `json:"naa"`
		OUI uint64 `json:"oui"`
		ID  uint64 `json:"id"`
	} `json:"wwn"`
	// NVMe: smartctl prints eui64 per namespace only when it is not zero.
	NVMeNamespaces []struct {
		EUI64 *struct {
			OUI   uint64 `json:"oui"`
			ExtID uint64 `json:"ext_id"`
		} `json:"eui64"`
	} `json:"nvme_namespaces"`
	// SCSI/SAS: the logical unit id from VPD page 0x83, already as text.
	LogicalUnitID string `json:"logical_unit_id"`
	RotationRate  int    `json:"rotation_rate"`
	SmartStatus   *struct {
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

// maxWWNLen caps the SCSI logical unit id; the longest NAA form (IEEE Registered Extended) is
// 0x plus 32 hex digits.
const maxWWNLen = 64

// smartWWN renders the disk's world wide name as smartctl reports it: 0x plus 16 hex digits for ATA, eui. plus
// 16 hex digits (the EUI-64) for NVMe, the SCSI logical unit id as smartctl prints it. lsblk -o WWN looks alike, but
// on an NVMe disk with an NGUID it may show another id (not verified which one the kernel picks).
// Empty when smartctl reports no id, an all-zero one or an implausible SCSI text.
func smartWWN(raw *smartctlJSON) string {
	if w := raw.WWN; w != nil {
		v := (w.NAA&0xf)<<60 | (w.OUI&0xffffff)<<36 | w.ID&0xfffffffff
		if v != 0 {
			return fmt.Sprintf("0x%016x", v)
		}
	}
	if len(raw.NVMeNamespaces) > 0 {
		if e := raw.NVMeNamespaces[0].EUI64; e != nil {
			v := (e.OUI&0xffffff)<<40 | e.ExtID&0xffffffffff
			if v != 0 {
				return fmt.Sprintf("eui.%016x", v)
			}
		}
	}
	lu := strings.TrimSpace(raw.LogicalUnitID)
	if lu == "" || len(lu) > maxWWNLen {
		return ""
	}
	for _, r := range lu {
		if r <= ' ' || r > '~' {
			return ""
		}
	}
	return lu
}
