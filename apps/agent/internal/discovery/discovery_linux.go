// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package discovery

import "adminhelper-agent/internal/probe"

// Seams for the tests: the cgroups the process pid runs in, the ports something listens on in its
// network namespace.
var (
	cgroupsOf          = probe.CgroupsOf
	containerListening = probe.ContainerListening
)
