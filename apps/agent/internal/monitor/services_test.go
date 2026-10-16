// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"reflect"
	"testing"
)

func TestServiceHealthCounts(t *testing.T) {
	// active counts the entries whose active_state is "active", total every entry: an inactive, a
	// failed and an activating unit are loaded, but none of them is active.
	linux := []ServiceEntry{
		{"unit": "ssh.service", "active_state": "active", "enabled_state": "enabled"},
		{"unit": "cron.service", "active_state": "active", "enabled_state": "enabled"},
		{"unit": "anacron.service", "active_state": "inactive", "enabled_state": "enabled"},
		{"unit": "broken.service", "active_state": "failed", "enabled_state": "enabled"},
		{"unit": "slow.service", "active_state": "activating", "enabled_state": "enabled"},
	}
	if got := serviceCounts(linux); !reflect.DeepEqual(got, map[string]int{"active": 2, "total": 5}) {
		t.Errorf("linux counts = %v, want active 2 of 5", got)
	}
	// Windows service names carry no .service suffix (parseScQuery): they count all the same.
	if got := serviceCounts(parseScQuery(scFixture)); !reflect.DeepEqual(got, map[string]int{"active": 1, "total": 2}) {
		t.Errorf("windows counts = %v, want active 1 of 2", got)
	}
	// No inventory still yields both keys, so the server reads 0 of 0 rather than a missing count.
	if got := serviceCounts(nil); !reflect.DeepEqual(got, map[string]int{"active": 0, "total": 0}) {
		t.Errorf("empty counts = %v, want active 0 of 0", got)
	}
}
