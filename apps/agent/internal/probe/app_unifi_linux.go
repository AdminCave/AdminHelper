// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package probe

import (
	"context"
	"fmt"
	"strconv"
	"strings"
)

// unifiOwner returns whether a process belongs to the UniFi OS Server of the unit name: whether it
// runs in the unit's cgroup or below it, or below the systemd user manager of the user the unit's
// main process runs as, if that is not root. UniFi OS Server 5.1.42 runs its container in rootless
// Podman, whose port forwarder (pasta) holds the HTTPS port from the cgroup of that user manager
// (/user.slice/user-<uid>.slice/user@<uid>.service/…), not from the unit's.
func unifiOwner(ctx context.Context, name string) (func(pid int32) bool, error) {
	props, err := showUnit(ctx, name, "ControlGroup", "MainPID")
	if err != nil {
		return nil, err
	}
	cg := props["ControlGroup"]
	main, _ := strconv.Atoi(props["MainPID"])
	if cg == "" || cg == "/" || main <= 0 {
		return nil, fmt.Errorf("unit %s is not running: it %w", name, errNotListening)
	}
	inUnit := func(path string) bool { return path == cg || strings.HasPrefix(path, cg+"/") }
	var manager string
	// The cgroup is read after the uid: a main process that ended and whose pid went to another
	// process meanwhile must not hand that process's user manager the key.
	if uid, ok := procUID(int32(main)); ok && uid != 0 && inCgroup(int32(main), inUnit) {
		manager = fmt.Sprintf("/user.slice/user-%d.slice/user@%d.service/", uid, uid)
	}
	return func(pid int32) bool {
		return inCgroup(pid, func(path string) bool {
			return inUnit(path) || (manager != "" && strings.HasPrefix(path, manager))
		})
	}, nil
}

// procUID returns the real user id of the process pid, false if it cannot be read.
func procUID(pid int32) (int, bool) {
	data, err := readProcFile("/proc/" + strconv.Itoa(int(pid)) + "/status")
	if err != nil {
		return 0, false
	}
	for line := range strings.SplitSeq(string(data), "\n") {
		if rest, ok := strings.CutPrefix(line, "Uid:"); ok {
			f := strings.Fields(rest)
			if len(f) == 0 {
				return 0, false
			}
			uid, err := strconv.Atoi(f[0])
			return uid, err == nil && uid >= 0
		}
	}
	return 0, false
}
