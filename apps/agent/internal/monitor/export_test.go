// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"context"
	"testing"
)

// The hooks of the end-to-end tests of package push (push_test.go, package monitor_test).

// StubReportHost is stubReportHost.
var StubReportHost = stubReportHost

// LoadReportState is loadReportState.
var LoadReportState = loadReportState

// StubCPU stubs the CPU counters as stubCPU does; the returned func sets them to cpuTimes(busy, idle).
func StubCPU(t *testing.T) func(busy, idle float64) {
	t.Helper()
	s := stubCPU(t)
	return func(busy, idle float64) { s.times = cpuTimes(busy, idle) }
}

// StubDockerCollector puts f in place of the docker collector; StubReportHost restores it.
func StubDockerCollector(f func(context.Context) *DockerBlock) { pluginCollectors.docker = f }
