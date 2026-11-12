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
	"regexp"
	"strconv"
	"strings"
	"time"
)

// vmstatPath is a variable so tests can point the OOM counter at a fixture.
var vmstatPath = "/proc/vmstat"

// memoryEventsPath is a variable so tests can point a container's OOM counter at a fixture. With
// cgroup v2 a container sees its own cgroup there, whose oom_kill counts the kills inside the
// container (hierarchical); the root cgroup of a host has no memory.events.
var memoryEventsPath = "/sys/fs/cgroup/memory.events"

// rebootRequiredPath is a variable so tests can point the Debian reboot flag at a fixture.
var rebootRequiredPath = "/var/run/reboot-required"

// rebootRequiredPkgsPath is a variable so tests can point the packages behind the Debian reboot flag at
// a fixture.
var rebootRequiredPkgsPath = "/var/run/reboot-required.pkgs"

// systemCLI indirects the lookups and calls of the system state tools (needs-restarting,
// timedatectl, journalctl) and the clock of the OOM window so tests can drive every path without them
// (same reason as dockerCLI). run runs one call under pluginTimeout and ctx. apt-get and dnf are looked
// up here as well, so the package family is told apart in one place; their update counts run through
// updatesCalls.
var systemCLI = struct {
	lookPath func(file string) (string, error)
	run      func(ctx context.Context, name string, args ...string) ([]byte, error)
	now      func() time.Time
}{exec.LookPath, runWithTimeout, time.Now}

// maxOOMProcesses caps the processes of oom_processes, maxOOMWindow the seconds of journal they are
// read from: a push lost while the server was away widens the window, the cap bounds what one call
// reads.
const (
	maxOOMProcesses = 10
	maxOOMWindow    = int64(time.Hour / time.Second)
)

// oomProcess is a process the kernel's OOM killer killed, as oom_processes carries it.
type oomProcess struct {
	PID  int    `json:"pid"`
	Name string `json:"name"`
}

// reOOMKilled finds the line the kernel logs for each OOM kill (mm/oom_kill.c, __oom_kill_process:
// "<cause>: Killed process <pid> (<comm>) total-vm:…", cause "Out of memory" or "Memory cgroup out of
// memory", without a colon); older kernels logged it without the cause (not verified here). It is no
// documented interface, so only pid and comm are read, and only from the start of a message: a kill
// line quoted in another message is no kill. comm is the process's own name and may hold spaces,
// colons and parentheses; everything after it is numbers, so the name runs to the last ") total-vm:".
var reOOMKilled = regexp.MustCompile(`^(?:[^:]*: )?Killed process ([0-9]+) \((.*)\) total-vm:`)

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
			kills := oomKillsSince(*st.OOMKill, count)
			block["oom_kills"] = kills
			// Only after a kill, and not in a container: the kernel log there is the host's, whose
			// kills its own counter leaves out.
			if kills > 0 && source == oomSourceVMStat {
				if processes := oomProcesses(ctx, oomWindow(st.CPU, systemCLI.now())); len(processes) > 0 {
					block["oom_processes"] = processes
				}
			}
		}
		st.OOMKill = &count
		st.OOMKillSource = source
	}
	if required, packages, ok := rebootRequired(ctx); ok {
		block["reboot_required"] = required
		if len(packages) > 0 {
			block["reboot_packages"] = packages
		}
	}
	if synced, ok := timeSynchronized(ctx); ok {
		block["time_synchronized"] = synced
	}
	st.Updates = securityUpdates(ctx, st.Updates)
	putSecurityUpdates(block, st.Updates)
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

// oomWindow is the journal window in seconds that holds the kills counted since the last report: from
// prev, the CPU sample the last successful push saved with the counter, up to now, rounded up, at most
// maxOOMWindow. Without a sample, or with one from the future (the clock was set back), it is the cap.
func oomWindow(prev *cpuSample, now time.Time) int64 {
	if prev == nil {
		return maxOOMWindow
	}
	seconds := now.Unix() - prev.Unix + 1
	if seconds < 1 || seconds > maxOOMWindow {
		return maxOOMWindow
	}
	return seconds
}

