// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

// ServiceEntry is one service record in the all_services inventory (keys:
// unit, active_state, enabled_state). Named alias so the wire contract between
// the platform collectors (services_linux.go / services_windows.go) and the
// throttle/hash logic (inventory.go) has a single anchor: change the element
// type here once instead of keeping three []map[string]string literals in sync.
type ServiceEntry = map[string]string

// serviceCounts sums up the loaded services for the "x/y active" display: active are the entries
// whose active_state is "active", total all of them. Callers pass the loaded services only: on
// Linux the units list-units reports (not the templates, aliases and unloaded unit files the
// inventory also lists), on Windows every service sc query lists. No .service suffix filter:
// Linux lists service units only (--type=service), and Windows service names carry no suffix.
func serviceCounts(entries []ServiceEntry) map[string]int {
	active := 0
	for _, e := range entries {
		if e["active_state"] == "active" {
			active++
		}
	}
	return map[string]int{"active": active, "total": len(entries)}
}
