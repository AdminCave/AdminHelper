// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build freebsd

package monitor

import (
	"context"
	"os"
	"reflect"
	"slices"
	"strings"
	"testing"
)

// On FreeBSD the collectors run the real service(8). cron and newsyslog are enabled on every install
// (/etc/defaults/rc.conf); rc.subr reads cron's pidfile, which only root may read.
func requireRoot(t *testing.T) {
	t.Helper()
	if os.Geteuid() != 0 {
		t.Fatal("run as root: status reads the pidfiles in /var/run")
	}
}

func TestCollectServiceHealthOnFreeBSD(t *testing.T) {
	requireRoot(t)
	health := collectServiceHealth(context.Background())
	if e := health.Error; e != "" {
		t.Fatalf("error = %v", e)
	}
	byUnit := map[string]ServiceEntry{}
	for _, e := range health.AllServices {
		byUnit[e["unit"]] = e
	}
	for unit, state := range map[string]string{"cron": "active", "newsyslog": "inactive"} {
		want := ServiceEntry{"unit": unit, "active_state": state, "enabled_state": "enabled"}
		if !reflect.DeepEqual(byUnit[unit], want) {
			t.Errorf("all_services[%s] = %v, want %v", unit, byUnit[unit], want)
		}
	}
	// newsyslog's start runs once: stop_cmd=":" in its script.
	if slices.Contains(health.EnabledInactive, "newsyslog") {
		t.Errorf("enabled_inactive = %v, newsyslog has nothing to stop", health.EnabledInactive)
	}
}

func TestCollectWatchedServicesOnFreeBSD(t *testing.T) {
	requireRoot(t)
	pid, err := os.ReadFile("/var/run/cron.pid")
	if err != nil {
		t.Fatal(err)
	}
	got := collectWatchedServices(context.Background(), []string{"cron", "../cron"})
	want := []WatchedService{
		runningService("cron", strings.TrimSpace(string(pid))),
		stoppedService("../cron"),
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("watched = %v, want %v", got, want)
	}
}
