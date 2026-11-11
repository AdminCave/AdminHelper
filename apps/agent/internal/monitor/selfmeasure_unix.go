// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build unix

package monitor

import (
	"syscall"
	"time"
)

// processCPUTime is the user and system time of the agent and of its ended children it waited for
// (the collectors' tools), 0 where getrusage fails.
func processCPUTime() time.Duration {
	var total time.Duration
	for _, who := range []int{syscall.RUSAGE_SELF, syscall.RUSAGE_CHILDREN} {
		var ru syscall.Rusage
		if syscall.Getrusage(who, &ru) != nil {
			continue
		}
		total += time.Duration(ru.Utime.Nano()) + time.Duration(ru.Stime.Nano())
	}
	return total
}
