// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package monitor

import "testing"

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
