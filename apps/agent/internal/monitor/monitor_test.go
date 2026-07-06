// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"testing"

	"adminhelper-agent/internal/config"
)

// The re-provisioning watch-list preservation (6.15): a token rotation passes an empty services
// string and must NOT wipe the configured SERVICES list — a documented, previously error-prone edge.
func TestPreserveServicesKeepsWatchListOnRotation(t *testing.T) {
	t.Setenv("ADMINHELPER_MONITOR_DIR", t.TempDir())

	// A non-empty list is passed through unchanged.
	if got := preserveServices("nginx,redis"); got != "nginx,redis" {
		t.Fatalf("non-empty services should pass through, got %q", got)
	}

	// Seed the persisted config with a watch list, then a rotation with empty services keeps it.
	if err := config.WriteKeyValue(config.MonitorConfFile(), []config.KeyValue{
		{Key: "MONITOR_URL", Value: "https://x"},
		{Key: "API_KEY", Value: "k"},
		{Key: "SERVER_ID", Value: "srv"},
		{Key: "SERVICES", Value: "nginx,redis"},
	}); err != nil {
		t.Fatal(err)
	}
	if got := preserveServices(""); got != "nginx,redis" {
		t.Fatalf("empty services wiped the configured watch list: %q", got)
	}
}

func TestPreserveServicesEmptyWhenNoConfig(t *testing.T) {
	t.Setenv("ADMINHELPER_MONITOR_DIR", t.TempDir())
	// No persisted config -> empty stays empty (no crash, no spurious list).
	if got := preserveServices(""); got != "" {
		t.Fatalf("empty services with no config should stay empty, got %q", got)
	}
}
