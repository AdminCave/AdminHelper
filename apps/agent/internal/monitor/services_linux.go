// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package monitor

import (
	"errors"
	"os/exec"
	"sort"
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
	health := assembleServiceHealth(unitStates, enabledStates, failed)
	health["enabled_inactive"] = filterEnabledInactive(health["enabled_inactive"].([]string))
	return health
}

// assembleServiceHealth derives the service-health report from the parsed unit states: all_services
// is the union of both maps (missing side -> "unknown"), and enabled_inactive holds the sorted
// candidates that are inactive yet enabled, before filterEnabledInactive re-checks them.
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
	// Sorted, so the single-query cap of filterEnabledInactive always checks the same units.
	sort.Strings(enabledInactive)

	if failed == nil {
		failed = []string{}
	}
	return map[string]any{
		"failed":           failed,
		"enabled_inactive": enabledInactive,
		"all_services":     allServices,
	}
}

// enabledInactiveProps are the properties filterEnabledInactive reads per candidate.
const enabledInactiveProps = "Id,Names,Type,Result,ConditionResult,TriggeredBy,ConditionTimestampMonotonic"

// maxSingleUnitChecks caps the per-unit fallback after a failed batch (Kevin 2026-10-16); the
// candidates beyond it stay unchecked.
const maxSingleUnitChecks = 50

// runSystemctl indirects the systemctl calls of filterEnabledInactive so tests can drive the batch
// and per-unit paths without systemctl (same reason as serviceHealthCollector, 6.18).
var runSystemctl = func(args ...string) ([]byte, error) {
	return runWithTimeout("systemctl", args...)
}

// filterEnabledInactive re-checks the enabled-but-inactive candidates with one batched
// `systemctl show` and drops the units that are inactive by design (inactiveByDesign). If systemctl
// answers the batch with a non-zero exit (one bad name spoils it), up to maxSingleUnitChecks
// candidates are asked one by one; a unit whose query fails, or beyond the cap, stays a candidate.
func filterEnabledInactive(candidates []string) []string {
	if len(candidates) == 0 {
		return candidates
	}
	out, err := runSystemctl(append([]string{"show", "-p", enabledInactiveProps, "--"}, candidates...)...)
	if err == nil {
		return parseEnabledInactive(out, candidates)
	}
	// Only a systemctl that answered gets the per-unit fallback, and the fallback ends at the first
	// call that did not: each such call waits pluginTimeout, and 50 of them (750 s) would outlast the
	// agent unit's TimeoutStartSec=270 and cost the whole report.
	if !answered(err) {
		return candidates
	}
	kept := make([]string, 0, len(candidates))
	asking := true
	for i, unit := range candidates {
		if asking && i < maxSingleUnitChecks {
			out, err := runSystemctl("show", "-p", enabledInactiveProps, "--", unit)
			if err == nil {
				kept = append(kept, parseEnabledInactive(out, []string{unit})...)
				continue
			}
			asking = answered(err)
		}
		kept = append(kept, unit)
	}
	return kept
}

// answered reports whether a failed systemctl call still answered, i.e. exited non-zero on its own,
// rather than being killed by the timeout (exit code -1) or never started.
func answered(err error) bool {
	var exitErr *exec.ExitError
	return errors.As(err, &exitErr) && exitErr.ExitCode() > 0
}

// parseEnabledInactive keeps the candidates whose blank-line-separated `systemctl show` block does
// not mark them inactive by design. Blocks are matched by Id and every name in Names, independent
// of their order; a candidate without a block stays.
func parseEnabledInactive(out []byte, candidates []string) []string {
	byName := map[string]map[string]string{}
	for _, block := range strings.Split(strings.TrimSpace(string(out)), "\n\n") {
		props := map[string]string{}
		for _, line := range strings.Split(block, "\n") {
			if kv := strings.SplitN(strings.TrimSpace(line), "=", 2); len(kv) == 2 {
				props[kv[0]] = kv[1]
			}
		}
		for _, name := range append(strings.Fields(props["Names"]), props["Id"]) {
			if name != "" {
				byName[name] = props
			}
		}
	}
	kept := make([]string, 0, len(candidates))
	for _, unit := range candidates {
		if props, ok := byName[unit]; ok && inactiveByDesign(props) {
			continue
		}
		kept = append(kept, unit)
	}
	return kept
}

// inactiveByDesign reports a unit that is not running on purpose: one started by a timer, socket or
// path unit, or, if systemd tried to start it, a oneshot that finished successfully
// (RemainAfterExit= defaults to no, systemd.service(5)) or a unit whose conditions did not hold.
// Result=success and ConditionResult=no are also the defaults of a unit systemd never tried to
// start (ConditionTimestampMonotonic=0), e.g. one whose start job failed on a dependency or whose
// target was never reached; such a unit stays a candidate. A missing or empty property drops nothing.
func inactiveByDesign(props map[string]string) bool {
	if props["TriggeredBy"] != "" {
		return true
	}
	if ts := props["ConditionTimestampMonotonic"]; ts == "" || ts == "0" {
		return false
	}
	return (props["Type"] == "oneshot" && props["Result"] == "success") || props["ConditionResult"] == "no"
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
