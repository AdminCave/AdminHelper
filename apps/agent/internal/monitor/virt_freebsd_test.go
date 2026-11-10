// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build freebsd

package monitor

import (
	"os/exec"
	"strings"
	"testing"
)

// On FreeBSD virtualization reads the sysctls itself; sysctl(8) is the second witness.
func TestVirtualizationReadsTheSysctls(t *testing.T) {
	out, err := exec.Command("/sbin/sysctl", "-n", "security.jail.jailed", "kern.vm_guest").Output()
	if err != nil {
		t.Fatalf("sysctl: %v", err)
	}
	lines := strings.Fields(string(out))
	if len(lines) != 2 {
		t.Fatalf("sysctl printed %q, want two values", out)
	}
	wantSystem, wantRole := freebsdVirtualization(lines[0] == "1", lines[1])
	system, role, err := virtualization()
	if err != nil {
		t.Fatalf("virtualization: %v", err)
	}
	if system != wantSystem || role != wantRole {
		t.Errorf("virtualization = (%q, %q), sysctl says (%q, %q)", system, role, wantSystem, wantRole)
	}
}
