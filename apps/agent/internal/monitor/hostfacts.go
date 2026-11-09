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
// procfs, sysctls or the registry and start no tool except lsb_release, which gopsutil caps at 3s.
// virtualization is gopsutil's except on FreeBSD (virt_freebsd.go, virt_other.go).
var hostFactsCalls = struct {
	platform       func() (platform, family, version string, err error)
	virtualization func() (system, role string, err error)
	lookPath       func(file string) (string, error)
}{host.PlatformInformation, virtualization, exec.LookPath}

// containerSystems are the virtualization systems reported with the role guest for a container:
// gopsutil's on Linux (v4.26.5, internal/common/common_linux.go, VirtualizationWithContext; it knows
// no Podman) and the jail on FreeBSD (freebsdVirtualization), which shares the host's kernel, load
// and boot as a container does.
var containerSystems = map[string]bool{"openvz": true, "lxc": true, "docker": true, "rkt": true, "jail": true}

// freebsdVirtualization maps FreeBSD's sysctls to the virtualization block: jailed is
// security.jail.jailed, vmGuest kern.vm_guest, the hypervisor the kernel detected ("none" without
// one; the names in sys/kern/subr_param.c). A jail wins over the VM it may run in: the agent
// watches the jail, not the VM.
func freebsdVirtualization(jailed bool, vmGuest string) (system, role string) {
	switch {
	case jailed:
		return "jail", "guest"
	case vmGuest != "" && vmGuest != "none":
		return vmGuest, "guest"
	}
	return "", ""
}

// inContainer tells a container from a host or a VM by the virtualization of the host facts, through
// the same call (hostFactsCalls). gopsutil detects it once per process and keeps the answer
// (internal/common/common_linux.go), so asking again in the same report reads no file; on FreeBSD it
// reads two sysctls. Without an answer it is no container, as for the monitoring service, whose
// report then has no virtualization.
func inContainer() bool {
	system, role, err := hostFactsCalls.virtualization()
	return err == nil && role == "guest" && containerSystems[system]
}

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
