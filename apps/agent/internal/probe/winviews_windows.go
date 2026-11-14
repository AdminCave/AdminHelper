// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package probe

import (
	"context"
	"errors"
	"fmt"
	"path/filepath"
	"runtime"
	"time"

	"github.com/go-ole/go-ole"
	"github.com/go-ole/go-ole/oleutil"
	"golang.org/x/sys/windows"
	"golang.org/x/sys/windows/registry"
)

// adReplication reads the inbound replication links of this domain controller alone
// (`repadmin /showrepl localhost /csv`, never `*`).
func adReplication(ctx context.Context, _ Target) (map[string]any, error) {
	out, err := runAppTool(ctx, "repadmin", "/showrepl", "localhost", "/csv")
	if err != nil {
		return nil, err
	}
	return repadminValues(out, time.Now())
}

// dhcpScopes reads the address use of the IPv4 scopes of this DHCP server.
func dhcpScopes(ctx context.Context, _ Target) (map[string]any, error) {
	var scopes []dhcpScope
	q := wmiQuery{namespace: `root\Microsoft\Windows\DHCP`, class: "PS_DhcpServerv4ScopeStatistics"}
	if err := q.run(ctx, &scopes); err != nil {
		return nil, err
	}
	return dhcpValues(scopes), nil
}

// appcmdPath is appcmd.exe of IIS, which is not on the PATH: %windir%\system32\inetsrv.
func appcmdPath() (string, error) {
	dir, err := windows.GetSystemDirectory()
	if err != nil {
		return "", err
	}
	return filepath.Join(dir, "inetsrv", "appcmd.exe"), nil
}

// iisState counts the sites and application pools of IIS that are not started.
func iisState(ctx context.Context, _ Target) (map[string]any, error) {
	appcmd, err := appcmdPath()
	if err != nil {
		return nil, err
	}
	values := map[string]any{}
	for _, list := range []struct{ object, element, total, stopped string }{
		{"site", "SITE", "sites", "sites_stopped"},
		{"apppool", "APPPOOL", "pools", "pools_stopped"},
	} {
		out, err := runAppTool(ctx, appcmd, "list", list.object, "/xml")
		if err != nil {
			return nil, err
		}
		total, stopped, err := appcmdStopped(out, list.element)
		if err != nil {
			return nil, err
		}
		values[list.total], values[list.stopped] = total, stopped
	}
	return values, nil
}

// rdsLicenses reads the license packs of this RD license server.
func rdsLicenses(ctx context.Context, _ Target) (map[string]any, error) {
	var packs []rdsPack
	q := wmiQuery{namespace: `root\cimv2`, class: "Win32_TSLicenseKeyPack"}
	if err := q.run(ctx, &packs); err != nil {
		return nil, err
	}
	return rdsValues(packs, time.Now()), nil
}

// winUpdates asks the Windows Update Agent for the open updates, offline: the search reads
// the agent's own catalog and contacts no update server (Online=false). Read only: no
// download, no install, no change of a setting.
func winUpdates(ctx context.Context) (map[string]any, error) {
	select {
	case wmiSlot <- struct{}{}:
	case <-ctx.Done():
		return nil, ctx.Err()
	}
	type result struct {
		state wuaState
		err   error
	}
	done := make(chan result, 1)
	go func() {
		defer func() { <-wmiSlot }()
		s, err := wuaRead()
		done <- result{s, err}
	}()
	select {
	case r := <-done:
		if r.err != nil {
			return nil, fmt.Errorf("windows update: %w", r.err)
		}
		return r.state.values(time.Now()), nil
	case <-ctx.Done():
		return nil, ctx.Err()
	}
}

// wuaRead runs on one locked thread, as COM requires.
func wuaRead() (s wuaState, err error) {
	runtime.LockOSThread()
	defer runtime.UnlockOSThread()
	if err := ole.CoInitializeEx(0, ole.COINIT_MULTITHREADED); err != nil {
		var oe *ole.OleError
		if !errors.As(err, &oe) || (oe.Code() != ole.S_OK && oe.Code() != 1) {
			return s, err
		}
	}
	defer ole.CoUninitialize()

	session, err := comObject("Microsoft.Update.Session")
	if err != nil {
		return s, err
	}
	defer session.Release()
	searcher, err := comCall(session, "CreateUpdateSearcher")
	if err != nil {
		return s, err
	}
	defer searcher.Release()
	if _, err := oleutil.PutProperty(searcher, "Online", false); err != nil {
		return s, err
	}
	found, err := comCall(searcher, "Search", "IsInstalled=0 and IsHidden=0")
	if err != nil {
		return s, err
	}
	defer found.Release()
	updates, err := comGet(found, "Updates")
	if err != nil {
		return s, err
	}
	defer updates.Release()
	count, err := oleutil.GetProperty(updates, "Count")
	if err != nil {
		return s, err
	}
	s.open = int(count.Val)
	for i := range s.open {
		item, err := comGet(updates, "Item", i)
		if err != nil {
			return s, err
		}
		sev, err := oleutil.GetProperty(item, "MsrcSeverity")
		item.Release()
		if err != nil {
			return s, err
		}
		if wuaSecurity(sev.ToString()) {
			s.security++
		}
	}

	info, err := comObject("Microsoft.Update.SystemInfo")
	if err != nil {
		return s, err
	}
	defer info.Release()
	reboot, err := oleutil.GetProperty(info, "RebootRequired")
	if err != nil {
		return s, err
	}
	s.reboot, _ = reboot.Value().(bool)

	// Windows Update's own last successful search. Not verified: an agent that never
	// searched answers no date, which leaves the age out.
	if auto, err := comObject("Microsoft.Update.AutoUpdate"); err == nil {
		defer auto.Release()
		if results, err := comGet(auto, "Results"); err == nil {
			defer results.Release()
			if at, err := oleutil.GetProperty(results, "LastSearchSuccessDate"); err == nil {
				s.lastSearch, _ = at.Value().(time.Time)
			}
		}
	}
	return s, nil
}

