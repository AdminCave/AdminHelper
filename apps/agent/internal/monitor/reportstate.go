// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"encoding/json"
	"os"
)

// reportState is what the next report is measured against, persisted in config.MonitorReportStateFile
// between two runs of the oneshot. Push saves it only after a successful push, like the inventory
// state: a lost push then widens the next CPU window instead of dropping a part of it, and its OOM
// kills count again in the next report.
type reportState struct {
	CPU *cpuSample `json:"cpu,omitempty"`
	// OOMKill is the oom_kill counter of /proc/vmstat at the last report (Linux only). A pointer, so a
	// host that never killed a process keeps its 0 and the next report counts from it.
	OOMKill *uint64 `json:"oom_kill,omitempty"`
	// Updates is the last hourly count of pending security updates (Linux only).
	Updates *updatesCheck `json:"updates,omitempty"`
}

// updatesCheck is one count of pending security updates, taken at CheckedUnix. Security is nil when the
// count failed: a failed count is the hour's attempt as well.
type updatesCheck struct {
	CheckedUnix int64 `json:"checked_unix"`
	Security    *int  `json:"security"`
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
	return os.WriteFile(path, data, 0600)
}
