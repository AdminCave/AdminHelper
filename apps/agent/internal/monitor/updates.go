// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"time"
)

// updatesTimeout caps a call of the security update count (apt-get, dnf, pkg audit). It runs once an
// hour and reads the whole package cache or vulnerability database, so it gets more than pluginTimeout.
const updatesTimeout = 30 * time.Second

// updatesCheckEvery spaces the counts: dnf loads all metadata on each call, and a pending security
// update is no five-minute matter.
const updatesCheckEvery = time.Hour

// updatesLeftOut ends the warning of a failed count: the field stays out until the next one.
const updatesLeftOut = "security_updates left out until the next hourly count"

// updatesCalls indirects the clock of the hourly count and its calls so tests can drive the cache and
// every outcome without the tools (same reason as cpuCalls). run runs one call under timeout
// and ctx with env added to the agent's environment.
var updatesCalls = struct {
	now func() time.Time
	run func(ctx context.Context, timeout time.Duration, env []string, name string, args ...string) ([]byte, error)
}{time.Now, runTimedEnv}

// runTimedEnv is runTimed with env added to the environment; a later entry of the same key wins
// (os/exec), so the agent's own LC_ALL is overridden.
func runTimedEnv(ctx context.Context, timeout time.Duration, env []string, name string, args ...string) ([]byte, error) {
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, name, args...)
	cmd.Env = append(os.Environ(), env...)
	cmd.WaitDelay = commandWaitDelay
	out, err := cmd.Output()
	if errors.Is(err, exec.ErrWaitDelay) {
		return out, nil
	}
	if err != nil && ctx.Err() != nil {
		return out, ctx.Err()
	}
	return out, err
}

// updatesDue reports whether a new count is due at now: none is saved, the saved one is an hour old or
// older, or it is from the future (the clock was set back), or counting would stop until the clock
// caught up.
func updatesDue(saved *updatesCheck, now time.Time) bool {
	if saved == nil {
		return true
	}
	age := now.Sub(time.Unix(saved.CheckedUnix, 0))
	return age < 0 || age >= updatesCheckEvery
}
