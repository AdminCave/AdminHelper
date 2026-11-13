// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package probe

import (
	"context"
	"fmt"

	"golang.org/x/sys/windows/svc"
)

// unitOwner returns whether a process is the one of the Windows service name. Services that share a
// process (svchost) share its listeners too.
func unitOwner(_ context.Context, name string) (func(pid int32) bool, error) {
	st, err := queryService(name)
	if err != nil {
		return nil, err
	}
	if st.State != svc.Running || st.ProcessId == 0 {
		return nil, fmt.Errorf("service %s is not running: it %w", name, errNotListening)
	}
	pid := int32(st.ProcessId)
	return func(p int32) bool { return p == pid }, nil
}

// containerEndpoint: the container networks of Windows are not resolved.
func containerEndpoint(context.Context, Target) (endpoint, error) {
	return endpoint{}, fmt.Errorf("%w: a container target on Windows", ErrUnsupported)
}

// ContainerListening: the agent reads no container networks on Windows.
func ContainerListening(int32) ([]uint16, error) {
	return nil, fmt.Errorf("%w: a container network on Windows", ErrUnsupported)
}
