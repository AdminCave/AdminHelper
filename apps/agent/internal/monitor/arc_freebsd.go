// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build freebsd

package monitor

import "golang.org/x/sys/unix"

// arcReclaimable is the ARC above c_min in bytes, 0 without ZFS (the sysctls are missing then).
func arcReclaimable() uint64 {
	size, err := unix.SysctlUint64("kstat.zfs.misc.arcstats.size")
	if err != nil {
		return 0
	}
	cMin, err := unix.SysctlUint64("kstat.zfs.misc.arcstats.c_min")
	if err != nil {
		return 0
	}
	return arcAbove(size, cMin)
}
