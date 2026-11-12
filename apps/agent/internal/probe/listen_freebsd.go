// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build freebsd

package probe

import "context"

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
