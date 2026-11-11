// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build !freebsd

package monitor

import "github.com/shirou/gopsutil/v4/host"

// virtualization is gopsutil's on every system but FreeBSD (virt_freebsd.go).
func virtualization() (system, role string, err error) {
	return host.Virtualization()
}
