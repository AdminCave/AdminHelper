// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package monitor

import (
	"syscall"
	"time"
)

// processCPUTime is the user and kernel time of the agent; Windows counts no time of ended children
// to it. 0 where GetProcessTimes fails.
func processCPUTime() time.Duration {
	h, err := syscall.GetCurrentProcess()
	if err != nil {
		return 0
	}
	var creation, exit, kernel, user syscall.Filetime
	if syscall.GetProcessTimes(h, &creation, &exit, &kernel, &user) != nil {
		return 0
	}
	return filetimeDuration(kernel) + filetimeDuration(user)
}

// filetimeDuration is a FILETIME that counts a duration in 100 ns. Filetime.Nanoseconds would take it
// for a point in time and subtract the 1601 epoch.
func filetimeDuration(ft syscall.Filetime) time.Duration {
	return time.Duration(int64(ft.HighDateTime)<<32|int64(ft.LowDateTime)) * 100
}
