// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"os/exec"
	"runtime"

	"github.com/shirou/gopsutil/v4/host"
)

// hostSubsystems names each subsystem the report can carry and the binary that marks it, in report
// order.
var hostSubsystems = []struct{ name, binary string }{
	{"docker", "docker"},
	{"zfs", "zpool"},
	{"proxmox", "pvesh"},
}

// hostFactsCalls indirects collectHostFacts's gopsutil and binary lookups so tests can drive every
// path without depending on the host (same reason as pluginCollectors, 6.18). Two narrow calls
// rather than host.Info: Info fails as a whole on any part it cannot read (process count, boot time,
// host ID), which would cost the platform too. Neither has a timeout of its own: they read /etc,
// procfs or the registry and start no tool except lsb_release, which gopsutil caps at 3s.
var hostFactsCalls = struct {
	platform       func() (platform, family, version string, err error)
	virtualization func() (system, role string, err error)
	lookPath       func(file string) (string, error)
}{host.PlatformInformation, host.Virtualization, exec.LookPath}

// gopsutilNotImplemented is the text of gopsutil's ErrNotImplementedError. The sentinel lives in its
// internal/common, out of reach, so only the text can be compared (TestCollectHostFactsNotImplemented
// takes the real error from gopsutil).
const gopsutilNotImplemented = "not implemented yet"

// collectHostFacts reports what the monitoring service needs to suggest standard templates: the OS,
// platform and virtualization, and the subsystems whose binary is on the PATH. A failed part drops
// only its own fields, never the block. The subsystems are looked up here rather than taken from the
// plugin collectors, so a broken collector cannot hide them.
func collectHostFacts() map[string]any {
	facts := map[string]any{"os": runtime.GOOS}
	if platform, _, version, err := hostFactsCalls.platform(); hostFactsPartOK("platform", err) {
		facts["platform"] = platform
		facts["platform_version"] = version
	}
	if system, role, err := hostFactsCalls.virtualization(); hostFactsPartOK("virtualization", err) {
		facts["virtualization"] = map[string]string{"system": system, "role": role}
	}
	subsystems := []string{}
	for _, s := range hostSubsystems {
		if _, err := hostFactsCalls.lookPath(s.binary); err == nil {
			subsystems = append(subsystems, s.name)
		}
	}
	facts["subsystems"] = subsystems
	return facts
}

// hostFactsPartOK reports whether a gopsutil part of the host facts succeeded and logs why not.
// "Not implemented" (virtualization on Windows) counts as success with empty values, as in host.Info.
func hostFactsPartOK(part string, err error) bool {
	if err == nil || err.Error() == gopsutilNotImplemented {
		return true
	}
	logger.Warnf("host facts: %s: %v", part, err)
	return false
}
