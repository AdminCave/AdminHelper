// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import "strings"

// parseScQuery parses the output of `sc query state= all` into systemd-compatible service entries.
// Extracted from the Windows collector (no build tag) so this pure string-parsing logic — the
// STATE-line detection and the flush that keeps the LAST service — is unit-tested on any platform;
// the Windows-only collector cannot run in the ubuntu CI, so the parser previously had no test and
// was never even seen by go vet (6.20).
//
// STOPPED services are deliberately NOT classified as enabled_inactive: `sc query` does not expose
// the start type, so "enabled but inactive" is unknowable here. The monitoring service derives the
// same empty result from all_services (enabled_state is always "unknown" on Windows).
func parseScQuery(out string) []ServiceEntry {
	var (
		allServices  []ServiceEntry
		currentName  string
		currentState string
	)

	// flush the in-progress entry — called both when a new SERVICE_NAME starts the next record AND
	// once after the loop, so the last service isn't dropped (off-by-one).
	flush := func() {
		if currentName == "" {
			return
		}
		allServices = append(allServices, mapWindowsService(currentName, currentState))
	}

	for _, line := range strings.Split(out, "\n") {
		line = strings.TrimSpace(line)
		if strings.HasPrefix(line, "SERVICE_NAME:") {
			flush()
			currentName = strings.TrimSpace(strings.TrimPrefix(line, "SERVICE_NAME:"))
			currentState = ""
		} else if strings.HasPrefix(line, "STATE") {
			parts := strings.Fields(line)
			for _, p := range parts {
				if p == "RUNNING" || p == "STOPPED" || p == "PAUSED" || p == "START_PENDING" || p == "STOP_PENDING" {
					currentState = p
					break
				}
			}
		}
	}
	flush()

	return allServices
}

// mapWindowsService maps a Windows service to the systemd-compatible format.
func mapWindowsService(name, state string) ServiceEntry {
	activeState := "unknown"
	switch state {
	case "RUNNING":
		activeState = "active"
	case "STOPPED":
		activeState = "inactive"
	case "PAUSED":
		activeState = "inactive"
	case "START_PENDING", "STOP_PENDING":
		activeState = "activating"
	}
	return ServiceEntry{
		"unit":          name,
		"active_state":  activeState,
		"enabled_state": "unknown",
	}
}
