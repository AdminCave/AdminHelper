// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package monitor

import (
	"context"
	"errors"
	"os/exec"
	"sort"
	"strings"
)

// collectServiceHealth collects systemd service status (port of collect_systemd_health). ctx ends
// every systemctl call.
func collectServiceHealth(ctx context.Context) map[string]any {
	// 1) All service units with load state (col 1) and active_state (col 2 = UNIT LOAD ACTIVE SUB)
	unitStates, loadStates := map[string]string{}, map[string]string{}
	listUnits, unitsErr := runSystemctl(ctx, "list-units", "--type=service", "--all",
		"--no-legend", "--plain", "--no-pager")
	if unitsErr == nil {
		unitStates = parseSystemctlColumnsOutput(string(listUnits), 2)
		loadStates = parseSystemctlColumnsOutput(string(listUnits), 1)
		// list-units --all also lists a unit that is not installed, only because another unit
		// references it (not-found inactive). In the inventory it would be inactive, i.e. down for the
		// server's list mode, where a name with no unit at all is nodata. One still running or failed
		// stays.
		for unit, load := range loadStates {
			if load == "not-found" && unitStates[unit] == "inactive" {
				delete(unitStates, unit)
			}
		}
	}

	// 2) Enabled state for all unit files (col 1 = UNIT STATE)
	enabledStates, _ := parseSystemctlColumns(ctx, 1, "list-unit-files", "--type=service",
		"--no-legend", "--no-pager")

	// 3) Failed units
	failed := []string{}
	out, err := runSystemctl(ctx, "list-units", "--state=failed", "--no-legend", "--plain")
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
	health["enabled_inactive"] = filterEnabledInactive(ctx, health["enabled_inactive"].([]string))
	resolveAliases(ctx, health["all_services"].([]ServiceEntry))
	// Without list-units every active state is unknown and no unit is a candidate: counts would
	// claim zero active units, and without the error the server would report "all OK".
	if unitsErr != nil {
		health["error"] = "systemctl list-units failed: " +
			commandFailure("systemctl", pluginTimeout, unitsErr)
	} else {
		// list-units --all also lists units without a unit file (not-found) and masked units that
		// something still references; neither is a loaded service.
		loaded := make([]ServiceEntry, 0, len(unitStates))
		for _, e := range health["all_services"].([]ServiceEntry) {
			_, listed := unitStates[e["unit"]]
			if load := loadStates[e["unit"]]; listed && load != "not-found" && load != "masked" {
				loaded = append(loaded, e)
			}
		}
		health["counts"] = serviceCounts(loaded)
	}
	return health
}

// aliasProps are the properties resolveAliases reads per alias: the alias stands in Names, its
// target in Id.
const aliasProps = "Id,Names"

// resolveAliases sets alias_of on the inventory entries list-unit-files reports as alias, from one
// batched `systemctl show`, so the server can match a watched alias (sshd) against its unit
// (ssh.service). Templates (name@.service) stay out: systemctl rejects a template name and fails the
// whole call. A failed call resolves nothing, since a call killed by the timeout can end in a
// truncated Id; an alias whose Id is its own name (no target) gets no alias_of.
func resolveAliases(ctx context.Context, entries []ServiceEntry) {
	aliases := map[string]ServiceEntry{}
	names := []string{}
	for _, e := range entries {
		if e["enabled_state"] == "alias" && !strings.HasSuffix(e["unit"], "@.service") {
			aliases[e["unit"]] = e
			names = append(names, e["unit"])
		}
	}
	if len(names) == 0 {
		return
	}
	out, err := runSystemctl(ctx, append([]string{"show", "-p", aliasProps, "--"}, names...)...)
	if err != nil {
		return
	}
	blocks := parseShowBlocks(out)
	for name, e := range aliases {
		if id := blocks[name]["Id"]; id != "" && id != name {
			e["alias_of"] = id
		}
	}
}

// assembleServiceHealth derives the service-health report from the parsed unit states: all_services
// is the union of both maps (missing side -> "unknown") sorted by unit, and enabled_inactive holds
// the sorted candidates that are inactive yet enabled, before filterEnabledInactive re-checks them.
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
	// Sorted, so the server's cap on the inventory always keeps the same units.
	sort.Slice(allServices, func(i, j int) bool { return allServices[i]["unit"] < allServices[j]["unit"] })

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

