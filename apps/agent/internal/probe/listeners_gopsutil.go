// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build !freebsd

package probe

import (
	"context"
	"net/netip"

	gnet "github.com/shirou/gopsutil/v4/net"
)

// listenTCP reads the listening TCP sockets of this host.
func listenTCP(ctx context.Context) ([]listener, error) {
	conns, err := gnet.ConnectionsWithContext(ctx, "tcp")
	if err != nil {
		return nil, err
	}
	var list []listener
	for _, c := range conns {
		if c.Status != "LISTEN" || c.Laddr.Port > 0xffff {
			continue
		}
		addr, err := netip.ParseAddr(c.Laddr.IP)
		if err != nil {
			continue
		}
		list = append(list, listener{addr: addr.Unmap().WithZone(""), port: uint16(c.Laddr.Port), pid: c.Pid})
	}
	return list, nil
}
