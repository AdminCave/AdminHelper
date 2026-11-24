// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build !freebsd

package monitor

import "github.com/shirou/gopsutil/v4/disk"

func collectDisks() []DiskInfo {
	parts, err := disk.Partitions(false)
	if err != nil {
		return nil
	}
	var disks []DiskInfo
	for _, p := range parts {
		if skippedDisk(p, resourceCalls.goos) {
			continue
		}
		usage, err := disk.Usage(p.Mountpoint)
		if err != nil || usage.Total == 0 {
			continue
		}
		disks = append(disks, diskInfo(p, usage, resourceCalls.goos))
	}
	return disks
}
