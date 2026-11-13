// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"fmt"
	"net/netip"
	"strconv"
	"strings"
)

// sockstatArgs ask sockstat(1) for the listening TCP sockets of both families, numeric and without
// the header. -w: without it, 15.x cuts an address longer than its column (21 characters) short;
// 14.x never cuts and only pads wider.
var sockstatArgs = []string{"-46", "-l", "-n", "-q", "-w", "-P", "tcp"}

// parseSockstat reads the output of sockstat with sockstatArgs, one socket per line: USER COMMAND
// PID FD PROTO LOCAL-ADDRESS FOREIGN-ADDRESS. COMMAND is the process name, which may hold blanks or
// none at all, so the columns after it count from the end. The local address is addr:port, an IPv6
// address in brackets since 15.1 and bare before (so the port is what follows the last colon), and
// * for the unspecified address of the socket's family. A socket that no process holds shows ? on
// 14.x and ?? on 15.x for USER, COMMAND, PID and FD (displaysock in sockstat.c, main.c since 15.0);
// its owner is unknown (pid 0), as gopsutil reports one elsewhere. -l lists every socket without a
// foreign address, so a socket neither bound nor connected shows *:* (the guard's own dial socket
// during Control); it listens on nothing and is left out. A line of any other form rejects the whole
// output: the guard then lets no probe through rather than judge on a partial list.
func parseSockstat(out []byte) ([]listener, error) {
	var list []listener
	for _, line := range strings.Split(string(out), "\n") {
		f := strings.Fields(line)
		if len(f) == 0 {
			continue
		}
		l, ok := sockstatListener(f)
		if !ok {
			return nil, fmt.Errorf("sockstat printed a line of unknown form: %q", line)
		}
		if l.port == 0 {
			continue
		}
		list = append(list, l)
	}
	return list, nil
}

// sockstatListener reads the fields of one line of parseSockstat; an unbound socket is a listener
// without a port.
func sockstatListener(f []string) (listener, bool) {
	n := len(f)
	if n < 6 || !(digits(f[n-4]) || unknown(f[n-4])) {
		return listener{}, false
	}
	var pid int32
	if !unknown(f[n-5]) {
		if !digits(f[n-5]) {
			return listener{}, false
		}
		p, err := strconv.ParseInt(f[n-5], 10, 32)
		if err != nil {
			return listener{}, false
		}
		pid = int32(p)
	}
	// tcp, or toe for a connection the network card offloads (gather_inet in sockstat.c), then 4, 6
	// or 46 for the families of the socket.
	family, ok := strings.CutPrefix(f[n-3], "tcp")
	if !ok {
		family, ok = strings.CutPrefix(f[n-3], "toe")
	}
	if !ok || (family != "4" && family != "6" && family != "46") {
		return listener{}, false
	}
	local := f[n-2]
	if local == "*:*" {
		return listener{}, true
	}
	i := strings.LastIndexByte(local, ':')
	if i < 1 {
		return listener{}, false
	}
	if !digits(local[i+1:]) {
		return listener{}, false
	}
	port, err := strconv.ParseUint(local[i+1:], 10, 16)
	if err != nil || port == 0 {
		return listener{}, false
	}
	host := local[:i]
	var addr netip.Addr
	switch {
	case host == "*" && family == "4":
		addr = netip.IPv4Unspecified()
	case host == "*":
		addr = netip.IPv6Unspecified()
	default:
		if strings.HasPrefix(host, "[") && strings.HasSuffix(host, "]") {
			host = host[1 : len(host)-1]
		}
		if addr, err = netip.ParseAddr(host); err != nil {
			return listener{}, false
		}
	}
	return listener{addr: addr.Unmap().WithZone(""), port: uint16(port), pid: pid}, true
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

// unknown reports whether s is sockstat's mark for a number it does not know: a run of '?'.
func unknown(s string) bool {
	return s != "" && strings.Trim(s, "?") == ""
}
