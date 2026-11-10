// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package discovery

import "adminhelper-agent/internal/probe"

// cgroupsOf returns the cgroups the process pid runs in; a seam for the tests.
var cgroupsOf = probe.CgroupsOf