// runSystemctl indirects every systemctl call of this file so tests can drive the collector, the
// batch and the per-unit paths without systemctl (same reason as serviceHealthCollector, 6.18).
var runSystemctl = func(ctx context.Context, args ...string) ([]byte, error) {
	return runWithTimeout(ctx, "systemctl", args...)
}

// filterEnabledInactive re-checks the enabled-but-inactive candidates with one batched
// `systemctl show` and drops the units that are inactive by design (inactiveByDesign). If systemctl
// answers the batch with a non-zero exit (one bad name spoils it), up to maxSingleUnitChecks
// candidates are asked one by one; a unit whose query fails, or beyond the cap, stays a candidate.
func filterEnabledInactive(ctx context.Context, candidates []string) []string {
	if len(candidates) == 0 {
		return candidates
	}
	out, err := runSystemctl(ctx, append([]string{"show", "-p", enabledInactiveProps, "--"}, candidates...)...)
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
			out, err := runSystemctl(ctx, "show", "-p", enabledInactiveProps, "--", unit)
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
// rather than being ended by the timeout or the end of ctx (context.DeadlineExceeded or
// context.Canceled from runWithTimeout), killed by a signal (exit code -1) or never started. So the
// per-unit fallbacks also end with ctx: once it has ended, the next call returns its error unstarted.
func answered(err error) bool {
	var exitErr *exec.ExitError
	return errors.As(err, &exitErr) && exitErr.ExitCode() > 0
}

// parseShowBlocks maps the blank-line-separated blocks of `systemctl show` to their properties,
// each block under its Id and under every name in its Names, so a lookup depends neither on the
// block order nor on which of a unit's names was asked for (an alias).
func parseShowBlocks(out []byte) map[string]map[string]string {
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
	return byName
}

// parseEnabledInactive keeps the candidates whose `systemctl show` block (parseShowBlocks) does not
// mark them inactive by design; a candidate without a block stays.
func parseEnabledInactive(out []byte, candidates []string) []string {
	byName := parseShowBlocks(out)
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
// its column `col`, skipping lines too short to hold it. Empty map and the error if systemctl failed.
func parseSystemctlColumns(ctx context.Context, col int, args ...string) (map[string]string, error) {
	out, err := runSystemctl(ctx, args...)
	if err != nil {
		return map[string]string{}, err
	}
	return parseSystemctlColumnsOutput(string(out), col), nil
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
func collectWatchedServices(ctx context.Context, names []string) []map[string]any {
	if len(names) == 0 {
		return nil
	}
	// One `systemctl show` for all watched units instead of is-active + show per unit — the 2N
	// process spawns + D-Bus roundtrips per cycle become one (5.7). `--` terminates option parsing
	// so a server-supplied name beginning with '-' is treated as an operand, not a systemctl flag
	// (argument/flag-confusion hardening; runWithTimeout runs exec directly, no shell).
	out, err := runSystemctl(ctx, append([]string{"show", "-p", watchedProps, "--"}, names...)...)
	if err == nil {
		return parseWatchedServices(out, names)
	}
	// One bad name (a template such as getty@.service) fails the whole batch: ask name by name, with
	// the limits of filterEnabledInactive. A name whose query fails, or that is not asked, is
	// reported not running, as every name was before.
	services := make([]map[string]any, 0, len(names))
	asking := answered(err)
	for i, name := range names {
		if asking && i < maxSingleUnitChecks {
			out, err := runSystemctl(ctx, "show", "-p", watchedProps, "--", name)
			if err == nil {
				services = append(services, parseWatchedServices(out, []string{name})...)
				continue
			}
			asking = answered(err)
		}
		services = append(services, map[string]any{"name": name, "running": false, "pid": nil})
	}
	return services
}

// watchedProps are the properties collectWatchedServices reads per watched name.
const watchedProps = "Id,Names,ActiveState,MainPID"

// parseWatchedServices maps each requested name to its status from the `systemctl show` blocks
// (parseShowBlocks), so an alias (sshd -> ssh.service) finds its unit through Names, and a bare
// "nginx" matches "nginx.service" too. A name with no block stays not-running.
func parseWatchedServices(out []byte, names []string) []map[string]any {
	byName := parseShowBlocks(out)
	services := make([]map[string]any, 0, len(names))
	for _, name := range names {
		svc := map[string]any{"name": name, "running": false, "pid": nil}
		props, ok := byName[name]
		if !ok {
			props, ok = byName[name+".service"]
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
