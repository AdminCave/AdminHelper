// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package probe

import (
	"context"
	"errors"
	"unsafe"

	"golang.org/x/sys/windows"
)

var procGetExtendedTcpTable = windows.NewLazySystemDLL("iphlpapi.dll").NewProc("GetExtendedTcpTable")

// tcpTableOwnerModuleListener is TCP_TABLE_OWNER_MODULE_LISTENER, the seventh value of
// TCP_TABLE_CLASS.
const tcpTableOwnerModuleListener = 6

// listenTCP reads the listening TCP sockets of this host with the account each runs under
// (osListenerAccount). The table names the process that created a socket by its pid, which Windows
// may have given to another process since; the creation time of the socket tells.
func listenTCP(ctx context.Context) ([]listener, error) {
	var list []listener
	for _, af := range []struct {
		family uint32
		v6     bool
	}{{windows.AF_INET, false}, {windows.AF_INET6, true}} {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		rows, err := tcpListenerTable(af.family, af.v6)
		if err != nil {
			return nil, err
		}
		for _, r := range rows {
			r.uid, r.hasUID = osListenerAccount(r.pid, r.created)
			list = append(list, r.listener)
		}
	}
	return list, nil
}

// tcpListenerTable asks GetExtendedTcpTable for the listeners of family, growing the buffer to the
// size it answers while the table grows.
func tcpListenerTable(family uint32, v6 bool) ([]tableListener, error) {
	var size uint32
	var buf []byte
	for range 8 {
		var p uintptr
		if len(buf) > 0 {
			p = uintptr(unsafe.Pointer(&buf[0]))
		}
		r, _, _ := procGetExtendedTcpTable.Call(p, uintptr(unsafe.Pointer(&size)), 0, uintptr(family),
			tcpTableOwnerModuleListener, 0)
		switch err := windows.Errno(r); {
		case r == 0 && len(buf) > 0:
			return parseTCPModuleTable(buf[:min(int(size), len(buf))], v6)
		case r == 0 || err == windows.ERROR_INSUFFICIENT_BUFFER:
			buf = make([]byte, size)
		default:
			return nil, err
		}
	}
	return nil, errors.New("the TCP table kept growing")
}

// osPrivilegedPorts: Windows reserves no ports for its administrators, so no port is privileged.
func osPrivilegedPorts() (lo, hi uint16) {
	return 1, 0
}
