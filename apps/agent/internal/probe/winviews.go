// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"bytes"
	"encoding/csv"
	"encoding/xml"
	"errors"
	"fmt"
	"io"
	"math"
	"regexp"
	"strconv"
	"strings"
	"time"
)

// The Windows views of the app and host sensors. What they read comes from fixed queries
// (winread.go) or fixed read commands through the allowlist; the parsers here are portable,
// so the tests run everywhere. Every view reports counts, percentages, ages and booleans,
// never a name, an address or an event text.

var (
	errRepadminForm = errors.New("repadmin: unexpected output")
	errAppcmdForm   = errors.New("appcmd: unexpected output")
)

// repadminTimeLayout is how `repadmin /showrepl /csv` writes a time, in local time. Not
// verified on a domain controller: the column names and the layout come from Microsoft's
// repadmin documentation and published samples.
const repadminTimeLayout = "2006-01-02 15:04:05"

// repadminValues reads `repadmin /showrepl localhost /csv`: one row per inbound replication
// link (naming context × source DC), after a header row showrepl_COLUMNS. A link counts as
// failing with a nonzero "Number of Failures"; the age is that of the oldest last success
// over all links. A link that never succeeded has no time and counts as never.
func repadminValues(out []byte, now time.Time) (map[string]any, error) {
	r := csv.NewReader(bytes.NewReader(out))
	r.FieldsPerRecord = -1
	r.LazyQuotes = true
	cols := map[string]int{}
	partners := map[string]bool{}
	links, failing, never := 0, 0, 0
	var oldest time.Time
	for {
		rec, err := r.Read()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			return nil, errRepadminForm
		}
		switch strings.TrimSpace(rec[0]) {
		case "showrepl_COLUMNS":
			for i, name := range rec {
				cols[strings.TrimSpace(name)] = i
			}
		case "showrepl_INFO":
			src, okSrc := cols["Source DSA"]
			fail, okFail := cols["Number of Failures"]
			last, okLast := cols["Last Success Time"]
			if !okSrc || !okFail || !okLast || len(rec) <= max(src, fail, last) {
				return nil, errRepadminForm
			}
			n, err := strconv.Atoi(strings.TrimSpace(rec[fail]))
			if err != nil || n < 0 {
				return nil, errRepadminForm
			}
			links++
			partners[strings.ToLower(strings.TrimSpace(rec[src]))] = true
			if n > 0 {
				failing++
			}
			at, err := time.ParseInLocation(repadminTimeLayout, strings.TrimSpace(rec[last]), time.Local)
			if err != nil || at.Year() < 1700 {
				never++
				continue
			}
			if oldest.IsZero() || at.Before(oldest) {
				oldest = at
			}
		}
	}
	if len(cols) == 0 {
		return nil, errRepadminForm
	}
	values := map[string]any{
		"partners":      len(partners),
		"links":         links,
		"failing_links": failing,
		"never_links":   never,
	}
	if !oldest.IsZero() {
		values["oldest_success_age_s"] = max(0, int64(now.Sub(oldest)/time.Second))
	}
	return values, nil
}

// appcmdStopped counts the elements of `appcmd list site|apppool /xml` and those whose
// state is not "Started" (Stopped, Starting, Stopping, Unknown). Not verified on IIS: the
// element names SITE and APPPOOL and the attribute state come from Microsoft's appcmd
// documentation.
func appcmdStopped(out []byte, element string) (total, stopped int, err error) {
	d := xml.NewDecoder(bytes.NewReader(out))
	root := false
	for {
		tok, err := d.Token()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			return 0, 0, errAppcmdForm
		}
		se, ok := tok.(xml.StartElement)
		if !ok {
			continue
		}
		switch se.Name.Local {
		case "appcmd":
			root = true
		case element:
			total++
			state := ""
			for _, a := range se.Attr {
				if a.Name.Local == "state" {
					state = a.Value
				}
			}
			if state != "Started" {
				stopped++
			}
		}
	}
	if !root {
		return 0, 0, errAppcmdForm
	}
	return total, stopped, nil
}

// dhcpScope is one row of PS_DhcpServerv4ScopeStatistics (root/Microsoft/Windows/DHCP).
// Not verified on a DHCP server: that the class answers a plain WQL enumeration.
type dhcpScope struct {
	InUse uint32
	Free  uint32
}

