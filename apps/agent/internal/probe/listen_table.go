// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"encoding/binary"
	"fmt"
	"net/netip"
)

// The layout of the tables GetExtendedTcpTable returns for TCP_TABLE_OWNER_MODULE_LISTENER on
// amd64 (Microsoft Learn, MIB_TCPTABLE_OWNER_MODULE and MIB_TCP6TABLE_OWNER_MODULE): dwNumEntries,
// padded to the 8-byte alignment of the rows; a row ends in OwningModuleInfo, 16 ULONGLONG
// (TCPIP_OWNING_MODULE_SIZE in tcpmib.h, not stated on the pages; the Windows test checks the rows).
const (
	tcpTableHead  = 8
	tcpRowModule  = 160 // six DWORD, liCreateTimestamp, OwningModuleInfo
	tcp6RowModule = 192 // two addresses of 16 bytes, six DWORD, liCreateTimestamp, OwningModuleInfo
)

// tableListener is a row of such a table: the listener and the FILETIME of the bind that created
// its socket (liCreateTimestamp).
type tableListener struct {
	listener
	created int64
}

// parseTCPModuleTable reads a MIB_TCPTABLE_OWNER_MODULE, or with v6 a MIB_TCP6TABLE_OWNER_MODULE.
// Ports are in network byte order, the IPv4 address as an in_addr, the IPv6 one in network byte
// order.
func parseTCPModuleTable(data []byte, v6 bool) ([]tableListener, error) {
	if len(data) < tcpTableHead {
		return nil, fmt.Errorf("a TCP table of %d bytes", len(data))
	}
	n := uint64(binary.LittleEndian.Uint32(data))
	size, pid, created := uint64(tcpRowModule), 20, 24
	if v6 {
		size, pid, created = tcp6RowModule, 52, 56
	}
	if uint64(len(data)) < tcpTableHead+n*size {
		return nil, fmt.Errorf("a TCP table of %d bytes for %d rows", len(data), n)
	}
	list := make([]tableListener, 0, n)
	for i := range n {
		r := data[tcpTableHead+i*size:][:size]
		var l tableListener
		if v6 {
			l.addr = netip.AddrFrom16([16]byte(r[0:16])).Unmap()
			l.port = binary.BigEndian.Uint16(r[20:22])
		} else {
			l.addr = netip.AddrFrom4([4]byte(r[4:8]))
			l.port = binary.BigEndian.Uint16(r[8:10])
		}
		l.pid = int32(binary.LittleEndian.Uint32(r[pid:]))
		l.created = int64(binary.LittleEndian.Uint64(r[created:]))
		list = append(list, l)
	}
	return list, nil
}

// clockTick is the longest clock tick of Windows, 15.625 ms in FILETIME units: the creation time of a
// process is read from the system time, which moves only once a tick.
const clockTick = 156_250

// createdByProcess reports whether a socket bound at the FILETIME created can be the socket of a
// process that started at start: only if it was bound more than a tick later. A process that started
// within the tick may have taken the pid of the one that bound it.
func createdByProcess(start, created int64) bool {
	return created > 0 && created-start > clockTick
}
