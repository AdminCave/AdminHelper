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