// dhcpValues reports the fullest scope and the scopes over 80 and 95 per cent in use.
// A server without a scope reports only the count: its rules then have no value and the
// check is unknown, not a silent ok (R-1465).
func dhcpValues(scopes []dhcpScope) map[string]any {
	if len(scopes) == 0 {
		return map[string]any{"scopes": 0}
	}
	maxPct := 0.0
	over80, over95 := 0, 0
	for _, s := range scopes {
		size := float64(s.InUse) + float64(s.Free)
		if size == 0 {
			continue
		}
		pct := 100 * float64(s.InUse) / size
		maxPct = max(maxPct, pct)
		if pct >= 80 {
			over80++
		}
		if pct >= 95 {
			over95++
		}
	}
	return map[string]any{
		"scopes":         len(scopes),
		"max_used_pct":   math.Round(maxPct*10) / 10,
		"scopes_over_80": over80,
		"scopes_over_95": over95,
	}
}

// rdsPack is one row of Win32_TSLicenseKeyPack (root\cimv2) on a license server.
type rdsPack struct {
	TotalLicenses  uint32
	IssuedLicenses uint32
	ExpirationDate time.Time
}

// rdsUnlimited marks a built-in pack without a count. Not verified on a license server.
const rdsUnlimited = math.MaxUint32

// rdsNoExpiry: a permanent pack carries an expiration far in the future (2038 in the
// samples). Not verified on a license server.
var rdsNoExpiry = time.Date(2038, 1, 1, 0, 0, 0, 0, time.UTC)

// rdsValues sums the counted packs and reports the days to the nearest expiry.
func rdsValues(packs []rdsPack, now time.Time) map[string]any {
	var total, issued uint64
	daysLeft := -1
	for _, p := range packs {
		if p.TotalLicenses != rdsUnlimited {
			total += uint64(p.TotalLicenses)
			issued += uint64(p.IssuedLicenses)
		}
		if p.ExpirationDate.IsZero() || !p.ExpirationDate.Before(rdsNoExpiry) {
			continue
		}
		d := int(p.ExpirationDate.Sub(now).Hours() / 24)
		if daysLeft < 0 || d < daysLeft {
			daysLeft = max(d, 0)
		}
	}
	values := map[string]any{"licenses_total": total, "licenses_issued": issued}
	if total > 0 {
		values["used_pct"] = math.Round(1000*float64(issued)/float64(total)) / 10
	}
	if daysLeft >= 0 {
		values["min_days_left"] = daysLeft
	}
	return values
}

// wuaState is what the Windows Update Agent answers: the open updates of the last offline
// search, how many of them carry an MSRC severity of Critical or Important, whether a
// reboot is pending, and when Windows Update last searched successfully on its own.
type wuaState struct {
	open, security int
	reboot         bool
	lastSearch     time.Time
}

func (s wuaState) values(now time.Time) map[string]any {
	values := map[string]any{
		"updates_open":     s.open,
		"updates_security": s.security,
		"reboot_required":  s.reboot,
	}
	if !s.lastSearch.IsZero() {
		values["search_age_s"] = max(0, int64(now.Sub(s.lastSearch)/time.Second))
	}
	return values
}

// wuaSecurity reports whether an MSRC severity is one of a security update that matters.
func wuaSecurity(severity string) bool {
	return severity == "Critical" || severity == "Important"
}

// winEventsWindow is how far back win_events counts: the probe's interval, so each run
// counts the events since the one before; an hour without one, at most a day.
func winEventsWindow(intervalS int) time.Duration {
	if intervalS <= 0 {
		return time.Hour
	}
	return min(time.Duration(intervalS)*time.Second, 24*time.Hour)
}

// machineCertValues reports the certificates of LocalMachine\My: how many, how many expired, and
// the days left of the one that expires next among the others.
func machineCertValues(notAfter []time.Time, now time.Time) map[string]any {
	expired := 0
	daysLeft := -1
	for _, at := range notAfter {
		if !at.After(now) {
			expired++
			continue
		}
		d := int(at.Sub(now).Hours() / 24)
		if daysLeft < 0 || d < daysLeft {
			daysLeft = d
		}
	}
	values := map[string]any{"certs": len(notAfter), "expired": expired}
	if daysLeft >= 0 {
		values["min_days_left"] = daysLeft
	}
	return values
}

