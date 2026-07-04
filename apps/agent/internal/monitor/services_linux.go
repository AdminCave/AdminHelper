// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package monitor

import (
	"os/exec"
	"strings"
)

// collectServiceHealth collects systemd service status (port of collect_systemd_health).
func collectServiceHealth() map[string]any {
	result := map[string]any{
		"failed":           []string{},
		"enabled_inactive": []string{},
		"all_services":     []ServiceEntry{},
	}

	// 1) All service units with active_state (col 2 = UNIT LOAD ACTIVE SUB)
	unitStates := parseSystemctlColumns(2, "list-units", "--type=service", "--all",
		"--no-legend", "--plain", "--no-pager")

	// 2) Enabled state for all unit files (col 1 = UNIT STATE)
	enabledStates := parseSystemctlColumns(1, "list-unit-files", "--type=service",
		"--no-legend", "--no-pager")

	// 3) Failed units
	failed := []string{}
	out, err := exec.Command("systemctl", "list-units", "--state=failed",
		"--no-legend", "--plain").Output()
	if err == nil {
		for _, line := range strings.Split(strings.TrimSpace(string(out)), "\n") {
			if parts := strings.Fields(line); len(parts) > 0 && parts[0] != "" {
				failed = append(failed, parts[0])
			}
		}
	}
	result["failed"] = failed

	// Assemble all_services
	allUnits := map[string]bool{}
	for u := range unitStates {
		allUnits[u] = true
	}
	for u := range enabledStates {
		allUnits[u] = true
	}
	allServices := []ServiceEntry{}
	for unit := range allUnits {
		active := unitStates[unit]
		if active == "" {
			active = "unknown"
		}
		enabled := enabledStates[unit]
		if enabled == "" {
			enabled = "unknown"
		}
		allServices = append(allServices, ServiceEntry{
			"unit":          unit,
			"active_state":  active,
			"enabled_state": enabled,
		})
	}
	result["all_services"] = allServices

	// Legacy: enabled_inactive
	enabledInactive := []string{}
	for unit, active := range unitStates {
		if active == "inactive" && enabledStates[unit] == "enabled" {
			enabledInactive = append(enabledInactive, unit)
		}
	}
	result["enabled_inactive"] = enabledInactive

	return result
}

// parseSystemctlColumns runs `systemctl <args>` and maps each unit (field 0) to
// its column `col`, skipping lines too short to hold it. Empty map on any error.
func parseSystemctlColumns(col int, args ...string) map[string]string {
	m := map[string]string{}
	out, err := exec.Command("systemctl", args...).Output()
	if err != nil {
		return m
	}
	for _, line := range strings.Split(strings.TrimSpace(string(out)), "\n") {
		if parts := strings.Fields(line); len(parts) > col {
			m[parts[0]] = parts[col]
		}
	}
	return m
}

// collectWatchedServices checks the status of specific systemd services.
func collectWatchedServices(names []string) []map[string]any {
	var services []map[string]any
	for _, name := range names {
		svc := map[string]any{"name": name, "running": false, "pid": nil}
		// `--` terminates option parsing so a server-supplied service name
		// beginning with '-' is treated as an operand, not a systemctl flag
		// (argument/flag-confusion hardening; exec.Command uses no shell).
		out, err := exec.Command("systemctl", "is-active", "--", name).Output()
		if err == nil && strings.TrimSpace(string(out)) == "active" {
			svc["running"] = true
			pidOut, err := exec.Command("systemctl", "show", "-p", "MainPID", "--", name).Output()
			if err == nil {
				parts := strings.SplitN(strings.TrimSpace(string(pidOut)), "=", 2)
				if len(parts) == 2 && parts[1] != "0" && parts[1] != "" {
					svc["pid"] = parts[1]
				}
			}
		}
		services = append(services, svc)
	}
	return services
}
