// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build freebsd

package probe

import (
	"context"

	"golang.org/x/sys/unix"
)

// sockstatPath is absolute: cron gives the agent a short PATH.
const sockstatPath = "/usr/bin/sockstat"

// listenTCP reads the listening TCP sockets of this host from sockstat(1) in the base system;
// gopsutil would ask lsof, a package most hosts do not have.
func listenTCP(ctx context.Context) ([]listener, error) {
	out, err := runTool(ctx, toolTimeout, sockstatPath, sockstatArgs...)
	if err != nil {
		return nil, err
	}
	return parseSockstat(out)
}

// osPrivilegedPorts returns the ports only root may bind: net.inet.ip.portrange.reservedlow to
// reservedhigh (ip(4)), 0 to 1023 where they cannot be read.
func osPrivilegedPorts() (lo, hi uint16) {
	l, errLo := unix.SysctlUint32("net.inet.ip.portrange.reservedlow")
	h, errHi := unix.SysctlUint32("net.inet.ip.portrange.reservedhigh")
	if errLo != nil || errHi != nil || l > 0xffff || h > 0xffff {
		return 0, 1023
	}
	return uint16(l), uint16(h)
}
