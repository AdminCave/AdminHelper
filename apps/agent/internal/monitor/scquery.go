// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"strconv"
	"strings"
)

// scServiceHealth builds the Windows service-health block from the result of `sc query state= all`,
// in the format of the systemd block; no build tag, so it is tested on any platform. A failed sc
// query sets error and leaves the inventory empty and the counts out: without error the server would
// read the empty block as all OK, and counts would claim 0 of 0.
//
// crashEvents runs the scmCrashArgs call, only when a stopped service carries an exit: its events
// add result and since to those services (addScmCrashes). A failed call adds nothing, like the
// facts batch on Linux.
func scServiceHealth(out []byte, err error, crashEvents func() ([]byte, error)) map[string]any {
	result := map[string]any{
		"failed":           []string{},
		"enabled_inactive": []string{},
		"all_services":     []ServiceEntry{},
	}
	if err != nil {
		result["error"] = "sc query failed: " + commandFailure("sc", pluginTimeout, err)
		return result
	}
	services, byName := parseScQuery(string(out))
	result["all_services"] = services
	result["counts"] = serviceCounts(services)
	for _, svc := range services {
		if svc["exit"] != "" {
			if events, err := crashEvents(); err == nil {
				addScmCrashes(services, byName, parseScmCrashes(events))
			}
			break
		}
	}
	return result
}

// parseScQuery parses the output of `sc query state= all` into systemd-compatible service entries.
// Extracted from the Windows collector (no build tag) so this pure string-parsing logic — the
// STATE-line detection and the flush that keeps the LAST service — is unit-tested on any platform;
// the Windows-only collector cannot run in the ubuntu CI, so the parser previously had no test and
// was never even seen by go vet (6.20).
//
// STOPPED services are deliberately NOT classified as enabled_inactive: `sc query` does not expose
// the start type, so "enabled but inactive" is unknowable here. The monitoring service derives the
// same empty result from all_services (enabled_state is always "unknown" on Windows).
//
// byName maps every service name and display name, in lower case, to the service name; the SCM
// keeps both unique across all services.
func parseScQuery(out string) (allServices []ServiceEntry, byName map[string]string) {
	var currentName, currentDisplay, currentState, currentWin32, currentSpecific string
	byName = map[string]string{}

	// flush the in-progress entry — called both when a new SERVICE_NAME starts the next record AND
	// once after the loop, so the last service isn't dropped (off-by-one).
	flush := func() {
		if currentName == "" {
			return
		}
		svc := mapWindowsService(currentName, currentState)
		if currentState == "STOPPED" {
			if exit := windowsExit(currentWin32, currentSpecific); exit != "" {
				svc["exit"] = exit
			}
		}
		allServices = append(allServices, svc)
		byName[strings.ToLower(currentName)] = currentName
		if currentDisplay != "" {
			byName[strings.ToLower(currentDisplay)] = currentName
		}
	}

	for _, line := range strings.Split(out, "\n") {
		line = strings.TrimSpace(line)
		if strings.HasPrefix(line, "SERVICE_NAME:") {
			flush()
			currentName = strings.TrimSpace(strings.TrimPrefix(line, "SERVICE_NAME:"))
			currentDisplay, currentState, currentWin32, currentSpecific = "", "", "", ""
		} else if strings.HasPrefix(line, "DISPLAY_NAME:") {
			currentDisplay = strings.TrimSpace(strings.TrimPrefix(line, "DISPLAY_NAME:"))
		} else if strings.HasPrefix(line, "WIN32_EXIT_CODE") {
			currentWin32 = scCode(line)
		} else if strings.HasPrefix(line, "SERVICE_EXIT_CODE") {
			currentSpecific = scCode(line)
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

	return allServices, byName
}

// scCode is the decimal code of an sc query line like `WIN32_EXIT_CODE    : 1067  (0x42b)`, or ""
// when the line carries none.
func scCode(line string) string {
	_, value, ok := strings.Cut(line, ":")
	fields := strings.Fields(value)
	if !ok || len(fields) == 0 {
		return ""
	}
	if _, err := strconv.ParseInt(fields[0], 10, 64); err != nil {
		return ""
	}
	return fields[0]
}

// windowsExit is the exit of a stopped service from its Win32 and service-specific exit codes, or ""
// when it ended without an error: 0 (NO_ERROR) and 1077 (ERROR_SERVICE_NEVER_STARTED, a service not
// started since boot) are none. 1066 (ERROR_SERVICE_SPECIFIC_ERROR) says the service's own code is in
// SERVICE_EXIT_CODE, which counts only then (SERVICE_STATUS).
func windowsExit(win32, specific string) string {
	switch win32 {
	case "", "0", "1077":
		return ""
	case "1066":
		if specific != "" && specific != "0" {
			return "service=" + specific
		}
	}
	return "win32=" + win32
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
