// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package frpc

import (
	"fmt"
	"strings"
)

// sockstatListensOnLoopback reports whether out, the output of `sockstat -4 -l -q -n -P tcp -p
// port` on FreeBSD, has a socket of process pid, owned by uid, listening on 127.0.0.1:port, and
// none of another process on 127.0.0.1:port or *:port. The process is told by its pid, not by its
// name: the name is that of the file it was started from, which its owner picks. A line not of the
// form below rejects the whole output, as does a socket without a process, which shows ? (14.x)
// or ?? (15.x) in place of the numbers.
func sockstatListensOnLoopback(out []byte, port int, uid, pid string) bool {
	loopback, wildcard := fmt.Sprintf("127.0.0.1:%d", port), fmt.Sprintf("*:%d", port)
	found := false
	for _, line := range strings.Split(string(out), "\n") {
		// USER COMMAND PID FD PROTO LOCAL-ADDRESS FOREIGN-ADDRESS. COMMAND is the process name,
		// which may hold blanks or none at all, so the columns after it count from the end.
		f := strings.Fields(line)
		if len(f) == 0 {
			continue
		}
		if len(f) < 6 || !digits(f[0]) || !digits(f[len(f)-5]) || !digits(f[len(f)-4]) ||
			(f[len(f)-3] != "tcp4" && f[len(f)-3] != "tcp46") {
			return false
		}
		local := f[len(f)-2]
		if local != loopback && local != wildcard {
			continue
		}
		if f[0] != uid || f[len(f)-5] != pid {
			return false
		}
		if local == loopback {
			found = true
		}
	}
	return found
}

// digits reports whether s is a non-empty run of ASCII digits.
func digits(s string) bool {
	if s == "" {
		return false
	}
	for _, c := range s {
		if c < '0' || c > '9' {
			return false
		}
	}
	return true
}
