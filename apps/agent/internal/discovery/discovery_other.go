// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build !linux

package discovery

import "adminhelper-agent/internal/probe"

// cgroupsOf: containers are discovered on Linux alone; a seam for the tests.
var cgroupsOf = func(int32) probe.Cgroups { return nil }
