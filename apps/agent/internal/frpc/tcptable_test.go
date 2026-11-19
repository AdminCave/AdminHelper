// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package frpc

import (
	"encoding/binary"
	"testing"
)

// tcpTable builds a MIB_TCPTABLE_OWNER_PID as Windows lays it out.
func tcpTable(rows ...[3]uint32) []byte { // addr (a.b.c.d as big-endian), port, pid
	b := make([]byte, 4+len(rows)*tcpRowSize)
	binary.LittleEndian.PutUint32(b, uint32(len(rows)))
	for i, r := range rows {
		row := b[4+i*tcpRowSize:]
		binary.LittleEndian.PutUint32(row[0:], 2) // MIB_TCP_STATE_LISTEN
		binary.BigEndian.PutUint32(row[4:], r[0])
		binary.BigEndian.PutUint16(row[8:], uint16(r[1]))
		binary.LittleEndian.PutUint32(row[20:], r[2])
	}
	return b
}

const loopback = 0x7f000001

func TestListenerOwnedBy(t *testing.T) {
	cases := []struct {
		name  string
		table []byte
		want  bool
	}{
		{"own frpc on loopback", tcpTable([3]uint32{loopback, 7400, 42}), true},
		{"another process on the port", tcpTable([3]uint32{loopback, 7400, 99}), false},
		{"own and another process", tcpTable([3]uint32{loopback, 7400, 42}, [3]uint32{loopback, 7400, 99}), false},
		{"own frpc on another port", tcpTable([3]uint32{loopback, 7401, 42}), false},
		{"own frpc on all addresses only", tcpTable([3]uint32{0, 7400, 42}), false},
		{"other rows around it", tcpTable([3]uint32{0, 445, 4}, [3]uint32{loopback, 7400, 42}, [3]uint32{loopback, 80, 7}), true},
		{"empty table", tcpTable(), false},
		{"truncated table", tcpTable([3]uint32{loopback, 7400, 42})[:20], false},
		{"no table", nil, false},
	}
	for _, c := range cases {
		if got := listenerOwnedBy(c.table, 7400, 42); got != c.want {
			t.Errorf("%s: listenerOwnedBy = %v, want %v", c.name, got, c.want)
		}
	}
}
