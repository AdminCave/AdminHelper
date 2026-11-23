// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

// SystemState is the system_state block. A field is set only when its platform measured it, and an
// unset one stays out of the wire: the server reads a missing field as not measured, not as false or 0.
type SystemState struct {
	OOMKills         *uint64      `json:"oom_kills,omitempty"`
	OOMProcesses     []oomProcess `json:"oom_processes,omitempty"`
	RebootRequired   *bool        `json:"reboot_required,omitempty"`
	RebootPackages   []string     `json:"reboot_packages,omitempty"`
	TimeSynchronized *bool        `json:"time_synchronized,omitempty"`
	SecurityUpdates  *int         `json:"security_updates,omitempty"`
	SecurityPackages []string     `json:"security_packages,omitempty"`
}

// oomProcess is a process the kernel's OOM killer killed, as oom_processes carries it.
type oomProcess struct {
	PID  int    `json:"pid"`
	Name string `json:"name"`
}

// empty reports whether s measured nothing; the report then leaves system_state out.
func (s *SystemState) empty() bool {
	return s == nil || s.OOMKills == nil && len(s.OOMProcesses) == 0 && s.RebootRequired == nil &&
		len(s.RebootPackages) == 0 && s.TimeSynchronized == nil && s.SecurityUpdates == nil &&
		len(s.SecurityPackages) == 0
}
