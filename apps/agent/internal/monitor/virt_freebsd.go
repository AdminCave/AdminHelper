// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build freebsd

package monitor

import "golang.org/x/sys/unix"

// virtualization reads the two sysctls freebsdVirtualization maps, without starting a process:
// gopsutil's host.Virtualization is not implemented on FreeBSD.
func virtualization() (system, role string, err error) {
	jailed, err := unix.SysctlUint32("security.jail.jailed")
	if err != nil {
		return "", "", err
	}
	vmGuest, err := unix.Sysctl("kern.vm_guest")
	if err != nil {
		return "", "", err
	}
	system, role = freebsdVirtualization(jailed == 1, vmGuest)
	return system, role, nil
}
