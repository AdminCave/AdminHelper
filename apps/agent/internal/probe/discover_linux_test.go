// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package probe

import (
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
