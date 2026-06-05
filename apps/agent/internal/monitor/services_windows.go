// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package monitor

import (
	"os/exec"
	"strings"
)

// collectServiceHealth collects Windows service status.
// The format is compatible with the systemd format for the monitoring server.
func collectServiceHealth() map[string]any {
	result := map[string]any{
		"failed":           []string{},
		"enabled_inactive": []string{},
		"all_services":     []map[string]string{},
	}

	// Run sc query state= all
	out, err := exec.Command("sc", "query", "state=", "all").Output()
	if err != nil {
		return result
	}

	var (
		allServices     []map[string]string
		failed          []string
		enabledInactive []string
		currentName     string
		currentState    string
	)

	// Flush the in-progress service entry. Called both when a new SERVICE_NAME
	// starts the next record AND once after the loop, so the LAST service's
	// STOPPED->enabledInactive classification isn't dropped (off-by-one).
	flush := func() {
		if currentName == "" {
			return
		}
		allServices = append(allServices, mapWindowsService(currentName, currentState))
		if currentState == "STOPPED" {
			enabledInactive = append(enabledInactive, currentName)
		}
	}

	for _, line := range strings.Split(string(out), "\n") {
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

	result["all_services"] = allServices
	result["failed"] = failed
	result["enabled_inactive"] = enabledInactive
	return result
}

// mapWindowsService maps a Windows service to the systemd-compatible format.
func mapWindowsService(name, state string) map[string]string {
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
	return map[string]string{
		"unit":          name,
		"active_state":  activeState,
		"enabled_state": "unknown",
	}
}

// collectWatchedServices checks the status of specific Windows services.
func collectWatchedServices(names []string) []map[string]any {
	var services []map[string]any
	for _, name := range names {
		svc := map[string]any{"name": name, "running": false, "pid": nil}
		out, err := exec.Command("sc", "query", name).Output()
		if err == nil {
			output := string(out)
			if strings.Contains(output, "RUNNING") {
				svc["running"] = true
				exOut, err := exec.Command("sc", "queryex", name).Output()
				if err == nil {
					for _, line := range strings.Split(string(exOut), "\n") {
						if strings.Contains(line, "PID") && !strings.Contains(line, "FLAGS") {
							parts := strings.Fields(line)
							if len(parts) >= 3 {
								pid := parts[len(parts)-1]
								if pid != "0" {
									svc["pid"] = pid
								}
							}
						}
					}
				}
			}
		}
		services = append(services, svc)
	}
	return services
}
