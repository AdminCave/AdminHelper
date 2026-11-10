// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build freebsd

package probe

import (
	"context"
	"fmt"
)

// sockstatPath is sockstat(1) of the FreeBSD base system.
const sockstatPath = "/usr/bin/sockstat"

// listenTCP reads the listening TCP sockets of this host from sockstat: gopsutil reads them on
// FreeBSD through lsof, which the base system and OPNsense do not ship.
func listenTCP(ctx context.Context) ([]listener, error) {
	out, err := runTool(ctx, toolTimeout, sockstatPath, "-46lnq", "-P", "tcp")
	if err != nil {
		return nil, fmt.Errorf("sockstat: %w", err)
	}
	return parseSockstat(out)
}

// unitOwner returns whether a process is one of the rc.d service name (rcOwner).
func unitOwner(ctx context.Context, name string) (func(pid int32) bool, error) {
	return rcOwner(ctx, name)
}

// containerEndpoint: FreeBSD runs no containers the agent resolves.
func containerEndpoint(context.Context, Target) (endpoint, error) {
	return endpoint{}, fmt.Errorf("%w: a container target on FreeBSD", ErrUnsupported)
}
