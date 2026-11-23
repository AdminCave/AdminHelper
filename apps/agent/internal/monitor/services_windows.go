// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package monitor

import (
	"context"
	"regexp"
	"strings"

	"golang.org/x/sys/windows/registry"
)

// reWinServiceName matches the characters a real Windows service name uses
// (including `$` for named instances like MSSQL$SQLEXPRESS). `sc` has no `--` option
// terminator (unlike the systemctl path in services_linux.go), so a server-supplied
// name that looks like an sc query option (type=, state=, bufsize=) would otherwise
// change the command's behaviour — the dangerous characters are `=` and whitespace,
// which this class excludes (3.44).
var reWinServiceName = regexp.MustCompile(`^[A-Za-z0-9._$-]+$`)

// collectServiceHealth collects Windows service status; ctx ends the sc call.
// The format is compatible with the systemd format for the monitoring server.
func collectServiceHealth(ctx context.Context) *ServiceHealth {
	// The block is built in scServiceHealth (no build tag) so it is unit-tested on any platform —
	// see scquery.go / scquery_test.go (6.20).
	out, err := runWithTimeout(ctx, "sc", "query", "state=", "all")
	return scServiceHealth(out, err, func() ([]byte, error) {
		return runWithTimeout(ctx, "wevtutil", scmCrashArgs...)
	}, serviceStartStates)
}

// servicesKey is the registry key under which every service has its own key with its Start value.
const servicesKey = `SYSTEM\CurrentControlSet\Services\`

// serviceStartStates reads the start type of each service from its registry key in one pass (no
// process per service, unlike sc qc) and maps it with windowsEnabledState. A service whose key or
// Start value cannot be read is left out and keeps "unknown".
func serviceStartStates(names []string) map[string]string {
	states := make(map[string]string, len(names))
	for _, name := range names {
		if name == "" || strings.ContainsAny(name, `\/`) {
			continue
		}
		start, ok := serviceStart(name)
		if !ok {
			continue
		}
		states[name] = windowsEnabledState(start, serviceHasTriggers(name))
	}
	return states
}

// serviceStart reads the Start value of the service's registry key.
func serviceStart(name string) (uint64, bool) {
	k, err := registry.OpenKey(registry.LOCAL_MACHINE, servicesKey+name, registry.QUERY_VALUE)
	if err != nil {
		return 0, false
	}
	defer k.Close()
	start, _, err := k.GetIntegerValue("Start")
	return start, err == nil
}

// serviceHasTriggers reports whether the service has start triggers: a TriggerInfo subkey with at
// least one trigger under it.
func serviceHasTriggers(name string) bool {
	k, err := registry.OpenKey(registry.LOCAL_MACHINE, servicesKey+name+`\TriggerInfo`, registry.QUERY_VALUE)
	if err != nil {
		return false
	}
	defer k.Close()
	info, err := k.Stat()
	return err == nil && info.SubKeyCount > 0
}

// collectWatchedServices checks the status of specific Windows services; ctx ends every sc call.
func collectWatchedServices(ctx context.Context, names []string) []WatchedService {
	var services []WatchedService
	for _, name := range names {
		svc := WatchedService{Name: name}
		// Reject names that aren't plain service names rather than passing an
		// option-looking string to sc (which has no `--`) — report not-running (3.44).
		if !reWinServiceName.MatchString(name) {
			services = append(services, svc)
			continue
		}
		out, err := runWithTimeout(ctx, "sc", "query", name)
		if err == nil {
			output := string(out)
			if strings.Contains(output, "RUNNING") {
				svc.Running = true
				exOut, err := runWithTimeout(ctx, "sc", "queryex", name)
				if err == nil {
					for _, line := range strings.Split(string(exOut), "\n") {
						if strings.Contains(line, "PID") && !strings.Contains(line, "FLAGS") {
							parts := strings.Fields(line)
							if len(parts) >= 3 {
								pid := parts[len(parts)-1]
								if pid != "0" {
									svc.PID = &pid
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
