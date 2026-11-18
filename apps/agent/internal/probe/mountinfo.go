// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"bytes"
	"os"
	"strconv"
	"strings"
)

// NetFSTypes are the file system types of the network shares (R-1267): the disk list leaves them out,
// the discovery reports them, the share check measures them.
var NetFSTypes = map[string]bool{"nfs": true, "nfs4": true, "cifs": true, "smb3": true}

// NetMount is a network share mounted on this host. Where it comes from (the server, the export)
// stays on the host (Kevin 2026-11-18): only the mount point and the type go to the server.
type NetMount struct {
	Mountpoint string
	FSType     string
}

// mountinfoPath is a seam for the tests.
var mountinfoPath = "/proc/self/mountinfo"

// NetMounts lists the network shares mounted now, from the mount table alone: it asks none of them
// (no statfs), so a share that hangs costs nothing here.
func NetMounts() ([]NetMount, error) {
	data, err := os.ReadFile(mountinfoPath)
	if err != nil {
		return nil, err
	}
	return ParseNetMounts(data), nil
}

// ParseNetMounts reads the network shares of a mountinfo table (proc_pid_mountinfo(5)): the mount
// point is field 5, the type the first field after the separator "-". A mount point mounted twice
// counts once.
func ParseNetMounts(data []byte) []NetMount {
	var mounts []NetMount
	seen := map[string]bool{}
	for _, line := range bytes.Split(data, []byte("\n")) {
		fields := strings.Fields(string(line))
		sep := -1
		for i, f := range fields {
			if f == "-" && i >= 6 {
				sep = i
				break
			}
		}
		if sep < 0 || sep+1 >= len(fields) || !NetFSTypes[fields[sep+1]] {
			continue
		}
		point := unescapeMount(fields[4])
		if !strings.HasPrefix(point, "/") || seen[point] {
			continue
		}
		seen[point] = true
		mounts = append(mounts, NetMount{Mountpoint: point, FSType: fields[sep+1]})
	}
	return mounts
}

// unescapeMount undoes the octal escapes the kernel writes for space, tab, newline and backslash.
func unescapeMount(s string) string {
	if !strings.Contains(s, `\`) {
		return s
	}
	var b strings.Builder
	for i := 0; i < len(s); i++ {
		if s[i] == '\\' && i+4 <= len(s) {
			if n, err := strconv.ParseUint(s[i+1:i+4], 8, 8); err == nil {
				b.WriteByte(byte(n))
				i += 3
				continue
			}
		}
		b.WriteByte(s[i])
	}
	return b.String()
}
