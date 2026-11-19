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

// NetMount is a mount point of this host and the type of its file system; for a network share where
// it comes from (the server, the export) stays on the host (Kevin 2026-11-18): only the mount point
// and the type go to the server.
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

// Mounts lists every mount point of the mount table with the type of the file system visible there.
func Mounts() ([]NetMount, error) {
	data, err := os.ReadFile(mountinfoPath)
	if err != nil {
		return nil, err
	}
	return parseMounts(data), nil
}

// ParseNetMounts reads the network shares of a mountinfo table: the mount points whose visible file
// system is a network share.
func ParseNetMounts(data []byte) []NetMount {
	var shares []NetMount
	for _, m := range parseMounts(data) {
		if NetFSTypes[m.FSType] {
			shares = append(shares, m)
		}
	}
	return shares
}

// parseMounts reads a mountinfo table (proc_pid_mountinfo(5)): the mount point is field 5, the type
// the first field after the separator "-". A mount point mounted twice counts once, in the place of
// its first mount, with the type of its last: the table lists a mount after the one it covers, so
// the last is the one visible.
func parseMounts(data []byte) []NetMount {
	var mounts []NetMount
	at := map[string]int{}
	for _, line := range bytes.Split(data, []byte("\n")) {
		fields := strings.Fields(string(line))
		sep := -1
		for i, f := range fields {
			if f == "-" && i >= 6 {
				sep = i
				break
			}
		}
		if sep < 0 || sep+1 >= len(fields) {
			continue
		}
		point := unescapeMount(fields[4])
		if !strings.HasPrefix(point, "/") {
			continue
		}
		if i, ok := at[point]; ok {
			mounts[i].FSType = fields[sep+1]
			continue
		}
		at[point] = len(mounts)
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
