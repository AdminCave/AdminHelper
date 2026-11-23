// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"context"
	"errors"
	"fmt"
	"os/exec"
	"time"
)

// ServiceEntry is one service record in the all_services inventory (keys:
// unit, active_state, enabled_state, alias_of; optional state facts sub_state,
// since, restarts, result, exit, memory_bytes). Named alias so the wire contract between
// the platform collectors (services_linux.go / services_windows.go) and the
// throttle/hash logic (inventory.go) has a single anchor: change the element
// type here once instead of keeping three []map[string]string literals in sync.
type ServiceEntry = map[string]string

// ServiceHealth is the systemd block of the report, the same on every platform. omitzero keeps an
// empty list and leaves out one never set (nil): the server tells "no units" from "not collected",
// and a platform without a part (failed_details off Linux, counts after a failed call) sends no key.
type ServiceHealth struct {
	Failed          []string              `json:"failed,omitzero"`
	EnabledInactive []string              `json:"enabled_inactive,omitzero"`
	AllServices     []ServiceEntry        `json:"all_services,omitzero"`
	Counts          *ServiceCounts        `json:"counts,omitempty"`
	Error           string                `json:"error,omitempty"`
	FailedDetails   []FailedDetail        `json:"failed_details,omitzero"`
	Watched         []WatchedService      `json:"watched,omitzero"`
	LogUnits        []string              `json:"log_units,omitzero"`
	FailedLogs      map[string]ServiceLog `json:"failed_logs,omitempty"`
}

// ServiceCounts is the "x/y active" display of the loaded services (serviceCounts).
type ServiceCounts struct {
	Active int `json:"active"`
	Total  int `json:"total"`
}

// FailedDetail is one failed unit with the reason fields of its facts (failedDetails).
type FailedDetail struct {
	Unit     string `json:"unit"`
	Result   string `json:"result,omitempty"`
	Exit     string `json:"exit,omitempty"`
	Since    string `json:"since,omitempty"`
	Restarts string `json:"restarts,omitempty"`
}

// WatchedService is the state of one watched service name; PID is null while it does not run.
type WatchedService struct {
	Name    string  `json:"name"`
	Running bool    `json:"running"`
	PID     *string `json:"pid"`
}

// serviceCounts sums up the loaded services for the "x/y active" display: active are the entries
// whose active_state is "active", total all of them. Callers pass the loaded services only: on
// Linux the units list-units reports as loaded (not its not-found and masked units, nor the
// templates, aliases and unloaded unit files the inventory also lists), on Windows every service
// sc query lists. No .service suffix filter: Linux lists service units only (--type=service), and
// Windows service names carry no suffix.
func serviceCounts(entries []ServiceEntry) *ServiceCounts {
	active := 0
	for _, e := range entries {
		if e["active_state"] == "active" {
			active++
		}
	}
	return &ServiceCounts{Active: active, Total: len(entries)}
}

// answered reports whether a failed call of a service tool (systemctl, service) still answered,
// i.e. exited non-zero on its own, rather than being ended by the timeout or the end of ctx
// (context.DeadlineExceeded or context.Canceled from runWithTimeout), killed by a signal (exit code
// -1) or never started. So the per-unit calls also end with ctx: once it has ended, the next call
// returns its error unstarted.
func answered(err error) bool {
	var exitErr *exec.ExitError
	return errors.As(err, &exitErr) && exitErr.ExitCode() > 0
}

// commandFailure is the short reason for a failed call of the command name: that it ran into
// timeout, the limit the caller ran it under (runTimed), that the run was canceled, its exit status
// or signal, or that the command did not start. Never stderr or the error text, which can name paths
// (fork/exec <path>).
func commandFailure(name string, timeout time.Duration, err error) string {
	if errors.Is(err, context.DeadlineExceeded) {
		return fmt.Sprintf("timed out after %s", timeout)
	}
	if errors.Is(err, context.Canceled) {
		return "canceled before it ended"
	}
	if errors.Is(err, errCommandNotAllowed) {
		return name + " call not on the command allowlist"
	}
	var exitErr *exec.ExitError
	if errors.As(err, &exitErr) {
		return exitErr.Error()
	}
	return name + " did not start"
}
