// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package discovery

import (
	"errors"
	"fmt"
	"unsafe"

	"golang.org/x/sys/windows"
	"golang.org/x/sys/windows/svc"

	"adminhelper-agent/internal/probe"
)

// Containers are discovered on Linux alone; seams for the tests, listServices among them.
var (
	cgroupsOf          = func(int32) probe.Cgroups { return nil }
	containerListening = func(int32) ([]uint16, error) { return nil, nil }
	listServices       = enumServices
)

// enumServices lists the Win32 services the service manager knows, in any state, with their state as
// the unit sensor maps it (probe.ServiceState). It opens the manager to enumerate alone and opens no
// service.
func enumServices() ([]Unit, error) {
	m, err := windows.OpenSCManager(nil, nil, windows.SC_MANAGER_ENUMERATE_SERVICE)
	if err != nil {
		return nil, fmt.Errorf("the service manager cannot be opened: %v", err)
	}
	defer windows.CloseServiceHandle(m)
	var buf []byte
	var needed, returned uint32
	for {
		var p *byte
		if len(buf) > 0 {
			p = &buf[0]
		}
		err = windows.EnumServicesStatusEx(m, windows.SC_ENUM_PROCESS_INFO, windows.SERVICE_WIN32,
			windows.SERVICE_STATE_ALL, p, uint32(len(buf)), &needed, &returned, nil, nil)
		if err == nil {
			break
		}
		// A service installed between two calls asks for more again; a buffer that does not grow
		// would loop for ever.
		if !errors.Is(err, windows.ERROR_MORE_DATA) || needed <= uint32(len(buf)) {
			return nil, fmt.Errorf("the services cannot be enumerated: %v", err)
		}
		buf = make([]byte, needed)
	}
	units := make([]Unit, 0, returned)
	if returned == 0 {
		return units, nil
	}
	for _, s := range unsafe.Slice((*windows.ENUM_SERVICE_STATUS_PROCESS)(unsafe.Pointer(&buf[0])), int(returned)) {
		active, sub := probe.ServiceState(svc.State(s.ServiceStatusProcess.CurrentState))
		units = append(units, Unit{Name: windows.UTF16PtrToString(s.ServiceName), State: active, Sub: sub})
	}
	return units, nil
}
