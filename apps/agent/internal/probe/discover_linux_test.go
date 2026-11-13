// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package probe

import (
	"encoding/binary"
	"fmt"
	"net/netip"
	"slices"
	"strings"
	"testing"
)

func TestCgroupsTellTheContainerAProcessRunsIn(t *testing.T) {
	a, b, c := strings.Repeat("a", 64), strings.Repeat("b", 64), strings.Repeat("c", 64)
	stubProc(t, map[string]string{
		// The first processes of two containers, under cgroup v2 and v1.
		"/proc/100/cgroup": "0::/system.slice/docker-" + b + ".scope\n",
		"/proc/200/cgroup": "12:pids:/docker/" + a + "\n11:memory:/docker/" + a + "\n1:name=systemd:/\n",
		"/proc/7/cgroup":   "0::/system.slice/docker-" + b + ".scope\n",
		"/proc/8/cgroup":   "12:pids:/docker/" + a + "/worker\n11:memory:/docker/" + a + "\n1:name=systemd:/\n",
		"/proc/9/cgroup":   "0::/system.slice/nginx.service\n",
		// Named like a container's cgroup, in the cgroup delegated to a user or beside the container's.
		"/proc/10/cgroup": "0::/user.slice/user-1000.slice/user@1000.service/docker-" + b + ".scope\n",
		"/proc/11/cgroup": "0::/system.slice/docker-" + b + ".scope2\n",
		// Only in the root of a hierarchy the container shares with every process.
		"/proc/12/cgroup": "12:pids:/\n11:memory:/user.slice\n1:name=systemd:/\n",
		// Hybrid mode: a container whose unified hierarchy names a cgroup it shares with host
		// processes; only a process in its own cgroups of every hierarchy runs in it.
		"/proc/300/cgroup": "12:pids:/docker/" + c + "\n0::/system.slice/containerd.service\n",
		"/proc/14/cgroup":  "12:pids:/\n0::/system.slice/containerd.service\n",
		"/proc/15/cgroup":  "12:pids:/docker/" + c + "/sub\n0::/system.slice/containerd.service\n",
	})
	containers := map[string]Cgroups{"a": CgroupsOf(200), "b": CgroupsOf(100), "c": CgroupsOf(300)}
	for _, c := range []struct {
		pid  int32
		want string
	}{
		{7, "b"},
		{8, "a"},
		{9, ""},
		{10, ""},
		{11, ""},
		{12, ""},
		{14, ""},
		{15, "c"},
		// A process that cannot be read runs in none.
		{13, ""},
	} {
		got := ""
		own := CgroupsOf(c.pid)
		for _, name := range []string{"a", "b", "c"} {
			if containers[name].Holds(own) {
				got += name
			}
		}
		if got != c.want {
			t.Errorf("process %d runs in %q, want %q", c.pid, got, c.want)
		}
	}
	if CgroupsOf(13) != nil {
		t.Error("CgroupsOf of a process that cannot be read is not nil")
	}
	if Cgroups(nil).Holds(CgroupsOf(7)) || (Cgroups{"0:": "/"}).Holds(CgroupsOf(7)) {
		t.Error("no cgroups, or the root alone, hold a process")
	}
}

// procNetLine is a line of /proc/<pid>/net/tcp or tcp6 for addr:port in state st: each 32-bit word
// of the address as the number its bytes make in the host's byte order.
func procNetLine(addr string, port uint16, st string) string {
	b := netip.MustParseAddr(addr).AsSlice()
	hex := ""
	for i := 0; i < len(b); i += 4 {
		hex += fmt.Sprintf("%08X", binary.NativeEndian.Uint32(b[i:i+4]))
	}
	return fmt.Sprintf("   0: %s:%04X %s:0000 %s 00000000:00000000 00:00000000 00000000     0        0 1 1\n",
		hex, port, strings.Repeat("0", len(hex)), st)
}

const procNetHeader = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"

func TestContainerListeningLeavesLoopbackOut(t *testing.T) {
	stubProc(t, map[string]string{
		"/proc/4100/net/tcp": procNetHeader + procNetLine("0.0.0.0", 8000, "0A") +
			procNetLine("127.0.0.1", 9000, "0A") + procNetLine("192.0.2.5", 80, "0A") +
			procNetLine("192.0.2.5", 443, "01"),
		"/proc/4100/net/tcp6": procNetHeader + procNetLine("::", 8000, "0A") + procNetLine("::1", 5432, "0A") +
			procNetLine("2001:db8::5", 8443, "0A"),
		// Without IPv6 the kernel has no tcp6 file.
		"/proc/4200/net/tcp": procNetHeader + procNetLine("0.0.0.0", 3000, "0A"),
	})
	for _, c := range []struct {
		pid  int32
		want []uint16
	}{
		{4100, []uint16{80, 8000, 8443}},
		{4200, []uint16{3000}},
	} {
		got, err := ContainerListening(c.pid)
		if err != nil || !slices.Equal(got, c.want) {
			t.Errorf("ContainerListening(%d) = %v, %v, want %v", c.pid, got, err, c.want)
		}
	}
	if got, err := ContainerListening(13); err == nil {
		t.Errorf("ContainerListening of a process that cannot be read = %v, want an error", got)
	}
}
