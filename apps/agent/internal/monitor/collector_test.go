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
	gnet "github.com/shirou/gopsutil/v4/net"
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
// fail them), reads counts both. net, loop and devices answer the network reads (netErr and
// loopErr fail them), deviceReads counts the device lookups.
type resourceStub struct {
	swap        *mem.SwapMemoryStat
	swapErr     error
	count       int
	countErr    error
	reads       int
	net         []gnet.IOCountersStat
	netErr      error
	loop        map[string]bool
	loopErr     error
	devices     map[string]bool
	deviceReads int
}

// stubResources swaps resourceCalls for a host on goos with 8 CPUs, 84 of 2048 MB swap in use and
// the interfaces of a Proxmox host: loopback, the NIC eno1, its bridge vmbr0 and a guest's tap.
func stubResources(t *testing.T, goos string) *resourceStub {
	t.Helper()
	s := &resourceStub{
		swap:  &mem.SwapMemoryStat{Total: 2048 * mib, Used: 84*mib + 512, UsedPercent: 4.1015625},
		count: 8,
		net: []gnet.IOCountersStat{
			{Name: "lo", BytesRecv: 7000, BytesSent: 7000},
			{Name: "eno1", BytesRecv: 5_000_000_000, BytesSent: 2_000_000_000},
			{Name: "vmbr0", BytesRecv: 4_900_000_000, BytesSent: 1_900_000_000},
			{Name: "tap100i0", BytesRecv: 300, BytesSent: 400},
		},
		loop:    map[string]bool{"lo": true},
		devices: map[string]bool{"eno1": true},
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
	resourceCalls.netIO = func(pernic bool) ([]gnet.IOCountersStat, error) {
		if !pernic {
			t.Error("network read the all-interface total, want per interface")
		}
		return s.net, s.netErr
	}
	resourceCalls.loopback = func() (map[string]bool, error) { return s.loop, s.loopErr }
	resourceCalls.device = func(name string) bool {
		s.deviceReads++
		return s.devices[name]
	}
	t.Cleanup(func() { resourceCalls = old })
	return s
}

func TestResourcesNetwork(t *testing.T) {
	container := []gnet.IOCountersStat{
		{Name: "lo", BytesRecv: 7000, BytesSent: 7000},
		{Name: "eth0", BytesRecv: 1234, BytesSent: 5678},
	}
	cases := []struct {
		name  string
		goos  string
		setup func(s *resourceStub)
		want  string // "" = no fields at all
	}{
		// The bridge and the tap carry what eno1 already counted.
		{"host with a NIC", "linux", func(*resourceStub) {},
			`{"net_rx_bytes_total": 5000000000, "net_tx_bytes_total": 2000000000}`},
		{"container without a device", "linux", func(s *resourceStub) {
			s.net = container
			s.devices = map[string]bool{}
		}, `{"net_rx_bytes_total": 1234, "net_tx_bytes_total": 5678}`},
		{"windows counts every non-loopback interface", "windows", func(*resourceStub) {},
			`{"net_rx_bytes_total": 9900000300, "net_tx_bytes_total": 3900000400}`},
		{"only loopback", "linux", func(s *resourceStub) { s.net = s.net[:1] }, ""},
		{"counters unreadable", "linux", func(s *resourceStub) { s.netErr = errors.New("open /proc/net/dev") }, ""},
		// Without the loopback flags lo would count into the sum of a container.
		{"interfaces unreadable", "linux", func(s *resourceStub) { s.loopErr = errors.New("netlink") }, ""},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			s := stubResources(t, c.goos)
			c.setup(s)
			n := collectNetwork()
			if c.want == "" {
				if n != nil {
					t.Errorf("network = %v, want no fields", n)
				}
				return
			}
			if got, want := dockerWire(t, n), wantDockerWire(t, c.want); !reflect.DeepEqual(got, want) {
				t.Errorf("network = %v, want %v", got, want)
			}
			if c.goos == "windows" && s.deviceReads != 0 {
				t.Errorf("windows looked up %d Linux devices, want none", s.deviceReads)
			}
		})
	}
}