// oomProcesses names the processes the OOM killer killed in the last seconds, from the kernel's own
// lines in the journal (journalctl(1): --dmesg the kernel messages of this boot, --priority=3 err and
// above, the level of the kill line, --output=cat each bare message). Without journalctl, or when the
// call fails, it names none and the log says why; oom_kills stays as counted.
func oomProcesses(ctx context.Context, seconds int64) []oomProcess {
	if _, err := systemCLI.lookPath("journalctl"); err != nil {
		logger.Warnf("system state: journalctl not found, oom_processes left out")
		return nil
	}
	out, err := systemCLI.run(ctx, "journalctl", "--no-pager", "--quiet", "--dmesg", "--output=cat",
		"--priority=3", "--since=-"+strconv.FormatInt(seconds, 10)+"s")
	if err != nil {
		logger.Warnf("system state: journalctl --dmesg failed: %s, oom_processes left out",
			commandFailure("journalctl", pluginTimeout, err))
		return nil
	}
	return parseOOMProcesses(out)
}

// parseOOMProcesses reads the processes of the OOM kill lines in out, one message per line in the
// order logged, and drops every other line. It keeps the newest maxOOMProcesses, each name cut like a
// package name (the kernel's comm has at most 15 bytes, TASK_COMM_LEN).
func parseOOMProcesses(out []byte) []oomProcess {
	var processes []oomProcess
	for _, line := range strings.Split(string(out), "\n") {
		m := reOOMKilled.FindStringSubmatch(line)
		if m == nil {
			continue
		}
		pid, err := strconv.Atoi(m[1])
		if err != nil {
			continue
		}
		processes = append(processes, oomProcess{PID: pid, Name: capPackageName(m[2])})
	}
	return processes[max(0, len(processes)-maxOOMProcesses):]
}

// rebootRequired says whether the host waits for a reboot and, if so, names the packages behind it
// (packageNames) as far as the tool does; ok is false when that is unknown. The Debian family
// (apt-get on the path) flags it with /var/run/reboot-required, the RPM family answers through
// needs-restarting -r (exit 1: reboot needed). A host with neither has no tool to ask, which is no
// failure and stays out of the log (like docker not installed).
func rebootRequired(ctx context.Context) (required bool, packages []string, ok bool) {
	if _, err := systemCLI.lookPath("apt-get"); err == nil {
		_, err := os.Stat(rebootRequiredPath)
		if err == nil {
			return true, debianRebootPackages(), true
		}
		if errors.Is(err, fs.ErrNotExist) {
			return false, nil, true
		}
		// A flag it cannot check is unknown, not "no reboot needed".
		logger.Warnf("system state: %v, reboot_required left out", err)
		return false, nil, false
	}
	if _, err := systemCLI.lookPath("needs-restarting"); err != nil {
		return false, nil, false
	}
	out, err := systemCLI.run(ctx, "needs-restarting", "-r")
	if err == nil {
		return false, nil, true
	}
	var exitErr *exec.ExitError
	if errors.As(err, &exitErr) && exitErr.ExitCode() == 1 {
		return true, parseNeedsRestarting(out), true
	}
	logger.Warnf("system state: needs-restarting -r failed: %s, reboot_required left out",
		commandFailure("needs-restarting", pluginTimeout, err))
	return false, nil, false
}

// debianRebootPackages reads the packages that set the Debian reboot flag, one per line: each
// package's maintainer script appends its name through update-notifier's notify-reboot-required, so
// a name can stand there twice. Without the file (the flag set by other means) there are no names,
// which is no failure.
func debianRebootPackages() []string {
	data, err := os.ReadFile(rebootRequiredPkgsPath)
	if err != nil {
		if !errors.Is(err, fs.ErrNotExist) {
			logger.Warnf("system state: %v, reboot_packages left out", err)
		}
		return nil
	}
	return packageNames(strings.Fields(string(data)))
}

// parseNeedsRestarting names the packages in the output of needs-restarting -r: one "  * <name>" line
// each (dnf-plugins-core, plugins/needs_restarting.py), the lines around them translated. Output of
// another form names none.
func parseNeedsRestarting(out []byte) []string {
	var names []string
	for _, line := range strings.Split(string(out), "\n") {
		if name, ok := strings.CutPrefix(line, "  * "); ok {
			if name = strings.TrimSpace(name); name != "" {
				names = append(names, name)
			}
		}
	}
	return packageNames(names)
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
