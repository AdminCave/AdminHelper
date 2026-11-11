// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"context"
	"time"

	"adminhelper-agent/internal/allowlist"
	"adminhelper-agent/internal/execx"
)

// errCommandNotAllowed is the error of a call runTimedEnv refused: the command or its arguments are not
// on the agent's command allowlist (package allowlist), so it never started.
var errCommandNotAllowed = allowlist.ErrNotAllowed

// argClasses are the variable parts a call may carry (allowlist.Classes).
var argClasses = allowlist.Classes()

// commandAllowed reports whether name with args is on the allowlist.
func commandAllowed(name string, args []string) bool {
	return allowlist.Allowed(name, args)
}

// commandKey is the allowlist key of name (allowlist.Key).
func commandKey(name string, windows bool) string {
	return allowlist.Key(name, windows)
}

// commandWaitDelay bounds how long runTimed waits for a command's pipes (execx.WaitDelay).
const commandWaitDelay = execx.WaitDelay

// runTimed runs a command under timeout and ctx, whichever ends first; see runTimedEnv.
func runTimed(ctx context.Context, timeout time.Duration, name string, args ...string) ([]byte, error) {
	return runTimedEnv(ctx, timeout, nil, name, args...)
}

// runTimedEnv is the one place the collectors start a command, through allowlist.RunEnv: a call off
// the list does not start and returns errCommandNotAllowed. env is added to the agent's environment; a
// later entry of the same key wins (os/exec), so the agent's own LC_ALL is overridden.
func runTimedEnv(ctx context.Context, timeout time.Duration, env []string, name string, args ...string) ([]byte, error) {
	return allowlist.RunEnv(ctx, timeout, env, name, args...)
}

// execTimed runs a command without the allowlist check, through execx.RunEnv (its errors there; a
// call its own timeout ended counts for the self-throttle); only the tests of the timeout handling
// call it.
func execTimed(ctx context.Context, timeout time.Duration, env []string, name string, args ...string) ([]byte, error) {
	return execx.RunEnv(ctx, timeout, env, name, args...)
}
