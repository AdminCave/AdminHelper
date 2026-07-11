// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package monitor

import (
	"reflect"
	"testing"
)

func TestParseWatchedServices(t *testing.T) {
	// 5.7: parse the batched `systemctl show` output. Keyed by Id so it's independent of block order
	// (the requested names below are in a different order than the blocks), matching a bare name
	// against its .service Id, and marking a name with no block as not-running.
	out := []byte("Id=nginx.service\nActiveState=active\nMainPID=1234\n\n" +
		"Id=sshd.service\nActiveState=inactive\nMainPID=0\n\n" +
		"Id=postgres.service\nActiveState=active\nMainPID=9999\n\n" +
		"Id=redis.service\nActiveState=active\nMainPID=5678")
	got := parseWatchedServices(out, []string{"redis", "missing", "nginx", "sshd.service", "postgres.service"})

	if len(got) != 5 {
		t.Fatalf("want 5 entries, got %d", len(got))
	}
	// redis (bare name matched to redis.service): active, pid 5678
	if got[0]["running"] != true || got[0]["pid"] != "5678" {
		t.Errorf("redis: want running=true pid=5678, got %v", got[0])
	}
	// missing: no block -> not running, no pid
	if got[1]["running"] != false || got[1]["pid"] != nil {
		t.Errorf("missing: want running=false pid=nil, got %v", got[1])
	}
	// nginx (bare name matched to nginx.service): active, pid 1234
	if got[2]["running"] != true || got[2]["pid"] != "1234" {
		t.Errorf("nginx: want running=true pid=1234, got %v", got[2])
	}
	// sshd.service: inactive -> not running (MainPID 0 ignored)
	if got[3]["running"] != false || got[3]["pid"] != nil {
		t.Errorf("sshd: want running=false pid=nil, got %v", got[3])
	}
	// postgres.service: direct .service Id match, active -> running, pid 9999
	if got[4]["running"] != true || got[4]["pid"] != "9999" {
		t.Errorf("postgres: want running=true pid=9999, got %v", got[4])
	}
}

func TestParseSystemctlColumnsOutput(t *testing.T) {
	// list-units: UNIT LOAD ACTIVE SUB ... -> col 2 = ACTIVE.
	units := parseSystemctlColumnsOutput(
		"nginx.service loaded active running\nredis.service loaded inactive dead\n", 2)
	if units["nginx.service"] != "active" || units["redis.service"] != "inactive" {
		t.Errorf("list-units col 2: %v", units)
	}
	// list-unit-files: UNIT STATE -> col 1 = STATE.
	files := parseSystemctlColumnsOutput("nginx.service enabled\nredis.service disabled\n", 1)
	if files["nginx.service"] != "enabled" || files["redis.service"] != "disabled" {
		t.Errorf("list-unit-files col 1: %v", files)
	}
	// A line too short to hold the column is skipped, not indexed out of range.
	if short := parseSystemctlColumnsOutput("only-one-field\n", 2); len(short) != 0 {
		t.Errorf("short line should be skipped: %v", short)
	}
}

func TestAssembleServiceHealthEnabledInactive(t *testing.T) {
	got := assembleServiceHealth(
		map[string]string{"a.service": "inactive", "b.service": "active"},
		map[string]string{"a.service": "enabled", "b.service": "enabled"},
		[]string{"c.service"},
	)
	// enabled_inactive: only a (inactive AND enabled); b is active, so excluded.
	if !reflect.DeepEqual(got["enabled_inactive"], []string{"a.service"}) {
		t.Errorf("enabled_inactive = %v, want [a.service]", got["enabled_inactive"])
	}
	if !reflect.DeepEqual(got["failed"], []string{"c.service"}) {
		t.Errorf("failed = %v, want [c.service]", got["failed"])
	}
	if all := got["all_services"].([]ServiceEntry); len(all) != 2 {
		t.Errorf("all_services should be the union (2 entries): %v", all)
	}
}

func TestAssembleServiceHealthUnknownFallback(t *testing.T) {
	// A unit present in only one map gets "unknown" for the missing side.
	got := assembleServiceHealth(
		map[string]string{"only-active.service": "active"},
		map[string]string{"only-enabled.service": "enabled"},
		nil,
	)
	byUnit := map[string]ServiceEntry{}
	for _, e := range got["all_services"].([]ServiceEntry) {
		byUnit[e["unit"]] = e
	}
	if byUnit["only-active.service"]["enabled_state"] != "unknown" {
		t.Errorf("only-active enabled_state = %q, want unknown", byUnit["only-active.service"]["enabled_state"])
	}
	if byUnit["only-enabled.service"]["active_state"] != "unknown" {
		t.Errorf("only-enabled active_state = %q, want unknown", byUnit["only-enabled.service"]["active_state"])
	}
	// nil failed normalizes to an empty slice, not null.
	if !reflect.DeepEqual(got["failed"], []string{}) {
		t.Errorf("failed = %v, want []", got["failed"])
	}
}