func TestResourcesSwapAndCPUCount(t *testing.T) {
	cases := []struct {
		name  string
		setup func(s *resourceStub, goos string)
		want  string
	}{
		{"swap in use", func(*resourceStub, string) {},
			`{"cpu_count": 8, "swap_total_mb": 2048, "swap_used_mb": 84, "swap_percent": 4.1}`},
		// gopsutil reports 0 % without a swap device on Linux and an error on FreeBSD
		// (mem_freebsd.go, vm.nswapdev 0); either must read as 0 MB, not as a healthy swap.
		{"no swap device", func(s *resourceStub, goos string) {
			if goos == "freebsd" {
				s.swapErr = errors.New("no swap devices found")
			} else {
				s.swap = &mem.SwapMemoryStat{}
			}
		},
			`{"cpu_count": 8, "swap_total_mb": 0, "swap_used_mb": 0}`},
		{"swap unreadable", func(s *resourceStub, _ string) { s.swapErr = errors.New("open /proc/vmstat") },
			`{"cpu_count": 8}`},
		{"cpu count unreadable", func(s *resourceStub, _ string) { s.countErr = errors.New("open /proc/stat") },
			`{"swap_total_mb": 2048, "swap_used_mb": 84, "swap_percent": 4.1}`},
		{"cpu count 0", func(s *resourceStub, _ string) { s.count = 0 },
			`{"swap_total_mb": 2048, "swap_used_mb": 84, "swap_percent": 4.1}`},
		{"both unreadable", func(s *resourceStub, _ string) {
			s.swapErr = errors.New("open /proc/vmstat")
			s.countErr = errors.New("open /proc/stat")
		}, `{}`},
	}
	// FreeBSD reports the same fields: its load is rated per CPU like Linux's (R-1253).
	for _, goos := range []string{"linux", "freebsd"} {
		for _, c := range cases {
			t.Run(goos+"/"+c.name, func(t *testing.T) {
				s := stubResources(t, goos)
				c.setup(s, goos)
				got := dockerWire(t, collectSwapAndCPUCount())
				if want := wantDockerWire(t, c.want); !reflect.DeepEqual(got, want) {
					t.Errorf("resources = %v, want %v", got, want)
				}
			})
		}
	}
}

// Only FreeBSD's gopsutil uses that error for "no swap"; on Linux it stays an unreadable swap.
func TestResourcesNoSwapErrorIsZeroOnlyOnFreeBSD(t *testing.T) {
	s := stubResources(t, "linux")
	s.swapErr = errors.New("no swap devices found")
	got := dockerWire(t, collectSwapAndCPUCount())
	if want := wantDockerWire(t, `{"cpu_count": 8}`); !reflect.DeepEqual(got, want) {
		t.Errorf("resources = %v, want %v", got, want)
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
	keys := []string{"cpu_count", "swap_total_mb", "swap_used_mb", "swap_percent", "net_rx_bytes_total", "net_tx_bytes_total"}
	cases := []struct {
		goos string
		want map[string]any
	}{
		{"linux", map[string]any{"cpu_count": 8.0, "swap_total_mb": 2048.0, "swap_used_mb": 84.0, "swap_percent": 4.1,
			"net_rx_bytes_total": 5e9, "net_tx_bytes_total": 2e9}},
		{"windows", map[string]any{"net_rx_bytes_total": 9900000300.0, "net_tx_bytes_total": 3900000400.0}},
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
				t.Errorf("swap, cpu count and network in the report = %v, want %v", got, c.want)
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

func TestSkipFSTypesFreeBSD(t *testing.T) {
	// FreeBSD's pseudo filesystems and nullfs (a directory of another filesystem mounted again, as in
	// jails) store nothing of their own, tmpfs nothing on a disk (same name as on Linux); ufs, zfs,
	// msdosfs and nfs do.
	for _, fstype := range []string{"devfs", "fdescfs", "procfs", "linprocfs", "linsysfs", "nullfs", "tmpfs"} {
		if !skipFSTypes[fstype] {
			t.Errorf("%s is not skipped", fstype)
		}
	}
	for _, fstype := range []string{"ufs", "zfs", "msdosfs", "nfs"} {
		if skipFSTypes[fstype] {
			t.Errorf("%s is skipped, it stores files of its own", fstype)
		}
	}
}
