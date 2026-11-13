// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build freebsd

package probe

import (
	"context"
	"fmt"
)

// unitOwner returns whether a process is one of the rc.d service name (rcOwner).
func unitOwner(ctx context.Context, name string) (func(pid int32) bool, error) {
	return rcOwner(ctx, name)
}

// containerEndpoint: the agent resolves no container networks on FreeBSD.
func containerEndpoint(context.Context, Target) (endpoint, error) {
	return endpoint{}, fmt.Errorf("%w: a container target on FreeBSD", ErrUnsupported)
}

// ContainerListening: the agent reads no container networks on FreeBSD.
func ContainerListening(int32) ([]uint16, error) {
	return nil, fmt.Errorf("%w: a container network on FreeBSD", ErrUnsupported)
}
