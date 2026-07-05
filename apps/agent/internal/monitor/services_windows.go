// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package monitor

import (
	"os/exec"
	"regexp"
	"strings"
)

// reWinServiceName matches the characters a real Windows service name uses
// (including `$` for named instances like MSSQL$SQLEXPRESS). `sc` has no `--` option
// terminator (unlike the systemctl path in services_linux.go), so a server-supplied
// name that looks like an sc query option (type=, state=, bufsize=) would otherwise
// change the command's behaviour — the dangerous characters are `=` and whitespace,
// which this class excludes (3.44).
var reWinServiceName = regexp.MustCompile(`^[A-Za-z0-9._$-]+$`)

// collectServiceHealth collects Windows service status.
// The format is compatible with the systemd format for the monitoring server.
func collectServiceHealth() map[string]any {
	result := map[string]any{
		"failed":           []string{},
		"enabled_inactive": []string{},
		"all_services":     []ServiceEntry{},
	}

	// Run sc query state= all
	out, err := exec.Command("sc", "query", "state=", "all").Output()
	if err != nil {
		return result
	}

	var (
		allServices  []ServiceEntry
		currentName  string
		currentState string
	)

	// Flush the in-progress service entry. Called both when a new SERVICE_NAME
	// starts the next record AND once after the loop, so the LAST service
	// isn't dropped (off-by-one).
	//
	// STOPPED services are deliberately NOT classified as enabled_inactive:
	// `sc query` does not expose the start type, so "enabled but inactive" is
	// unknowable here. The monitoring service derives the same empty result
	// from all_services (enabled_state is always "unknown" on Windows); the
	// legacy key must match, because it becomes the fallback when the
	// throttled push omits all_services.
	flush := func() {
		if currentName == "" {
			return
		}
		allServices = append(allServices, mapWindowsService(currentName, currentState))
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
	return result
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

// collectWatchedServices checks the status of specific Windows services.
func collectWatchedServices(names []string) []map[string]any {
	var services []map[string]any
	for _, name := range names {
		svc := map[string]any{"name": name, "running": false, "pid": nil}
		// Reject names that aren't plain service names rather than passing an
		// option-looking string to sc (which has no `--`) — report not-running (3.44).
		if !reWinServiceName.MatchString(name) {
			services = append(services, svc)
			continue
		}
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
