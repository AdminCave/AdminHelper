// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package monitor

import (
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
	out, err := runWithTimeout("sc", "query", "state=", "all")
	if err != nil {
		return result
	}

	// The sc-query parsing lives in parseScQuery (no build tag) so it is unit-tested on any
	// platform — see scquery.go / scquery_test.go (6.20).
	result["all_services"] = parseScQuery(string(out))
	return result
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
		out, err := runWithTimeout("sc", "query", name)
		if err == nil {
			output := string(out)
			if strings.Contains(output, "RUNNING") {
				svc["running"] = true
				exOut, err := runWithTimeout("sc", "queryex", name)
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
