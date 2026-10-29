// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"context"
	"errors"
	"fmt"
	"os/exec"
	"time"
)

// ServiceEntry is one service record in the all_services inventory (keys:
// unit, active_state, enabled_state). Named alias so the wire contract between
// the platform collectors (services_linux.go / services_windows.go) and the
// throttle/hash logic (inventory.go) has a single anchor: change the element
// type here once instead of keeping three []map[string]string literals in sync.
type ServiceEntry = map[string]string

// serviceCounts sums up the loaded services for the "x/y active" display: active are the entries
// whose active_state is "active", total all of them. Callers pass the loaded services only: on
// Linux the units list-units reports as loaded (not its not-found and masked units, nor the
// templates, aliases and unloaded unit files the inventory also lists), on Windows every service
// sc query lists. No .service suffix filter: Linux lists service units only (--type=service), and
// Windows service names carry no suffix.
func serviceCounts(entries []ServiceEntry) map[string]int {
	active := 0
	for _, e := range entries {
		if e["active_state"] == "active" {
			active++
		}
	}
	return map[string]int{"active": active, "total": len(entries)}
}

// commandFailure is the short reason for a failed call of the command name: that it ran into
// timeout, the limit the caller ran it under (runTimed), that the run was canceled, its exit status
// or signal, or that the command did not start. Never stderr or the error text, which can name paths
// (fork/exec <path>).
func commandFailure(name string, timeout time.Duration, err error) string {
	if errors.Is(err, context.DeadlineExceeded) {
		return fmt.Sprintf("timed out after %s", timeout)
	}
	if errors.Is(err, context.Canceled) {
		return "canceled before it ended"
	}
	var exitErr *exec.ExitError
	if errors.As(err, &exitErr) {
		return exitErr.Error()
	}
	return name + " did not start"
}
