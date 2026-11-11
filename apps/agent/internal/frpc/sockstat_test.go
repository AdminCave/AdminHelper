// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package frpc

import "testing"

// Lines as `sockstat -4 -l -q -n -P tcp -p 7400` prints them: 15.x pads each column to its
// widest entry (usr.bin/sockstat/main.c), 14.x to fixed offsets (sockstat.c); a socket without
// a process shows ?? (15.x) or ? (14.x). frpc is root's process 1234. On FreeBSD itself
// TestSockstatSeesItsOwnListener runs the parser against the real tool.
const (
	rootFrpc15     = "0    frpc       1234  5 tcp4  127.0.0.1:7400        *:*\n"
	rootFrpc14     = "0        frpc        1234 5   tcp4   127.0.0.1:7400        *:*\n"
	userWildcard46 = "1001 nc         4567  3 tcp46 *:7400                *:*\n"
	otherPort46    = "1001 nc         4567  3 tcp46 *:17400               *:*\n"
	userSamePid    = "1001 frpc       1234  3 tcp4  127.0.0.1:7400        *:*\n"
	rootOtherPid   = "0    frpc       9999  5 tcp4  127.0.0.1:7400        *:*\n"
	rootNginx      = "0    nginx      3456  6 tcp4  127.0.0.1:7400        *:*\n"
	userWildcard   = "1001 nc         4567  3 tcp4  *:7400                *:*\n"
	rootWildcard   = "0    frpc       1234  5 tcp4  *:7400                *:*\n"
	noProcess15    = "??   ??           ?? ?? tcp4  127.0.0.1:7400        *:*\n"
	noProcess14    = "?        ?          ?     ?   tcp4   127.0.0.1:7400        *:*\n"
	otherPort      = "1001 nc         4567  3 tcp4  127.0.0.1:17400       *:*\n"
	spacedName     = "0    a b c      1234  5 tcp4  127.0.0.1:7400        *:*\n"
	noCommand      = "0               1234  5 tcp4  127.0.0.1:7400        *:*\n"
	brokenLine     = "1001 a\n"
	udpLine        = "0    frpc       1234  5 udp4  127.0.0.1:7400        *:*\n"
	fdNotNumber    = "0    frpc       1234  x tcp4  127.0.0.1:7400        *:*\n"
	pidNotNumber   = "1001 nc         x     3 tcp4  127.0.0.1:17400       *:*\n"
	userNotNumber  = "www  nc         4567  3 tcp4  127.0.0.1:17400       *:*\n"
	sockstatHeader = "USER COMMAND    PID   FD PROTO  LOCAL ADDRESS         FOREIGN ADDRESS\n"
)

func TestSockstatListensOnLoopback(t *testing.T) {
	for _, tc := range []struct {
		name, out string
		want      bool
	}{
		{"frpc, 15.x", rootFrpc15, true},
		{"frpc, 14.x", rootFrpc14, true},
		{"frpc beside a dual-stack socket on another port", otherPort46 + rootFrpc15, true},
		{"frpc beside a socket on another port", otherPort + rootFrpc15, true},
		{"frpc's pid under a name with blanks", spacedName, true},
		{"frpc's pid without a name", noCommand, true},
		{"frpc's pid under another user", userSamePid, false},
		{"root's process named frpc under another pid", rootOtherPid, false},
		{"root's process named frpc under another pid beside frpc", rootFrpc15 + rootOtherPid, false},
		{"another process of root", rootNginx, false},
		{"another user's wildcard beside frpc", rootFrpc15 + userWildcard, false},
		{"another user's wildcard before frpc", userWildcard + rootFrpc15, false},
		{"another user's dual-stack wildcard beside frpc", rootFrpc15 + userWildcard46, false},
		{"frpc on the wildcard only", rootWildcard, false},
		{"a socket without a process, 15.x", rootFrpc15 + noProcess15, false},
		{"a socket without a process, 14.x", noProcess14 + rootFrpc14, false},
		{"only another port", otherPort, false},
		{"a short line before frpc", brokenLine + rootFrpc15, false},
		{"a short line after frpc", rootFrpc15 + brokenLine, false},
		{"a line of another protocol beside frpc", rootFrpc15 + udpLine, false},
		{"a line whose fd is no number beside frpc", rootFrpc15 + fdNotNumber, false},
		{"a line whose pid is no number beside frpc", rootFrpc15 + pidNotNumber, false},
		{"a line whose user is no number beside frpc", rootFrpc15 + userNotNumber, false},
		{"the header (sockstat without -q)", sockstatHeader + rootFrpc15, false},
		{"empty", "", false},
	} {
		if got := sockstatListensOnLoopback([]byte(tc.out), 7400, "0", "1234"); got != tc.want {
			t.Errorf("%s: sockstatListensOnLoopback = %v, want %v", tc.name, got, tc.want)
		}
	}
}
