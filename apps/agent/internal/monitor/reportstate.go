// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"encoding/json"
	"os"

	"adminhelper-agent/internal/config"
	"adminhelper-agent/internal/probe"
)

// reportState is what the next report is measured against, persisted in config.MonitorReportStateFile
// between two runs of the oneshot. Push saves it only after a successful push, like the inventory
// state: a lost push then widens the next CPU window instead of dropping a part of it, and its OOM
// kills count again in the next report. Probes, Throttle, Brake, Bindings and Cursors alone are saved after a
// lost push too (Push).
type reportState struct {
	CPU *cpuSample `json:"cpu,omitempty"`
	// OOMKill is the oom_kill counter at the last report (Linux only), read from OOMKillSource. A
	// pointer, so a host that never killed a process keeps its 0 and the next report counts from it.
	OOMKill *uint64 `json:"oom_kill,omitempty"`
	// OOMKillSource names where OOMKill was read (oomSourceVMStat or oomSourceCgroup): the counters of
	// two sources cannot be subtracted from each other.
	OOMKillSource string `json:"oom_kill_source,omitempty"`
	// Updates is the last hourly count of pending security updates (Linux and FreeBSD).
	Updates *updatesCheck `json:"updates,omitempty"`
	// Probes is the last result of every probe of the plan; its ts also says when the probe is due.
	Probes probe.Results `json:"probes,omitempty"`
	// Throttle is the self-throttle of the optional collectors and of the probe phase, by name.
	Throttle map[string]throttle `json:"throttle,omitempty"`
	// Brake is the access brake (probe.Access.Brake): by credential ref, the id of the credential its
	// target refused. The probes with it rest until it is set anew.
	Brake map[string]string `json:"brake,omitempty"`
	// Bindings is where each stored credential went first (probe.Access.Bindings), by credential ref.
	// Lost, it would let the next plan bind a credential to another target.
	Bindings map[string]probe.Binding `json:"bindings,omitempty"`
	// Cursors is where the last run of each counting probe stopped (probe.Access.Cursors), by probe id.
	// It goes with Probes: the next run of a probe counts from where the run of its kept result stopped.
	Cursors map[string]string `json:"cursors,omitempty"`
	// ProxmoxBackups is the last backup index read from the backup storages' content (Proxmox nodes
	// only). A state without it, saved by an older agent, reads them at once.
	ProxmoxBackups *backupIndexCheck `json:"proxmox_backups,omitempty"`
}

// The sources of the OOM kill counter: /proc/vmstat counts the kills of the whole kernel, the
// memory.events of a container's own cgroup only those inside the container.
const (
	oomSourceVMStat = "vmstat"
	oomSourceCgroup = "cgroup"
)

// oomKillSource is the source of OOMKill. A state saved before the source was recorded has none: its
// counter came from /proc/vmstat, the only source then.
func (st reportState) oomKillSource() string {
	if st.OOMKillSource == "" {
		return oomSourceVMStat
	}
	return st.OOMKillSource
}

// updatesCheck is one count of pending security updates, taken at CheckedUnix. Security is nil when the
// count failed: a failed count is the hour's attempt as well. Packages names the counted packages
// (packageNames); a state saved by an older agent has none until the next count.
type updatesCheck struct {
	CheckedUnix int64    `json:"checked_unix"`
	Security    *int     `json:"security"`
	Packages    []string `json:"packages,omitempty"`
}

// backupIndexCheck is one backup index of Node, read at CheckedUnix from the content of Storages
// (sorted): vmid -> newest backup ctime. Index has no omitempty: an empty index (no backups yet) must
// come back as one, not as nil, which counts as never read.
type backupIndexCheck struct {
	CheckedUnix int64         `json:"checked_unix"`
	Node        string        `json:"node"`
	Storages    []string      `json:"storages"`
	Index       map[int]int64 `json:"index"`
}

// cpuSample is the CPU time counted up to Unix, summed as cpuBusyTimes does.
type cpuSample struct {
	Unix  int64   `json:"unix"`
	Total float64 `json:"total"`
	Busy  float64 `json:"busy"`
}

// loadReportState reads the persisted state; any error (missing file, corrupt JSON) yields the empty
// state, so the report falls back to what a first run measures.
func loadReportState(path string) reportState {
	data, err := os.ReadFile(path)
	if err != nil {
		return reportState{}
	}
	var st reportState
	if err := json.Unmarshal(data, &st); err != nil {
		return reportState{}
	}
	return st
}

// saveReportState persists the state. A failure here must never fail a push that went through —
// callers only log it (the next run then takes the 1s CPU sample).
func saveReportState(path string, st reportState) error {
	data, err := json.Marshal(st)
	if err != nil {
		return err
	}
	return config.WriteFile(path, data, 0600)
}
