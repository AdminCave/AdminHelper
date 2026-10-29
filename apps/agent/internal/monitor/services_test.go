// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"context"
	"os/exec"
	"reflect"
	"testing"
	"time"
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

func TestCommandFailure(t *testing.T) {
	// A call the timeout ended names the timeout its caller ran it under (docker 10 s, the other
	// tools pluginTimeout), not one fixed value. The exit status comes from a real child process, so
	// the ExitError is the one exec builds on this platform; a command that never started names the
	// command, not the path exec reports.
	failed := runHelperDocker(t, "fail", time.Minute)
	for name, tc := range map[string]struct {
		timeout time.Duration
		err     error
		want    string
	}{
		"timed out 10s": {10 * time.Second, context.DeadlineExceeded, "timed out after 10s"},
		"timed out 15s": {15 * time.Second, context.DeadlineExceeded, "timed out after 15s"},
		"exit status":   {time.Minute, failed, "exit status 3"},
		"not started": {time.Minute, &exec.Error{Name: "/usr/bin/docker", Err: exec.ErrNotFound},
			"docker did not start"},
		"canceled": {time.Minute, context.Canceled, "canceled before it ended"},
	} {
		t.Run(name, func(t *testing.T) {
			if got := commandFailure("docker", tc.timeout, tc.err); got != tc.want {
				t.Errorf("commandFailure = %q, want %q", got, tc.want)
			}
		})
	}
}
