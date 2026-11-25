// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build freebsd

package monitor

import (
	"time"

	"github.com/shirou/gopsutil/v4/disk"
	"golang.org/x/sys/unix"
)

// collectDisks lists the mounts with getfsstat(2) and MNT_NOWAIT, which asks no file system
// (gopsutil's disk.Partitions uses MNT_WAIT and hangs on a hung NFS mount, R-1701). The figures
// of that list are only the kernel's cached mnt_stat, which nothing refreshes without MNT_WAIT,
// so each mount is read with statfs(2) of its own: a local one directly, a network one bounded
// by boundedStats, as is a local one below a network mount.
func collectDisks() []DiskInfo {
	n, err := unix.Getfsstat(nil, unix.MNT_NOWAIT)
	if err != nil || n == 0 {
		return nil
	}
	buf := make([]unix.Statfs_t, n)
	n, err = unix.Getfsstat(buf, unix.MNT_NOWAIT)
	if err != nil {
		return nil
	}
	var local, shares []string
	for _, s := range buf[:n] {
		mount := unix.ByteSliceToString(s.Mntonname[:])
		fstype := unix.ByteSliceToString(s.Fstypename[:])
		if skippedDisk(disk.PartitionStat{Mountpoint: mount, Fstype: fstype}, "freebsd") {
			continue
		}
		if freebsdNetFS(fstype) {
			shares = append(shares, mount)
		} else {
			local = append(local, mount)
		}
	}
	// A local mount below a share is reached through it and is read with the deadline too.
	var stats []fsStat
	bounded := shares
	for _, mount := range local {
		if underNetMount(mount, shares) {
			bounded = append(bounded, mount)
			continue
		}
		if st, err := statfsOf(mount); err == nil {
			stats = append(stats, st)
		}
	}
	answered := boundedStats(bounded, time.After(shareStatTimeout), statfsOf)
	if len(answered) < len(bounded) {
		logger.Warnf("disks: %d network mount(s) did not answer statfs within %s or still hang from an earlier run, left out of this run",
			len(bounded)-len(answered), shareStatTimeout)
	}
	return disksFromFsstat(append(stats, answered...), "freebsd")
}

func statfsOf(mount string) (fsStat, error) {
	var s unix.Statfs_t
	if err := unix.Statfs(mount, &s); err != nil {
		return fsStat{}, err
	}
	return fsStat{
		Mount:  mount,
		FSType: unix.ByteSliceToString(s.Fstypename[:]),
		Bsize:  uint64(s.Bsize),
		Blocks: uint64(s.Blocks),
		Bfree:  uint64(s.Bfree),
		Bavail: int64(s.Bavail),
	}, nil
}
