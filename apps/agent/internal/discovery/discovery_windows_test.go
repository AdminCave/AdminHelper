// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package discovery

import (
	"strings"
	"testing"
)

// The event log and WMI run on every Windows host, the CI runner among them.
func TestTheServicesOfThisHostAreListedAsUnits(t *testing.T) {
	units, err := enumServices()
	if err != nil {
		t.Fatalf("enumServices: %v", err)
	}
	found := map[string]Unit{}
	for _, u := range units {
		found[strings.ToLower(u.Name)] = u
	}
	for _, name := range []string{"eventlog", "winmgmt"} {
		u, ok := found[name]
		if !ok {
			t.Errorf("service %s not listed among %d units", name, len(units))
			continue
		}
		if u.State != "active" || u.Sub != "running" {
			t.Errorf("service %s = %+v, want active, running", name, u)
		}
	}
}

func TestADiscoveryOnThisHostListsItsServicesWhole(t *testing.T) {
	units, ok := collectUnits(t.Context())
	if !ok || len(units) == 0 {
		t.Errorf("collectUnits = %d units, whole %v; want the services, whole", len(units), ok)
	}
}