// appEventsWindow is how far back the app views count events: they take no interval, so a
// day, the field names say so (_24h).
const appEventsWindow = 24 * time.Hour

// hypervVM is one row of Msvm_ComputerSystem (root\virtualization\v2). A VM's Name is its
// GUID, the host's own row carries the computer name: the GUID tells them apart without the
// Caption, whose text may be localized. The Name stays on this host.
type hypervVM struct {
	Name              string
	EnabledState      uint16 // 2 Enabled (running), 3 Disabled, 32768 Paused, 32769 Suspended
	HealthState       uint16 // 5 OK, 20 Major Failure, 25 Critical Failure
	ReplicationHealth uint16 // 0 not applicable, 1 Ok, 2 Warning, 3 Critical
}

// hypervHeartbeat is one row of Msvm_HeartbeatComponent: OperationalStatus[0] 2 OK,
// 3 Degraded, 7 Non-Recoverable Error, 12 No Contact (not installed or not yet reached),
// 13 Lost Communication, 15 Paused.
type hypervHeartbeat struct {
	OperationalStatus []uint16
}

// hypervSetting is one row of Msvm_VirtualSystemSettingData: a VM's settings, or a
// checkpoint with VirtualSystemType Microsoft:Hyper-V:Snapshot:Realized.
type hypervSetting struct {
	VirtualSystemType string
	CreationTime      time.Time
}

const hypervCheckpoint = "Microsoft:Hyper-V:Snapshot:Realized"

var hypervGUIDRe = regexp.MustCompile(`^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$`)

// hypervValues counts the VMs, those running, those whose health is a failure, the
// heartbeats lost (No Contact is no loss: a VM without integration services never had one),
// the replicas in warning and critical, and the checkpoints with the age of the oldest.
func hypervValues(vms []hypervVM, beats []hypervHeartbeat, settings []hypervSetting, now time.Time) map[string]any {
	guests, running, unhealthy, replWarn, replCrit := 0, 0, 0, 0, 0
	for _, vm := range vms {
		if !hypervGUIDRe.MatchString(vm.Name) {
			continue
		}
		guests++
		if vm.EnabledState == 2 {
			running++
		}
		if vm.HealthState == 20 || vm.HealthState == 25 {
			unhealthy++
		}
		switch vm.ReplicationHealth {
		case 2:
			replWarn++
		case 3:
			replCrit++
		}
	}
	lost := 0
	for _, b := range beats {
		if len(b.OperationalStatus) > 0 && (b.OperationalStatus[0] == 7 || b.OperationalStatus[0] == 13) {
			lost++
		}
	}
	checkpoints := 0
	var oldest time.Time
	for _, s := range settings {
		if s.VirtualSystemType != hypervCheckpoint {
			continue
		}
		checkpoints++
		if !s.CreationTime.IsZero() && (oldest.IsZero() || s.CreationTime.Before(oldest)) {
			oldest = s.CreationTime
		}
	}
	values := map[string]any{
		"vms":                  guests,
		"vms_running":          running,
		"vms_unhealthy":        unhealthy,
		"heartbeat_lost":       lost,
		"replication_warning":  replWarn,
		"replication_critical": replCrit,
		"checkpoints":          checkpoints,
	}
	if !oldest.IsZero() {
		values["oldest_checkpoint_age_s"] = max(0, int64(now.Sub(oldest)/time.Second))
	}
	return values
}

// dfsrFolder is one row of DfsrReplicatedFolderInfo (root\MicrosoftDfs): State 0
// Uninitialized, 1 Initialized, 2 Initial Sync, 3 Auto Recovery, 4 Normal, 5 In Error.
type dfsrFolder struct {
	State uint32
}

// dfsrValues counts the replicated folders, those in error and those not (yet) in normal
// operation, with the day's events 2213 (replication stopped after an unclean shutdown,
// waits for a manual resume) and 4012 (the member was offline longer than allowed).
func dfsrValues(folders []dfsrFolder, stopped, stale int) map[string]any {
	inError, notNormal := 0, 0
	for _, f := range folders {
		if f.State == 5 {
			inError++
		}
		if f.State != 4 {
			notNormal++
		}
	}
	return map[string]any{
		"folders":              len(folders),
		"folders_error":        inError,
		"folders_not_normal":   notNormal,
		"stopped_events_24h":   stopped,
		"offline_too_long_24h": stale,
	}
}

