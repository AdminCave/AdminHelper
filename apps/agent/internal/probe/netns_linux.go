// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package probe

import (
	"bufio"
	"bytes"
	"context"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"strconv"
	"strings"
)

// agentNetNS names the network namespace of the agent; tests stand in their own.
var agentNetNS = func() (string, error) { return os.Readlink("/proc/self/ns/net") }

// namespaceProcesses returns the processes that listen on TCP port in the network namespace of pid:
// the inodes of the listening sockets from /proc/<pid>/net/tcp{,6}, found again among the
// descriptors of the processes in that namespace. A socket no process can be found for is an error,
// as is none at all.
func namespaceProcesses(ctx context.Context, pid int32, port uint16) ([]int32, error) {
	if pid <= 0 {
		return nil, errors.New("the container has no process")
	}
	base := "/proc/" + strconv.Itoa(int(pid))
	ns, err := os.Readlink(base + "/ns/net")
	if err != nil {
		return nil, fmt.Errorf("the network namespace of the container cannot be read: %v", err)
	}
	// The pid may come from a list older than the container: a host process may hold it by now.
	if own, err := agentNetNS(); err != nil || own == ns {
		return nil, errors.New("the process of the container is no longer in a namespace of its own")
	}
	sockets := map[string]bool{}
	for _, name := range []string{"tcp", "tcp6"} {
		data, err := readProcFile(base + "/net/" + name)
		// Without IPv6 the kernel has no tcp6 file.
		if err != nil && !(name == "tcp6" && errors.Is(err, fs.ErrNotExist)) {
			return nil, fmt.Errorf("the listening sockets of the container cannot be read: %v", err)
		}
		for _, inode := range listenInodes(data, port) {
			sockets["socket:["+inode+"]"] = false
		}
	}
	if len(sockets) == 0 {
		return nil, fmt.Errorf("no socket listens on port %d", port)
	}
	entries, err := os.ReadDir("/proc")
	if err != nil {
		return nil, err
	}
	var pids []int32
	for _, e := range entries {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		p, err := strconv.ParseInt(e.Name(), 10, 32)
		if err != nil {
			continue
		}
		dir := "/proc/" + e.Name()
		// A process that ended meanwhile, or one of another namespace, holds none of the sockets.
		if other, err := os.Readlink(dir + "/ns/net"); err != nil || other != ns {
			continue
		}
		fds, err := os.ReadDir(dir + "/fd")
		if err != nil {
			continue
		}
		holds := false
		for _, fd := range fds {
			link, err := os.Readlink(dir + "/fd/" + fd.Name())
			if _, ok := sockets[link]; err == nil && ok {
				sockets[link], holds = true, true
			}
		}
		if holds {
			pids = append(pids, int32(p))
		}
	}
	for _, found := range sockets {
		if !found {
			return nil, fmt.Errorf("the process holding port %d cannot be found", port)
		}
	}
	return pids, nil
}

// listenInodes returns the inodes of the sockets in a /proc/net/tcp{,6} file that listen on port.
func listenInodes(data []byte, port uint16) []string {
	var inodes []string
	sc := bufio.NewScanner(bytes.NewReader(data))
	for sc.Scan() {
		f := strings.Fields(sc.Text())
		if len(f) < 10 || f[3] != "0A" {
			continue
		}
		_, num, ok := strings.Cut(f[1], ":")
		if p, err := strconv.ParseUint(num, 16, 16); !ok || err != nil || uint16(p) != port {
			continue
		}
		inodes = append(inodes, f[9])
	}
	return inodes
}
