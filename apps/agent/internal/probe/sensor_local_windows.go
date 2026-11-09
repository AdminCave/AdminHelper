// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package probe

import (
	"context"
	"errors"
	"fmt"
	"net"
	"os"
	"regexp"
	"time"

	"github.com/shirou/gopsutil/v4/process"
	"golang.org/x/sys/windows"
	"golang.org/x/sys/windows/svc"
	"golang.org/x/sys/windows/svc/mgr"
)

// unitPattern is the name of a Windows service, the unit of this platform.
var unitPattern = regexp.MustCompile(`^[A-Za-z0-9._$@-]{1,255}$`)

// queryService reads the status of the Windows service name; tests stand in their own.
var queryService = func(name string) (svc.Status, error) {
	m, err := windows.OpenSCManager(nil, nil, windows.SC_MANAGER_CONNECT)
	if err != nil {
		return svc.Status{}, fmt.Errorf("the service manager cannot be opened: %v", err)
	}
	defer windows.CloseServiceHandle(m)
	n, err := windows.UTF16PtrFromString(name)
	if err != nil {
		return svc.Status{}, fmt.Errorf("%w: service name %q", ErrInvalid, name)
	}
	h, err := windows.OpenService(m, n, windows.SERVICE_QUERY_STATUS)
	if errors.Is(err, windows.ERROR_SERVICE_DOES_NOT_EXIST) {
		return svc.Status{}, fmt.Errorf("service %s does not exist on this host", name)
	}
	if err != nil {
		return svc.Status{}, fmt.Errorf("service %s cannot be opened: %v", name, err)
	}
	s := &mgr.Service{Name: name, Handle: h}
	defer s.Close()
	return s.Query()
}

// serviceState maps the state of a Windows service to the active_state of a systemd unit and a
// sub_state of its own, so that one check fits both platforms.
func serviceState(s svc.State) (active, sub string) {
	switch s {
	case svc.Running:
		return "active", "running"
	case svc.StartPending:
		return "activating", "start_pending"
	case svc.ContinuePending:
		return "activating", "continue_pending"
	case svc.StopPending:
		return "deactivating", "stop_pending"
	case svc.PausePending:
		return "deactivating", "pause_pending"
	case svc.Paused:
		return "inactive", "paused"
	case svc.Stopped:
		return "inactive", "stopped"
	}
	return "unknown", fmt.Sprintf("state_%d", s)
}

// measureUnit reads the state of the Windows service name. While it runs, active_since is when its
// process started; services that share a process (svchost) share that time too. Windows counts no
// restarts.
func measureUnit(ctx context.Context, name string) (map[string]any, error) {
	st, err := queryService(name)
	if err != nil {
		return nil, err
	}
	active, sub := serviceState(st.State)
	values := map[string]any{"active_state": active, "sub_state": sub}
	if st.State == svc.Running && st.ProcessId != 0 {
		if p, err := process.NewProcessWithContext(ctx, int32(st.ProcessId)); err == nil {
			if ms, err := p.CreateTimeWithContext(ctx); err == nil {
				values["active_since"] = time.UnixMilli(ms).Unix()
			}
		}
	}
	return values, nil
}

// openNoWait opens path to read. A path of the monitoring service starts with "/", the root of the
// agent's drive; pathParam lets no pipe (\\.\pipe\…) through that could wait.
func openNoWait(path string) (*os.File, error) {
	return os.Open(path)
}

// refuseKernelFile: Windows has no file system of the kernel a path could reach.
func refuseKernelFile(*os.File, string) error {
	return nil
}

// dialUnix is not supported: the agent probes unix sockets on Linux only.
func dialUnix(context.Context, string) (net.Conn, error) {
	return nil, fmt.Errorf("%w: unix sockets are probed on Linux only", ErrUnsupported)
}
