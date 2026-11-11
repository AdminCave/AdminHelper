// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"net/netip"
	"reflect"
	"strings"
	"testing"

	"adminhelper-agent/internal/allowlist"
)

// sockstat15 is `sockstat -46 -l -n -q -w -P tcp` as FreeBSD 15.1 prints it (the box of T9, with an
// IPv6 address on lo0 for the long form), plus a name with a blank, a process whose name sockstat
// cannot read (??) and a socket that no process holds (?? in USER, COMMAND, PID and FD).
const sockstat15 = `1001 nc         5974  3 tcp4  127.0.0.1:44864                                *:*
1001 nc         5973  3 tcp6  [2001:db8:1234:5678:9abc:def0:1234:5678]:44863 *:*
1001 nc         5832  3 tcp6  [::1]:44861                                    *:*
0    sshd       1478  6 tcp6  *:22                                           *:*
0    sshd       1478  7 tcp4  *:22                                           *:*
80   php fpm    2210  5 tcp4  127.0.0.1:9000                                 *:*
0    ??         1500  4 tcp4  127.0.0.1:9001                                 *:*
??   ??         ??   ?? tcp46 *:9100                                         *:*
`

// sockstat14 is the same on FreeBSD 14.x (printaddr in releng/14.3 sockstat.c): IPv6 without
// brackets, ? for a socket that no process holds, toe for an offloaded connection, an empty name.
const sockstat14 = `0        sshd       812   4  tcp6   *:22                                          *:*
80       nginx      1001  6  tcp6   ::1:8080                                      *:*
80       nginx      1001  7  tcp46  *:443                                         *:*
80       nginx      1001  8  tcp6   ::ffff:192.0.2.1:8443                         *:*
?        ?          ?     ?  tcp4   127.0.0.1:2049                                *:*
0        iperf3     1200  3  toe4   192.0.2.10:5201                               *:*
0                   1300  3  tcp4   192.0.2.11:5202                               *:*
`

func TestParseSockstatReadsBothForms(t *testing.T) {
	l := func(addr string, port uint16, pid int32) listener {
		return listener{addr: netip.MustParseAddr(addr), port: port, pid: pid}
	}
	cases := []struct {
		name string
		out  string
		want []listener
	}{
		{"15.x", sockstat15, []listener{
			l("127.0.0.1", 44864, 5974),
			l("2001:db8:1234:5678:9abc:def0:1234:5678", 44863, 5973),
			l("::1", 44861, 5832),
			l("::", 22, 1478),
			l("0.0.0.0", 22, 1478),
			l("127.0.0.1", 9000, 2210),
			l("127.0.0.1", 9001, 1500),
			l("::", 9100, 0),
		}},
		{"14.x", sockstat14, []listener{
			l("::", 22, 812),
			l("::1", 8080, 1001),
			l("::", 443, 1001),
			l("192.0.2.1", 8443, 1001),
			l("127.0.0.1", 2049, 0),
			l("192.0.2.10", 5201, 1200),
			l("192.0.2.11", 5202, 1300),
		}},
	}
	for _, c := range cases {
		got, err := parseSockstat([]byte(c.out))
		if err != nil || !reflect.DeepEqual(got, c.want) {
			t.Errorf("%s: parseSockstat = %v, %v; want %v", c.name, got, err, c.want)
		}
	}
	if got, err := parseSockstat(nil); err != nil || len(got) != 0 {
		t.Errorf("no listener: parseSockstat = %v, %v; want none", got, err)
	}
}

func TestParseSockstatRejectsALineOfAnotherForm(t *testing.T) {
	lines := []string{
		// 15.x without -w cuts a long address short.
		"1001 nc         5954  3 tcp6  [2001:db8:1234:5678:9 *:*",
		"USER COMMAND     PID FD PROTO LOCAL ADDRESS         FOREIGN ADDRESS",
		"0    unbound    700   3 udp4  127.0.0.1:53          *:*",
		"0    sshd       812   4 tcp4  127.0.0.1:*           *:*",
		"0    sshd       812   4 tcp4  127.0.0.1:0           *:*",
		"0    sshd       812   4 tcp4  127.0.0.1:70000       *:*",
		"0    sshd       812   4 tcp4  127.0.0.1:+22         *:*",
		"0    sshd       812   4 tcp4  127.0.0.1             *:*",
		"0    sshd       812   4 tcp4  :22                   *:*",
		"0    sshd       812   4 tcp4  [::1:22               *:*",
		"0    sshd       812   4 tcp4  host.example:22       *:*",
		"0    sshd       -5    4 tcp4  127.0.0.1:22          *:*",
		"0    sshd       +5    4 tcp4  127.0.0.1:22          *:*",
		"0    sshd       99999999999 4 tcp4 127.0.0.1:22     *:*",
		"0    sshd       812   x tcp4  127.0.0.1:22          *:*",
		"0    sshd       812   4 tcp5  127.0.0.1:22          *:*",
		"0    sshd       812   4 tcptoe4 127.0.0.1:22        *:*",
		"0    sshd       812   4 tcp4",
		"812 4 tcp4 127.0.0.1:22 *:*",
	}
	for _, line := range lines {
		got, err := parseSockstat([]byte(sockstat15 + line + "\n"))
		if err == nil || got != nil || !strings.Contains(err.Error(), "unknown form") {
			t.Errorf("with %q: parseSockstat = %v, %v; want the whole output rejected", line, got, err)
		}
	}
}

// TestSockstatCallIsAllowed: the call listenTCP makes on FreeBSD is the one on the command allowlist.
func TestSockstatCallIsAllowed(t *testing.T) {
	if !allowlist.Allowed("/usr/bin/sockstat", sockstatArgs) {
		t.Errorf("sockstat %q is not on the command allowlist", sockstatArgs)
	}
}