func comObject(progID string) (*ole.IDispatch, error) {
	unknown, err := oleutil.CreateObject(progID)
	if err != nil {
		return nil, fmt.Errorf("%s: %w", progID, err)
	}
	defer unknown.Release()
	return unknown.QueryInterface(ole.IID_IDispatch)
}

func comCall(d *ole.IDispatch, name string, params ...any) (*ole.IDispatch, error) {
	v, err := oleutil.CallMethod(d, name, params...)
	if err != nil {
		return nil, fmt.Errorf("%s: %w", name, err)
	}
	return v.ToIDispatch(), nil
}

func comGet(d *ole.IDispatch, name string, params ...any) (*ole.IDispatch, error) {
	v, err := oleutil.GetProperty(d, name, params...)
	if err != nil {
		return nil, fmt.Errorf("%s: %w", name, err)
	}
	return v.ToIDispatch(), nil
}

// winEvents counts the critical and error events of System and Application within the
// window, by level alone: their texts are localized and never read.
func winEvents(ctx context.Context, within time.Duration) (map[string]any, error) {
	values := map[string]any{}
	total := 0
	for _, ch := range []struct{ channel, key string }{{"System", "system"}, {"Application", "application"}} {
		n, err := countEvents(ctx, eventQuery{channel: ch.channel, levels: []uint8{1, 2}, within: within})
		if err != nil {
			return nil, err
		}
		values[ch.key] = n
		total += n
	}
	values["total"] = total
	return values, nil
}

// winCerts reads the validity of the machine certificates in LocalMachine\My.
func winCerts(context.Context) (map[string]any, error) {
	certs, err := machineCerts()
	if err != nil {
		return nil, err
	}
	notAfter := make([]time.Time, len(certs))
	for i, c := range certs {
		notAfter[i] = c.notAfter
	}
	return machineCertValues(notAfter, time.Now()), nil
}

// hypervState reads the VMs of this Hyper-V host, their heartbeats and their checkpoints.
func hypervState(ctx context.Context, _ Target) (map[string]any, error) {
	const ns = `root\virtualization\v2`
	var vms []hypervVM
	if err := (wmiQuery{namespace: ns, class: "Msvm_ComputerSystem"}).run(ctx, &vms); err != nil {
		return nil, err
	}
	var beats []hypervHeartbeat
	if err := (wmiQuery{namespace: ns, class: "Msvm_HeartbeatComponent"}).run(ctx, &beats); err != nil {
		return nil, err
	}
	// The type is compared here, not in a where clause: the query alphabet has no colon.
	var settings []hypervSetting
	if err := (wmiQuery{namespace: ns, class: "Msvm_VirtualSystemSettingData"}).run(ctx, &settings); err != nil {
		return nil, err
	}
	return hypervValues(vms, beats, settings, time.Now()), nil
}

// dfsrState reads the replicated folders of this DFS-R member and the day's events 2213
// and 4012 of the DFS Replication log.
func dfsrState(ctx context.Context, _ Target) (map[string]any, error) {
	var folders []dfsrFolder
	if err := (wmiQuery{namespace: `root\MicrosoftDfs`, class: "DfsrReplicatedFolderInfo"}).run(ctx, &folders); err != nil {
		return nil, err
	}
	count := func(id uint16) (int, error) {
		return countEvents(ctx, eventQuery{channel: "DFS Replication", provider: "DFSR", ids: []uint16{id}, within: appEventsWindow})
	}
	stopped, err := count(2213)
	if err != nil {
		return nil, err
	}
	stale, err := count(4012)
	if err != nil {
		return nil, err
	}
	return dfsrValues(folders, stopped, stale), nil
}

// optionalQuery reads q into dst; a class or namespace the host lacks (its role or feature is
// not installed) is no error, only ok false.
func optionalQuery(ctx context.Context, q wmiQuery, dst any) (bool, error) {
	err := q.run(ctx, dst)
	if errors.Is(err, ErrUnsupported) {
		return false, nil
	}
	return err == nil, err
}

