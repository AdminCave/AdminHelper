// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package monitor

import (
	"context"
	"errors"
	"io/fs"
	"os"
	"os/exec"
	"strconv"
	"strings"
)

// vmstatPath is a variable so tests can point the OOM counter at a fixture.
var vmstatPath = "/proc/vmstat"

// memoryEventsPath is a variable so tests can point a container's OOM counter at a fixture. With
// cgroup v2 a container sees its own cgroup there, whose oom_kill counts the kills inside the
// container (hierarchical); the root cgroup of a host has no memory.events.
var memoryEventsPath = "/sys/fs/cgroup/memory.events"

// containerSystems are the virtualization systems gopsutil reports with the role guest for a
// container (v4.26.5, internal/common/common_linux.go, VirtualizationWithContext). It knows no Podman.
var containerSystems = map[string]bool{"openvz": true, "lxc": true, "docker": true, "rkt": true}

// rebootRequiredPath is a variable so tests can point the Debian reboot flag at a fixture.
var rebootRequiredPath = "/var/run/reboot-required"

// systemCLI indirects the lookups and calls of the system state tools (needs-restarting,
// timedatectl) so tests can drive every path without them (same reason as dockerCLI). run runs one
// call under pluginTimeout and ctx. apt-get and dnf are looked up here as well, so the package family
// is told apart in one place; their update counts run through updatesCalls.
var systemCLI = struct {
	lookPath func(file string) (string, error)
	run      func(ctx context.Context, name string, args ...string) ([]byte, error)
}{exec.LookPath, runWithTimeout}

// collectSystemState reports the system_state block and returns st, the state the last successful
// push saved, with what it measured replaced. A field is set only when measured; why one is missing
// goes to the log. A counter it cannot read keeps the saved one, so the next report still counts the
// OOM kills since the last counter it could read. ctx ends its tool calls.
func collectSystemState(ctx context.Context, st reportState) (map[string]any, reportState) {
	block := map[string]any{}
	if count, source, ok := readOOMKill(); ok {
		// The first run has no counter to count from, nor has a run that reads another source than the
		// saved counter came from (an agent update, a container detected anew): no field, only the
		// counter for the next one.
		if st.OOMKill != nil && st.oomKillSource() == source {
			block["oom_kills"] = oomKillsSince(*st.OOMKill, count)
		}
		st.OOMKill = &count
		st.OOMKillSource = source
	}
	if required, ok := rebootRequired(ctx); ok {
		block["reboot_required"] = required
	}
	if synced, ok := timeSynchronized(ctx); ok {
		block["time_synchronized"] = synced
	}
	st.Updates = securityUpdates(ctx, st.Updates)
	if st.Updates != nil && st.Updates.Security != nil {
		block["security_updates"] = *st.Updates.Security
	}
	return block, st
}

// readOOMKill reads the oom_kill counter and names its source; it logs why when it cannot. In a
// container /proc/vmstat counts the OOM kills of the whole host, so there it reads the counter of the
// container's own cgroup, and without cgroup v2 there is none.
func readOOMKill() (uint64, string, bool) {
	path, name, source := vmstatPath, "/proc/vmstat", oomSourceVMStat
	if inContainer() {
		path, name, source = memoryEventsPath, "memory.events", oomSourceCgroup
	}
	data, err := os.ReadFile(path)
	if err != nil {
		if source == oomSourceCgroup && errors.Is(err, fs.ErrNotExist) {
			logger.Warnf("system state: container without cgroup v2 memory.events, oom_kills left out")
		} else {
			logger.Warnf("system state: %v, oom_kills left out", err)
		}
		return 0, source, false
	}
	count, ok := parseOOMKill(data)
	if !ok {
		logger.Warnf("system state: no readable oom_kill counter in %s, oom_kills left out", name)
	}
	return count, source, ok
}

