// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package frpc

import "encoding/binary"

// tcpRowSize is the size of a MIB_TCPROW_OWNER_PID: state, local address, local port, remote
// address, remote port and owning process, six DWORDs.
const tcpRowSize = 24

// listenerOwnedBy reports whether table, a MIB_TCPTABLE_OWNER_PID of IPv4 listeners as
// GetExtendedTcpTable returns it, has a socket on 127.0.0.1:port owned by pid, and none of
// another process there: the reload goes only to the frpc the agent started, as on Linux
// (listensOnLoopback). The DWORD count is in host order (little-endian on Windows); address and
// port are in network order, the port in the low two bytes.
func listenerOwnedBy(table []byte, port int, pid uint32) bool {
	if len(table) < 4 {
		return false
	}
	n := int(binary.LittleEndian.Uint32(table))
	found := false
	for i := 0; i < n; i++ {
		off := 4 + i*tcpRowSize
		if off+tcpRowSize > len(table) {
			return false
		}
		row := table[off : off+tcpRowSize]
		if row[4] != 127 || row[5] != 0 || row[6] != 0 || row[7] != 1 ||
			int(binary.BigEndian.Uint16(row[8:10])) != port {
			continue
		}
		if binary.LittleEndian.Uint32(row[20:24]) != pid {
			return false
		}
		found = true
	}
	return found
}