// storageDisk is one row of MSFT_PhysicalDisk or MSFT_VirtualDisk
// (root\Microsoft\Windows\Storage). Not verified: HealthStatus 0 Healthy, 1 Warning,
// 2 Unhealthy, 5 Unknown.
type storageDisk struct {
	HealthStatus uint16
}

// fsrmQuota is one row of MSFT_FSRMQuota (root\Microsoft\Windows\FSRM): limit and use, in
// the same unit.
type fsrmQuota struct {
	Size  uint64
	Usage uint64
}

// shadowCopy is one row of Win32_ShadowCopy; InstallDate is when it was taken (not verified).
type shadowCopy struct {
	InstallDate time.Time
}

// encVolume is one row of Win32_EncryptableVolume (root\CIMV2\Security\
// MicrosoftVolumeEncryption): ProtectionStatus 0 off, 1 on, 2 unknown; VolumeType 0 the
// system volume, 1 a fixed data volume, 2 a removable one. Never a key protector.
type encVolume struct {
	ProtectionStatus uint32
	VolumeType       uint32
}

// storageState is what the storage view could read; a part whose role or feature the host
// lacks (Storage Spaces, FSRM, BitLocker) is left out, not counted as zero.
type storageState struct {
	physical, virtual               []storageDisk
	quotas                          []fsrmQuota
	shadows                         []shadowCopy
	volumes                         []encVolume
	hasDisks, hasQuotas, hasVolumes bool
}

func storageValues(s storageState, now time.Time) map[string]any {
	unhealthy := func(disks []storageDisk) int {
		n := 0
		for _, d := range disks {
			if d.HealthStatus == 1 || d.HealthStatus == 2 {
				n++
			}
		}
		return n
	}
	values := map[string]any{"shadow_copies": len(s.shadows)}
	var newest time.Time
	for _, c := range s.shadows {
		if c.InstallDate.After(newest) {
			newest = c.InstallDate
		}
	}
	if !newest.IsZero() {
		values["newest_shadow_age_s"] = max(0, int64(now.Sub(newest)/time.Second))
	}
	if s.hasDisks {
		values["disks"], values["disks_unhealthy"] = len(s.physical), unhealthy(s.physical)
		values["vdisks"], values["vdisks_unhealthy"] = len(s.virtual), unhealthy(s.virtual)
	}
	if s.hasQuotas {
		over := 0
		for _, q := range s.quotas {
			if q.Size > 0 && float64(q.Usage) >= 0.9*float64(q.Size) {
				over++
			}
		}
		values["quotas"], values["quotas_over_90"] = len(s.quotas), over
	}
	if s.hasVolumes {
		fixed, unprotected := 0, 0
		for _, v := range s.volumes {
			if v.VolumeType > 1 {
				continue
			}
			fixed++
			if v.ProtectionStatus != 1 {
				unprotected++
			}
		}
		values["volumes"], values["volumes_unprotected"] = fixed, unprotected
	}
	return values
}

// printJob is one row of Win32_PrintJob.
type printJob struct {
	StatusMask    uint32
	TimeSubmitted time.Time
}

// printer is one row of Win32_Printer.
type printer struct {
	DetectedErrorState    uint16
	ExtendedPrinterStatus uint16
	WorkOffline           bool
}

// printJobFault: the StatusMask bits Error (2), Offline (32), Paper Out (64), Blocked_DevQ
// (512) and User Intervention Required (1024).
const printJobFault = 2 | 32 | 64 | 512 | 1024

// printerFault reports a printer that cannot print: DetectedErrorState No Paper (4), No
// Toner (6), Door Open (7), Jammed (8), Offline (9), Service Requested (10), Output Bin
// Full (11); ExtendedPrinterStatus Offline (7) or Error (9); or set to work offline. Low
// paper and low toner still print.
func printerFault(p printer) bool {
	switch p.DetectedErrorState {
	case 4, 6, 7, 8, 9, 10, 11:
		return true
	}
	return p.ExtendedPrinterStatus == 7 || p.ExtendedPrinterStatus == 9 || p.WorkOffline
}

