// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package monitor

import (
	"errors"
	"io/fs"
	"os"
	"os/exec"
	"strconv"
	"strings"
)

// vmstatPath is a variable so tests can point the OOM counter at a fixture.
var vmstatPath = "/proc/vmstat"

// rebootRequiredPath is a variable so tests can point the Debian reboot flag at a fixture.
var rebootRequiredPath = "/var/run/reboot-required"

// systemCLI indirects the lookups and calls of the system state tools (needs-restarting,
// timedatectl) so tests can drive every path without them (same reason as dockerCLI). run runs one
// call under pluginTimeout.
var systemCLI = struct {
	lookPath func(file string) (string, error)
	run      func(name string, args ...string) ([]byte, error)
}{exec.LookPath, runWithTimeout}

// collectSystemState reports the system_state block and returns st, the state the last successful
// push saved, with what it measured replaced. A field is set only when measured; why one is missing
// goes to the log. A counter it cannot read keeps the saved one, so the next report still counts the
// OOM kills since the last counter it could read.
func collectSystemState(st reportState) (map[string]any, reportState) {
	block := map[string]any{}
	if count, ok := readOOMKill(); ok {
		// The first run has no counter to count from: no field, only the counter for the next one.
		if st.OOMKill != nil {
			block["oom_kills"] = oomKillsSince(*st.OOMKill, count)
		}
		st.OOMKill = &count
	}
	if required, ok := rebootRequired(); ok {
		block["reboot_required"] = required
	}
	if synced, ok := timeSynchronized(); ok {
		block["time_synchronized"] = synced
	}
	return block, st
}

// readOOMKill reads the oom_kill counter from /proc/vmstat and logs why when it cannot.
func readOOMKill() (uint64, bool) {
	data, err := os.ReadFile(vmstatPath)
	if err != nil {
		logger.Warnf("system state: %v, oom_kills left out", err)
		return 0, false
	}
	count, ok := parseOOMKill(data)
	if !ok {
		logger.Warnf("system state: no readable oom_kill counter in /proc/vmstat, oom_kills left out")
	}
	return count, ok
}

// parseOOMKill finds the line "oom_kill <n>". proc_vmstat(5) documents the "name value" lines but not
// this counter (Linux 4.13 and later by the kernel source): a missing line or a value that is no
// counter is no counter.
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
func rebootRequired() (required, ok bool) {
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
	_, err := systemCLI.run("needs-restarting", "-r")
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
func timeSynchronized() (synced, ok bool) {
	if _, err := systemCLI.lookPath("timedatectl"); err != nil {
		logger.Warnf("system state: timedatectl not found, time_synchronized left out")
		return false, false
	}
	out, err := systemCLI.run("timedatectl", "show")
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
