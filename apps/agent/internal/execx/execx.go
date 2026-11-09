// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Package execx runs the agent's external tools: one exec path for the collectors, the sensors and
// the discovery, so a timeout, a canceled run and a tool that leaves a child behind end the same way
// everywhere.
package execx

import (
	"context"
	"errors"
	"os/exec"
	"sync/atomic"
	"time"
)

// WaitDelay bounds how long Run waits for a command's pipes once its context ended or the command
// exited. The kill reaches only the tool: a grandchild that inherited its stdout (a daemon, a pager)
// kept the pipe open, and Output read it past the timeout until the grandchild ended.
const WaitDelay = 2 * time.Second

// Run runs a command under timeout and ctx, whichever ends first. A call either ended returns the
// context's error (context.DeadlineExceeded at the timeout or the deadline of ctx, context.Canceled
// when ctx was canceled): exec itself reports it as the ExitError "signal: killed", which would pass a
// hanging tool off as a failing one. exec.ErrWaitDelay means the command exited 0 and only a child of
// it held the pipe past WaitDelay: the command's output is complete, so it is no error.
//
// A call its own timeout ended counts under CountTimeouts; one that ctx ended does not.
func Run(ctx context.Context, timeout time.Duration, name string, args ...string) ([]byte, error) {
	parent := ctx
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, name, args...)
	cmd.WaitDelay = WaitDelay
	out, err := cmd.Output()
	if errors.Is(err, exec.ErrWaitDelay) {
		return out, nil
	}
	if err != nil && ctx.Err() != nil {
		if parent.Err() == nil {
			if n, ok := parent.Value(timeoutsKey{}).(*atomic.Int64); ok {
				n.Add(1)
			}
		}
		return out, ctx.Err()
	}
	return out, err
}

type timeoutsKey struct{}

// CountTimeouts returns ctx with a counter of the calls of Run under it that their own timeout ended:
// the measure of a collector that hits its time limit (monitor's self-throttle).
func CountTimeouts(ctx context.Context) (context.Context, *atomic.Int64) {
	n := new(atomic.Int64)
	return context.WithValue(ctx, timeoutsKey{}, n), n
}
