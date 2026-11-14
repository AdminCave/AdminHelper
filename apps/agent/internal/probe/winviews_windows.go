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
