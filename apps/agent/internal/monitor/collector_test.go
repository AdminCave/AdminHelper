// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"encoding/json"
	"errors"
	"reflect"
	"testing"

	"github.com/shirou/gopsutil/v4/disk"
	"github.com/shirou/gopsutil/v4/mem"
)

func TestHasPrefix(t *testing.T) {
	prefixes := []string{"/sys", "/proc", "/dev/", "/run/snapd", "/snap"}

	cases := []struct {
		mount string
		want  bool
	}{
		{"/sys", true},
		{"/sys/kernel/debug", true},
		{"/proc/sys/fs", true},
		{"/dev/shm", true},
		{"/snap", true},
		{"/run/snapd/ns", true},
		{"/", false},
		{"/data", false},
		{"/home", false},
		// "/dev/" has the trailing slash so the /dev mountpoint itself passes.
		{"/dev", false},
		{"/run", false},
		{"", false},
	}
	for _, c := range cases {
		if got := hasPrefix(c.mount, prefixes); got != c.want {
			t.Errorf("hasPrefix(%q) = %v, erwartet %v", c.mount, got, c.want)
		}
	}
}

func TestHasPrefixEmptyList(t *testing.T) {
	if hasPrefix("/anything", nil) {
		t.Error("hasPrefix mit leerer Prefix-Liste muss false liefern")
	}
}

const mib = 1024 * 1024

// gib converts gigabytes to the bytes gopsutil reports.
func gib(f float64) uint64 {
	return uint64(f * (1 << 30))
}

// resourceStub stands in for resourceCalls: swap and count answer each read (swapErr and countErr
// fail them), reads counts both.
type resourceStub struct {
	swap     *mem.SwapMemoryStat
	swapErr  error
	count    int
	countErr error
	reads    int
}

// stubResources swaps resourceCalls for a host on goos with 8 CPUs and 84 of 2048 MB swap in use.
func stubResources(t *testing.T, goos string) *resourceStub {
	t.Helper()
	s := &resourceStub{
		swap:  &mem.SwapMemoryStat{Total: 2048 * mib, Used: 84*mib + 512, UsedPercent: 4.1015625},
		count: 8,
	}
	old := resourceCalls
	resourceCalls.goos = goos
	resourceCalls.swap = func() (*mem.SwapMemoryStat, error) {
		s.reads++
		if s.swapErr != nil {
			return nil, s.swapErr
		}
		return s.swap, nil
	}
	resourceCalls.counts = func(logical bool) (int, error) {
		s.reads++
		if !logical {
			t.Error("cpu count read physical cores, want logical CPUs")
		}
		return s.count, s.countErr
	}
	t.Cleanup(func() { resourceCalls = old })
	return s
}

func TestResourcesSwapAndCPUCount(t *testing.T) {
	cases := []struct {
		name  string
		setup func(s *resourceStub)
		want  string
	}{
		{"swap in use", func(*resourceStub) {},
			`{"cpu_count": 8, "swap_total_mb": 2048, "swap_used_mb": 84, "swap_percent": 4.1}`},
		// gopsutil reports 0 % without a swap device; that must not read as a healthy swap.
		{"no swap device", func(s *resourceStub) { s.swap = &mem.SwapMemoryStat{} },
			`{"cpu_count": 8, "swap_total_mb": 0, "swap_used_mb": 0}`},
		{"swap unreadable", func(s *resourceStub) { s.swapErr = errors.New("open /proc/vmstat") },
			`{"cpu_count": 8}`},
		{"cpu count unreadable", func(s *resourceStub) { s.countErr = errors.New("open /proc/stat") },
			`{"swap_total_mb": 2048, "swap_used_mb": 84, "swap_percent": 4.1}`},
		{"cpu count 0", func(s *resourceStub) { s.count = 0 },
			`{"swap_total_mb": 2048, "swap_used_mb": 84, "swap_percent": 4.1}`},
		{"both unreadable", func(s *resourceStub) {
			s.swapErr = errors.New("open /proc/vmstat")
			s.countErr = errors.New("open /proc/stat")
		}, `{}`},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			s := stubResources(t, "linux")
			c.setup(s)
			got := dockerWire(t, collectSwapAndCPUCount())
			if want := wantDockerWire(t, c.want); !reflect.DeepEqual(got, want) {
				t.Errorf("resources = %v, want %v", got, want)
			}
		})
	}
}

