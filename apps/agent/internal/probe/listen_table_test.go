// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"encoding/binary"
	"net/netip"
	"testing"
)

// TestParseTCPModuleTableReadsTheRowsOfBothFamilies builds the tables by the layout of Microsoft
// Learn: a padded count, then rows with the port in network byte order.
func TestParseTCPModuleTableReadsTheRowsOfBothFamilies(t *testing.T) {
	v4 := make([]byte, tcpTableHead+2*tcpRowModule)
	binary.LittleEndian.PutUint32(v4, 2)
	for i, row := range []struct {
		addr    [4]byte
		port    uint16
		pid     uint32
		created uint64
	}{{[4]byte{127, 0, 0, 1}, 8443, 4242, 133_000_000_000_000_000}, {[4]byte{0, 0, 0, 0}, 80, 4, 7}} {
		r := v4[tcpTableHead+i*tcpRowModule:]
		binary.LittleEndian.PutUint32(r, 2) // MIB_TCP_STATE_LISTEN
		copy(r[4:8], row.addr[:])
		binary.BigEndian.PutUint16(r[8:10], row.port)
		binary.LittleEndian.PutUint32(r[20:24], row.pid)
		binary.LittleEndian.PutUint64(r[24:32], row.created)
		for j := 32; j < tcpRowModule; j++ {
			r[j] = 0xff // OwningModuleInfo must not leak into the next row
		}
	}
	got, err := parseTCPModuleTable(v4, false)
	if err != nil || len(got) != 2 {
		t.Fatalf("v4: %v, %v", got, err)
	}
	if got[0].addr != netip.MustParseAddr("127.0.0.1") || got[0].port != 8443 || got[0].pid != 4242 || got[0].created != 133_000_000_000_000_000 {
		t.Errorf("v4 row 0: %+v", got[0])
	}
	if got[1].addr != netip.MustParseAddr("0.0.0.0") || got[1].port != 80 || got[1].pid != 4 || got[1].created != 7 {
		t.Errorf("v4 row 1: %+v", got[1])
	}

	v6 := make([]byte, tcpTableHead+tcp6RowModule)
	binary.LittleEndian.PutUint32(v6, 1)
	r := v6[tcpTableHead:]
	loop := netip.MustParseAddr("::1").As16()
	copy(r[0:16], loop[:])
	binary.BigEndian.PutUint16(r[20:22], 5432)
	binary.LittleEndian.PutUint32(r[48:52], 2)
	binary.LittleEndian.PutUint32(r[52:56], 900)
	binary.LittleEndian.PutUint64(r[56:64], 99)
	got, err = parseTCPModuleTable(v6, true)
	if err != nil || len(got) != 1 || got[0].addr != netip.MustParseAddr("::1") || got[0].port != 5432 || got[0].pid != 900 || got[0].created != 99 {
		t.Errorf("v6: %+v, %v", got, err)
	}
	mapped := netip.MustParseAddr("::ffff:192.0.2.1").As16()
	copy(r[0:16], mapped[:])
	if got, _ := parseTCPModuleTable(v6, true); got[0].addr != netip.MustParseAddr("192.0.2.1") {
		t.Errorf("a v4-mapped address: %v", got[0].addr)
	}

	for _, short := range [][]byte{nil, v4[:4], v4[:len(v4)-1], v6[:tcpTableHead+tcp6RowModule-1]} {
		if _, err := parseTCPModuleTable(short, len(short) > 0 && &short[0] == &v6[0]); err == nil {
			t.Errorf("a table of %d bytes: no error", len(short))
		}
	}
}