// inContainer tells a container from a host or a VM by the virtualization of the host facts, through
// the same call (hostFactsCalls). gopsutil detects it once per process and keeps the answer
// (internal/common/common_linux.go), so asking again in the same report reads no file. Without an
// answer it is no container, as for the monitoring service, whose report then has no virtualization.
func inContainer() bool {
	system, role, err := hostFactsCalls.virtualization()
	return err == nil && role == "guest" && containerSystems[system]
}

// parseOOMKill finds the line "oom_kill <n>" of /proc/vmstat or memory.events, both "name value"
// lines. proc_vmstat(5) documents those lines but not this counter (Linux 4.13 and later by the
// kernel source): a missing line or a value that is no counter is no counter.
func parseOOMKill(data []byte) (uint64, bool) {
	for _, line := range strings.Split(string(data), "\n") {
		fields := strings.Fields(line)
		if len(fields) == 2 && fields[0] == "oom_kill" {
			n, err := strconv.ParseUint(fields[1], 10, 64)
			return n, err == nil
		}
	}
	return 0, false
}

// oomKillsSince is the growth of the counter since saved. A smaller counter started again at a reboot
// since then, so all of its kills are new.
func oomKillsSince(saved, count uint64) uint64 {
	if count < saved {
		return count
	}
	return count - saved
}

// rebootRequired says whether the host waits for a reboot; ok is false when that is unknown. The
// Debian family (apt-get on the path) flags it with /var/run/reboot-required, the RPM family answers
// through needs-restarting -r (exit 1: reboot needed). A host with neither has no tool to ask, which
// is no failure and stays out of the log (like docker not installed).
func rebootRequired(ctx context.Context) (required, ok bool) {
	if _, err := systemCLI.lookPath("apt-get"); err == nil {
		_, err := os.Stat(rebootRequiredPath)
		if err == nil {
			return true, true
		}
		if errors.Is(err, fs.ErrNotExist) {
			return false, true
		}
		// A flag it cannot check is unknown, not "no reboot needed".
		logger.Warnf("system state: %v, reboot_required left out", err)
		return false, false
	}
	if _, err := systemCLI.lookPath("needs-restarting"); err != nil {
		return false, false
	}
	_, err := systemCLI.run(ctx, "needs-restarting", "-r")
	if err == nil {
		return false, true
	}
	var exitErr *exec.ExitError
	if errors.As(err, &exitErr) && exitErr.ExitCode() == 1 {
		return true, true
	}
	logger.Warnf("system state: needs-restarting -r failed: %s, reboot_required left out",
		commandFailure("needs-restarting", pluginTimeout, err))
	return false, false
}

// timeSynchronized says whether the kernel reports the clock as synchronized, the NTPSynchronized
// property of timedatectl show (org.freedesktop.timedate1(5)); ok is false when that is unknown, and
// the log names why.
func timeSynchronized(ctx context.Context) (synced, ok bool) {
	if _, err := systemCLI.lookPath("timedatectl"); err != nil {
		logger.Warnf("system state: timedatectl not found, time_synchronized left out")
		return false, false
	}
	out, err := systemCLI.run(ctx, "timedatectl", "show")
	if err != nil {
		logger.Warnf("system state: timedatectl show failed: %s, time_synchronized left out",
			commandFailure("timedatectl", pluginTimeout, err))
		return false, false
	}
	synced, ok = parseNTPSynchronized(out)
	if !ok {
		logger.Warnf("system state: no NTPSynchronized=yes|no in timedatectl show, time_synchronized left out")
	}
	return synced, ok
}

// parseNTPSynchronized finds the line "NTPSynchronized=yes|no". timedatectl(1) gives no example of
// the show output (the line is read from systemd 257) and documents -p only for show-timesync, so
// the line is searched for: a missing line or another value is no answer.
func parseNTPSynchronized(out []byte) (synced, ok bool) {
	for _, line := range strings.Split(string(out), "\n") {
		key, value, _ := strings.Cut(line, "=")
		if key != "NTPSynchronized" {
			continue
		}
		switch value {
		case "yes":
			return true, true
		case "no":
			return false, true
		}
		return false, false
	}
	return false, false
}
