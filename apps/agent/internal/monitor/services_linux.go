// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package monitor

import (
	"strings"
)

// collectServiceHealth collects systemd service status (port of collect_systemd_health).
func collectServiceHealth() map[string]any {
	// 1) All service units with active_state (col 2 = UNIT LOAD ACTIVE SUB)
	unitStates := parseSystemctlColumns(2, "list-units", "--type=service", "--all",
		"--no-legend", "--plain", "--no-pager")

	// 2) Enabled state for all unit files (col 1 = UNIT STATE)
	enabledStates := parseSystemctlColumns(1, "list-unit-files", "--type=service",
		"--no-legend", "--no-pager")

	// 3) Failed units
	failed := []string{}
	out, err := runWithTimeout("systemctl", "list-units", "--state=failed",
		"--no-legend", "--plain")
	if err == nil {
		for _, line := range strings.Split(strings.TrimSpace(string(out)), "\n") {
			if parts := strings.Fields(line); len(parts) > 0 && parts[0] != "" {
				failed = append(failed, parts[0])
			}
		}
	}

	// The failed/enabled_inactive/all_services derivation lives in assembleServiceHealth (pure) so
	// it is unit-tested without running systemctl (6.19).
	return assembleServiceHealth(unitStates, enabledStates, failed)
}

// assembleServiceHealth derives the service-health report from the parsed unit states: all_services
// is the union of both maps (missing side -> "unknown"), and enabled_inactive is the legacy set of
// units that are inactive yet enabled.
func assembleServiceHealth(unitStates, enabledStates map[string]string, failed []string) map[string]any {
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

	enabledInactive := []string{}
	for unit, active := range unitStates {
		if active == "inactive" && enabledStates[unit] == "enabled" {
			enabledInactive = append(enabledInactive, unit)
		}
	}

	if failed == nil {
		failed = []string{}
	}
	return map[string]any{
		"failed":           failed,
		"enabled_inactive": enabledInactive,
		"all_services":     allServices,
	}
}

// parseSystemctlColumns runs `systemctl <args>` and maps each unit (field 0) to
// its column `col`, skipping lines too short to hold it. Empty map on any error.
func parseSystemctlColumns(col int, args ...string) map[string]string {
	out, err := runWithTimeout("systemctl", args...)
	if err != nil {
		return map[string]string{}
	}
	return parseSystemctlColumnsOutput(string(out), col)
}

// parseSystemctlColumnsOutput maps each unit (field 0) to its column `col`, skipping lines too short
// to hold it — the positional parsing, testable without running systemctl (6.19).
func parseSystemctlColumnsOutput(out string, col int) map[string]string {
	m := map[string]string{}
	for _, line := range strings.Split(strings.TrimSpace(out), "\n") {
		if parts := strings.Fields(line); len(parts) > col {
			m[parts[0]] = parts[col]
		}
	}
	return m
}

// collectWatchedServices checks the status of specific systemd services.
func collectWatchedServices(names []string) []map[string]any {
	if len(names) == 0 {
		return nil
	}
	// One `systemctl show` for all watched units instead of is-active + show per unit — the 2N
	// process spawns + D-Bus roundtrips per cycle become one (5.7). `--` terminates option parsing
	// so a server-supplied name beginning with '-' is treated as an operand, not a systemctl flag
	// (argument/flag-confusion hardening; runWithTimeout runs exec directly, no shell).
	args := append([]string{"show", "-p", "Id,ActiveState,MainPID", "--"}, names...)
	out, err := runWithTimeout("systemctl", args...)
	if err != nil {
		services := make([]map[string]any, 0, len(names))
		for _, name := range names {
			services = append(services, map[string]any{"name": name, "running": false, "pid": nil})
		}
		return services
	}
	return parseWatchedServices(out, names)
}

// parseWatchedServices maps each requested name to its status from the blank-line-separated
// `systemctl show -p Id,ActiveState,MainPID` blocks. Keyed by the canonical Id so it doesn't rely on
// block order, and matches a bare "nginx" against "nginx.service" too. A name with no block stays
// not-running.
func parseWatchedServices(out []byte, names []string) []map[string]any {
	byID := map[string]map[string]string{}
	for _, block := range strings.Split(strings.TrimSpace(string(out)), "\n\n") {
		props := map[string]string{}
		for _, line := range strings.Split(block, "\n") {
			if kv := strings.SplitN(strings.TrimSpace(line), "=", 2); len(kv) == 2 {
				props[kv[0]] = kv[1]
			}
		}
		if id := props["Id"]; id != "" {
			byID[id] = props
		}
	}
	services := make([]map[string]any, 0, len(names))
	for _, name := range names {
		svc := map[string]any{"name": name, "running": false, "pid": nil}
		props, ok := byID[name]
		if !ok {
			props, ok = byID[name+".service"]
		}
		if ok && props["ActiveState"] == "active" {
			svc["running"] = true
			if pid := props["MainPID"]; pid != "0" && pid != "" {
				svc["pid"] = pid
			}
		}
		services = append(services, svc)
	}
	return services
}