func printValues(printers []printer, jobs []printJob, now time.Time) map[string]any {
	faulty := 0
	for _, p := range printers {
		if printerFault(p) {
			faulty++
		}
	}
	jobsFaulty := 0
	var oldest time.Time
	for _, j := range jobs {
		if j.StatusMask&printJobFault != 0 {
			jobsFaulty++
		}
		if !j.TimeSubmitted.IsZero() && (oldest.IsZero() || j.TimeSubmitted.Before(oldest)) {
			oldest = j.TimeSubmitted
		}
	}
	values := map[string]any{
		"printers":       len(printers),
		"printers_error": faulty,
		"jobs":           len(jobs),
		"jobs_error":     jobsFaulty,
	}
	if !oldest.IsZero() {
		values["oldest_job_age_s"] = max(0, int64(now.Sub(oldest)/time.Second))
	}
	return values
}

// mpStatus is the one row of MSFT_MpComputerStatus (root\Microsoft\Windows\Defender).
type mpStatus struct {
	RealTimeProtectionEnabled bool
	AntivirusEnabled          bool
	AntivirusSignatureAge     uint32 // days; 65535 when the signatures were never updated
}

// mpMode is AMRunningMode, asked apart: older Defender versions lack the property, and a
// query naming it would fail as a whole. Not verified: "Normal", "Passive Mode", "SxS
// Passive Mode", "EDR Block Mode".
type mpMode struct {
	AMRunningMode string
}

// mpThreat is one row of MSFT_MpThreatDetection.
type mpThreat struct {
	InitialDetectionTime time.Time
}

const mpSignatureNever = 65535

func defenderValues(s mpStatus, mode string, threats []mpThreat, now time.Time) map[string]any {
	recent := 0
	for _, t := range threats {
		if !t.InitialDetectionTime.IsZero() && now.Sub(t.InitialDetectionTime) <= appEventsWindow {
			recent++
		}
	}
	values := map[string]any{
		"realtime_on":    s.RealTimeProtectionEnabled,
		"antivirus_on":   s.AntivirusEnabled,
		"detections_24h": recent,
	}
	// Never updated (65535) goes out as that age: the >= 4 days rule rates it critical (R-1481).
	values["signature_age_d"] = int(s.AntivirusSignatureAge)
	if mode != "" {
		values["passive"] = strings.Contains(mode, "Passive")
	}
	return values
}

// mssqlServiceRe is the service of an SQL Server instance: MSSQLSERVER for the default
// one, MSSQL$<instance> for a named one. Its name is the source of its events in the
// Application log (not verified on a SQL Server).
var mssqlServiceRe = regexp.MustCompile(`^MSSQL(SERVER|\$[A-Za-z0-9_]{1,16})$`)

// mssqlSource returns the event source of the SQL Server instance the target unit names.
func mssqlSource(unit string) (string, error) {
	name := strings.TrimSuffix(unit, ".service")
	if !mssqlServiceRe.MatchString(name) {
		return "", fmt.Errorf("%w: %q is no SQL Server service", ErrInvalid, unit)
	}
	return name, nil
}

// freeValues reports the free space of the volume a directory is on.
func freeValues(free, total uint64) map[string]any {
	values := map[string]any{"content_free_bytes": free}
	if total > 0 {
		values["content_free_pct"] = math.Round(1000*float64(free)/float64(total)) / 10
	}
	return values
}

// winBackupValues reports the age of the newest successful backup, whether the newest finished
// one failed, and the day's failures. A host that never backed up successfully has no age.
func winBackupValues(lastSuccess time.Time, lastFailed bool, failures int, now time.Time) map[string]any {
	values := map[string]any{"last_failed": lastFailed, "failures_24h": failures}
	if !lastSuccess.IsZero() {
		values["last_success_age_s"] = max(0, int64(now.Sub(lastSuccess)/time.Second))
	}
	return values
}

// veeamWindowsValues reports the age and the result of the newest job end: information is
// success, warning a warning, error or critical a failure. Without one, only runs 0.
func veeamWindowsValues(found bool, at time.Time, level uint8, now time.Time) map[string]any {
	if !found {
		return map[string]any{"runs": 0}
	}
	result := "success"
	switch level {
	case 1, 2:
		result = "failed"
	case 3:
		result = "warning"
	}
	values := map[string]any{"runs": 1, "last_result": result}
	if !at.IsZero() {
		values["last_run_age_s"] = max(0, int64(now.Sub(at)/time.Second))
	}
	return values
}
