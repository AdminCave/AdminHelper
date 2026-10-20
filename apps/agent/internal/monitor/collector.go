// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"math"
	"runtime"
	"strings"
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

// cpuSampleInterval is a variable so tests can skip the 1s blocking CPU sample.
var cpuSampleInterval = 1 * time.Second

// cpuStateMaxAge bounds the window collectCPUSince averages over: older CPU times (agent stopped,
// pushes failing) say little about the last minutes, so the 1s sample is taken instead.
const cpuStateMaxAge = 15 * time.Minute

// cpuCalls indirects gopsutil's CPU reads so tests can drive the average and observe the fallback
// sample without depending on the host (same reason as hostFactsCalls, 6.18).
var cpuCalls = struct {
	times   func(percpu bool) ([]cpu.TimesStat, error)
	percent func(interval time.Duration, percpu bool) ([]float64, error)
}{cpu.Times, cpu.Percent}

func collectCPU() float64 {
	percents, err := cpuCalls.percent(cpuSampleInterval, false)
	if err != nil || len(percents) == 0 {
		return 0
	}
	return round1(percents[0])
}

// collectCPUSince reports the CPU share since prev, the sample the last successful push saved, and
// returns the current sample for the next run (nil if the CPU times are unreadable). Without a usable
// prev it takes the 1s sample.
func collectCPUSince(prev *cpuSample, now time.Time) (float64, *cpuSample) {
	times, err := cpuCalls.times(false)
	if err != nil || len(times) == 0 {
		return collectCPU(), nil
	}
	total, busy := cpuBusyTimes(times[0])
	cur := &cpuSample{Unix: now.Unix(), Total: total, Busy: busy}
	if percent, ok := cpuPercentSince(prev, *cur); ok {
		return round1(percent), cur
	}
	return collectCPU(), cur
}

// cpuBusyTimes sums t as gopsutil's getAllBusy does for cpu.Percent (v4.26.5 cpu/cpu.go:106-116, not
// exported): the total leaves out the guest times on Linux, busy is the total without idle and iowait.
// Total() is not used, gopsutil marks it as internal.
func cpuBusyTimes(t cpu.TimesStat) (total, busy float64) {
	total = t.User + t.System + t.Idle + t.Nice + t.Iowait + t.Irq + t.Softirq + t.Steal + t.Guest + t.GuestNice
	if runtime.GOOS == "linux" {
		total -= t.Guest + t.GuestNice
	}
	return total, total - t.Idle - t.Iowait
}

// cpuPercentSince is gopsutil's calculateBusy (cpu/cpu.go:118-129) between two saved samples, limited
// to 0-100. ok is false when prev cannot open the window: missing, older than cpuStateMaxAge, from the
// future (clock set back) or with a total that did not grow (reboot), where calculateBusy would say 100.
func cpuPercentSince(prev *cpuSample, cur cpuSample) (float64, bool) {
	if prev == nil {
		return 0, false
	}
	age := cur.Unix - prev.Unix
	if age < 0 || age > int64(cpuStateMaxAge/time.Second) || cur.Total <= prev.Total {
		return 0, false
	}
	return math.Min(100, math.Max(0, (cur.Busy-prev.Busy)/(cur.Total-prev.Total)*100)), true
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
		if strings.HasPrefix(s, p) {
			return true
		}
	}
	return false
}

func round1(f float64) float64 {
	return math.Round(f*10) / 10
}

func round2(f float64) float64 {
	return math.Round(f*100) / 100
}