func TestResourcesWindowsHasNoSwapOrCPUCount(t *testing.T) {
	s := stubResources(t, "windows")
	if got := collectSwapAndCPUCount(); got != nil {
		t.Errorf("windows resources = %v, want nil", got)
	}
	if s.reads != 0 {
		t.Errorf("windows read swap or cpu count %d times, want none", s.reads)
	}
}

func TestResourcesInReport(t *testing.T) {
	keys := []string{"cpu_count", "swap_total_mb", "swap_used_mb", "swap_percent"}
	cases := []struct {
		goos string
		want map[string]any
	}{
		{"linux", map[string]any{"cpu_count": 8.0, "swap_total_mb": 2048.0, "swap_used_mb": 84.0, "swap_percent": 4.1}},
		{"windows", map[string]any{}},
	}
	for _, c := range cases {
		t.Run(c.goos, func(t *testing.T) {
			stubReportHost(t)
			stubResources(t, c.goos)
			resources, ok := BuildReport(nil)["resources"].(map[string]any)
			if !ok {
				t.Fatal("report has no resources")
			}
			wire := dockerWire(t, resources)
			got := map[string]any{}
			for _, k := range keys {
				if v, ok := wire[k]; ok {
					got[k] = v
				}
			}
			if !reflect.DeepEqual(got, c.want) {
				t.Errorf("swap and cpu count in the report = %v, want %v", got, c.want)
			}
		})
	}
}

// diskWire is d as the service receives it.
func diskWire(t *testing.T, d DiskInfo) map[string]any {
	t.Helper()
	raw, err := json.Marshal(d)
	if err != nil {
		t.Fatalf("marshal %+v: %v", d, err)
	}
	var wire map[string]any
	if err := json.Unmarshal(raw, &wire); err != nil {
		t.Fatalf("unmarshal %s: %v", raw, err)
	}
	return wire
}

func TestResourcesDiskInfo(t *testing.T) {
	root := disk.PartitionStat{Mountpoint: "/", Fstype: "ext4"}
	// Free is what non-root users may still write: the reserved blocks leave it below total - used.
	ext4 := disk.UsageStat{Total: gib(100), Used: gib(60), Free: gib(35.04), UsedPercent: 63.157894,
		InodesTotal: 6_553_600, InodesUsed: 808_000, InodesUsedPercent: 12.33}
	noInodes := ext4
	noInodes.InodesTotal, noInodes.InodesUsed, noInodes.InodesUsedPercent = 0, 0, 0
	freshInodes := ext4
	freshInodes.InodesUsed, freshInodes.InodesUsedPercent = 0, 0
	cases := []struct {
		name  string
		p     disk.PartitionStat
		usage disk.UsageStat
		goos  string
		want  string
	}{
		{"linux with inodes", root, ext4, "linux", `{"mount": "/", "fstype": "ext4", "percent": 63.2,
			"total_gb": 100, "used_gb": 60, "free_gb": 35, "inodes_percent": 12.3}`},
		// A filesystem with inodes but none used yet still reports its 0 %.
		{"linux with no inode used", root, freshInodes, "linux", `{"mount": "/", "fstype": "ext4",
			"percent": 63.2, "total_gb": 100, "used_gb": 60, "free_gb": 35, "inodes_percent": 0}`},
		{"linux without inodes (btrfs)", disk.PartitionStat{Mountpoint: "/srv", Fstype: "btrfs"}, noInodes,
			"linux", `{"mount": "/srv", "fstype": "btrfs", "percent": 63.2, "total_gb": 100, "used_gb": 60,
			"free_gb": 35}`},
		{"windows", disk.PartitionStat{Mountpoint: "C:", Fstype: "NTFS"}, noInodes, "windows",
			`{"mount": "C:", "fstype": "NTFS", "percent": 63.2, "total_gb": 100, "used_gb": 60, "free_gb": 35}`},
		{"windows ignores inode counts", disk.PartitionStat{Mountpoint: "C:", Fstype: "NTFS"}, ext4, "windows",
			`{"mount": "C:", "fstype": "NTFS", "percent": 63.2, "total_gb": 100, "used_gb": 60, "free_gb": 35}`},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got := diskWire(t, diskInfo(c.p, &c.usage, c.goos))
			if want := wantDockerWire(t, c.want); !reflect.DeepEqual(got, want) {
				t.Errorf("disk = %v, want %v", got, want)
			}
		})
	}
}