// storageHealth reads the disks of the Storage Management API, the FSRM quotas, the shadow
// copies and the protection state of the BitLocker volumes.
func storageHealth(ctx context.Context) (map[string]any, error) {
	const storageNS = `root\Microsoft\Windows\Storage`
	var s storageState
	if err := (wmiQuery{namespace: `root\cimv2`, class: "Win32_ShadowCopy"}).run(ctx, &s.shadows); err != nil {
		return nil, err
	}
	var err error
	if s.hasDisks, err = optionalQuery(ctx, wmiQuery{namespace: storageNS, class: "MSFT_PhysicalDisk"}, &s.physical); err != nil {
		return nil, err
	}
	if s.hasDisks {
		if _, err := optionalQuery(ctx, wmiQuery{namespace: storageNS, class: "MSFT_VirtualDisk"}, &s.virtual); err != nil {
			return nil, err
		}
	}
	if s.hasQuotas, err = optionalQuery(ctx, wmiQuery{namespace: `root\Microsoft\Windows\FSRM`, class: "MSFT_FSRMQuota"}, &s.quotas); err != nil {
		return nil, err
	}
	if s.hasVolumes, err = optionalQuery(ctx, wmiQuery{namespace: `root\CIMV2\Security\MicrosoftVolumeEncryption`, class: "Win32_EncryptableVolume"}, &s.volumes); err != nil {
		return nil, err
	}
	return storageValues(s, time.Now()), nil
}

// printState reads the printers and the queued jobs of the print spooler.
func printState(ctx context.Context, _ Target) (map[string]any, error) {
	var printers []printer
	if err := (wmiQuery{namespace: `root\cimv2`, class: "Win32_Printer"}).run(ctx, &printers); err != nil {
		return nil, err
	}
	var jobs []printJob
	if err := (wmiQuery{namespace: `root\cimv2`, class: "Win32_PrintJob"}).run(ctx, &jobs); err != nil {
		return nil, err
	}
	return printValues(printers, jobs, time.Now()), nil
}

// defenderStatus reads the protection state of Microsoft Defender and its detections.
func defenderStatus(ctx context.Context) (map[string]any, error) {
	const ns = `root\Microsoft\Windows\Defender`
	var status []mpStatus
	if err := (wmiQuery{namespace: ns, class: "MSFT_MpComputerStatus"}).run(ctx, &status); err != nil {
		return nil, err
	}
	if len(status) == 0 {
		return nil, fmt.Errorf("%w: Defender reports no status", ErrUnsupported)
	}
	// An older Defender lacks the property, and then the query fails: the mode is left out.
	var modes []mpMode
	mode := ""
	if err := (wmiQuery{namespace: ns, class: "MSFT_MpComputerStatus"}).run(ctx, &modes); err == nil && len(modes) > 0 {
		mode = modes[0].AMRunningMode
	} else if ctxErr := ctx.Err(); ctxErr != nil {
		return nil, ctxErr
	}
	var threats []mpThreat
	if err := (wmiQuery{namespace: ns, class: "MSFT_MpThreatDetection"}).run(ctx, &threats); err != nil {
		return nil, err
	}
	return defenderValues(status[0], mode, threats, time.Now()), nil
}

// mssqlEvents counts the day's critical and error events of the SQL Server instance the
// target names, in the Application log.
func mssqlEvents(ctx context.Context, t Target) (map[string]any, error) {
	source, err := mssqlSource(t.Name)
	if err != nil {
		return nil, err
	}
	n, err := countEvents(ctx, eventQuery{channel: "Application", provider: source, levels: []uint8{1, 2}, within: appEventsWindow})
	if err != nil {
		return nil, err
	}
	return map[string]any{"errors_24h": n}, nil
}

// wsusContentKey holds ContentDir, the content folder WSUS setup chose (not verified on a
// WSUS server).
const wsusContentKey = `SOFTWARE\Microsoft\Update Services\Server\Setup`

// wsusState reads the free space at the WSUS content folder and the day's critical and error
// events of WSUS in the Application log. The last synchronization is not read: it is only in
// the WSUS database and its .NET API (Kevin 2026-11-14).
func wsusState(ctx context.Context, _ Target) (map[string]any, error) {
	key, err := registry.OpenKey(registry.LOCAL_MACHINE, wsusContentKey, registry.QUERY_VALUE)
	if err != nil {
		return nil, fmt.Errorf("%w: no WSUS setup key", ErrUnsupported)
	}
	dir, _, err := key.GetStringValue("ContentDir")
	key.Close()
	if err != nil || dir == "" {
		return nil, fmt.Errorf("%w: no WSUS content folder", ErrUnsupported)
	}
	path, err := windows.UTF16PtrFromString(dir)
	if err != nil {
		return nil, fmt.Errorf("%w: WSUS content folder", ErrInvalid)
	}
	var avail, total, free uint64
	if err := windows.GetDiskFreeSpaceEx(path, &avail, &total, &free); err != nil {
		return nil, fmt.Errorf("wsus content folder: %w", err)
	}
	values := freeValues(avail, total)
	n, err := countEvents(ctx, eventQuery{channel: "Application", provider: "Windows Server Update Services", levels: []uint8{1, 2}, within: appEventsWindow})
	if err != nil {
		return nil, err
	}
	values["errors_24h"] = n
	return values, nil
}
