// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"runtime"
	"time"

	"github.com/shirou/gopsutil/v4/cpu"
	"github.com/shirou/gopsutil/v4/disk"
	"github.com/shirou/gopsutil/v4/host"
	"github.com/shirou/gopsutil/v4/load"
	"github.com/shirou/gopsutil/v4/mem"
)

// Filesystem types to skip (Linux-specific; Windows ignores these).
var skipFSTypes = map[string]bool{
	"squashfs": true, "tmpfs": true, "devtmpfs": true, "overlay": true,
	"proc": true, "sysfs": true, "devpts": true, "cgroup": true,
	"cgroup2": true, "pstore": true, "bpf": true, "debugfs": true,
	"tracefs": true, "securityfs": true, "configfs": true, "fusectl": true,
	"mqueue": true, "hugetlbfs": true, "autofs": true, "binfmt_misc": true,
	"efivarfs": true, "fuse.lxcfs": true,
}

// Mount prefixes to skip (Linux-specific).
var skipMountPrefixes = []string{"/sys", "/proc", "/dev/", "/run/snapd", "/snap"}

func collectCPU() float64 {
	percents, err := cpu.Percent(1*time.Second, false)
	if err != nil || len(percents) == 0 {
		return 0
	}
	return round1(percents[0])
}

func collectMemory() map[string]any {
	v, err := mem.VirtualMemory()
	if err != nil {
		return nil
	}
	return map[string]any{
		"memory_percent":  round1(v.UsedPercent),
		"memory_total_mb": int(v.Total / 1024 / 1024),
		"memory_used_mb":  int(v.Used / 1024 / 1024),
	}
}

func collectLoad() map[string]any {
	if runtime.GOOS == "windows" {
		return nil
	}
	avg, err := load.Avg()
	if err != nil {
		return nil
	}
	return map[string]any{
		"load_1m":  round2(avg.Load1),
		"load_5m":  round2(avg.Load5),
		"load_15m": round2(avg.Load15),
	}
}

// DiskInfo holds the metrics of a partition.
type DiskInfo struct {
	Mount   string  `json:"mount"`
	FSType  string  `json:"fstype"`
	Percent float64 `json:"percent"`
	TotalGB float64 `json:"total_gb"`
	UsedGB  float64 `json:"used_gb"`
}

func collectDisks() []DiskInfo {
	parts, err := disk.Partitions(false)
	if err != nil {
		return nil
	}
	var disks []DiskInfo
	for _, p := range parts {
		if skipFSTypes[p.Fstype] {
			continue
		}
		if hasPrefix(p.Mountpoint, skipMountPrefixes) {
			continue
		}
		usage, err := disk.Usage(p.Mountpoint)
		if err != nil || usage.Total == 0 {
			continue
		}
		disks = append(disks, DiskInfo{
			Mount:   p.Mountpoint,
			FSType:  p.Fstype,
			Percent: round1(usage.UsedPercent),
			TotalGB: round1(float64(usage.Total) / (1024 * 1024 * 1024)),
			UsedGB:  round1(float64(usage.Used) / (1024 * 1024 * 1024)),
		})
	}
	return disks
}

func collectUptime() int {
	uptime, err := host.Uptime()
	if err != nil {
		return 0
	}
	return int(uptime)
}

// Helper functions

func hasPrefix(s string, prefixes []string) bool {
	for _, p := range prefixes {
		if len(s) >= len(p) && s[:len(p)] == p {
			return true
		}
	}
	return false
}

func round1(f float64) float64 {
	return float64(int(f*10+0.5)) / 10
}

func round2(f float64) float64 {
	return float64(int(f*100+0.5)) / 100
}
