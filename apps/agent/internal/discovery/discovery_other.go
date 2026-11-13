// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build !linux

package discovery

import "adminhelper-agent/internal/probe"

// Containers and units are discovered on Linux alone; seams for the tests.
var (
	cgroupsOf          = func(int32) probe.Cgroups { return nil }
	containerListening = func(int32) ([]uint16, error) { return nil, nil }
)
