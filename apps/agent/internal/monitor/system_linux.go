// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package monitor

import (
	"os"
	"strconv"
	"strings"
)

// vmstatPath is a variable so tests can point the OOM counter at a fixture.
var vmstatPath = "/proc/vmstat"

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
