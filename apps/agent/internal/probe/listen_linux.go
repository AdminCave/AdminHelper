// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package probe

import (
	"context"
	"errors"
	"io/fs"
	"os"
	"slices"
	"strconv"
	"strings"
)

// listenTCP reads the listening TCP sockets of this host from /proc/net/tcp and tcp6 and finds the
// processes that hold each among the descriptors of every process: one listener per socket and
// process. gopsutil keeps one process per address (connectionDedupKey), so a socket systemd holds for
// a service that holds it too showed either of the two. A socket no process can be found for is a
// listener of pid 0, which the guard cannot name and so refuses.
func listenTCP(ctx context.Context) ([]listener, error) {
	var socks []listener
	for _, name := range []string{"tcp", "tcp6"} {
		data, err := readProcFile("/proc/net/" + name)
		// Without IPv6 the kernel has no tcp6 file.
		if err != nil && !(name == "tcp6" && errors.Is(err, fs.ErrNotExist)) {
			return nil, err
		}
		socks = append(socks, parseProcNetTCP(data)...)
	}
	holders, err := socketHolders(ctx, socks)
	if err != nil {
		return nil, err
	}
	var list []listener
	for _, s := range socks {
		pids := holders[s.sock]
		if len(pids) == 0 {
			pids = []int32{0}
		}
		for _, pid := range pids {
			s.pid = pid
			list = append(list, s)
		}
	}
	return list, nil
}

// socketHolders returns, by inode, the processes that hold one of socks, in ascending order. A process
// that ended meanwhile or whose descriptors cannot be read holds none.
func socketHolders(ctx context.Context, socks []listener) (map[string][]int32, error) {
	want := map[string]string{}
	for _, s := range socks {
		want["socket:["+s.sock+"]"] = s.sock
	}
	holders := map[string][]int32{}
	if len(want) == 0 {
		return holders, nil
	}
	entries, err := os.ReadDir("/proc")
	if err != nil {
		return nil, err
	}
	for _, e := range entries {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		p, err := strconv.ParseInt(e.Name(), 10, 32)
		if err != nil {
			continue
		}
		dir := "/proc/" + e.Name() + "/fd/"
		fds, err := os.ReadDir(dir)
		if err != nil {
			continue
		}
		for _, fd := range fds {
			link, err := os.Readlink(dir + fd.Name())
			if err != nil {
				continue
			}
			// A process may hold one socket under several descriptors.
			if inode, ok := want[link]; ok && !slices.Contains(holders[inode], int32(p)) {
				holders[inode] = append(holders[inode], int32(p))
			}
		}
	}
	return holders, nil
}

// osPrivilegedPorts returns the ports only root may bind in the agent's network namespace: below
// ip_unprivileged_port_start (Linux ip-sysctl), 1024 where the kernel predates the sysctl.
func osPrivilegedPorts() (lo, hi uint16) {
	data, err := os.ReadFile("/proc/sys/net/ipv4/ip_unprivileged_port_start")
	if err != nil {
		return 1, 1023
	}
	start, err := strconv.ParseUint(strings.TrimSpace(string(data)), 10, 16)
	if err != nil {
		return 1, 1023
	}
	if start == 0 {
		return 1, 0
	}
	return 1, uint16(start - 1)
}
