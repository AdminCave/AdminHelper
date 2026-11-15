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
	"os"
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
	return RunEnv(ctx, timeout, nil, name, args...)
}

// RunEnv is Run with env added to the agent's environment; a later entry of the same key wins
// (os/exec), so the agent's own LC_ALL is overridden.
func RunEnv(ctx context.Context, timeout time.Duration, env []string, name string, args ...string) ([]byte, error) {
	parent := ctx
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, name, args...)
	if env != nil {
		cmd.Env = append(os.Environ(), env...)
	}
	cmd.WaitDelay = WaitDelay
	out, err := cmd.Output()
	return ended(parent, ctx, out, err)
}

// ErrOutputLimit is the error of RunCapped for a command that wrote more than its limit.
var ErrOutputLimit = errors.New("the output exceeded its limit")

// RunCapped is Run for a command whose output the agent does not trust to stay small (code of a site
// it runs): it keeps at most limit bytes of stdout, and a command that writes more it kills and
// returns ErrOutputLimit, so its output never grows in the agent's memory. stderr is dropped, and
// with it any text of the command in the ExitError.
func RunCapped(ctx context.Context, timeout time.Duration, limit int, name string, args ...string) ([]byte, error) {
	parent := ctx
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, name, args...)
	w := &capWriter{limit: limit, kill: cancel}
	cmd.Stdout = w
	cmd.WaitDelay = WaitDelay
	err := cmd.Run()
	if w.over {
		return nil, ErrOutputLimit
	}
	return ended(parent, ctx, w.buf, err)
}

// capWriter keeps what is written to it up to limit bytes; the first write past it calls kill.
type capWriter struct {
	limit int
	buf   []byte
	over  bool
	kill  func()
}

func (w *capWriter) Write(p []byte) (int, error) {
	if len(w.buf)+len(p) > w.limit {
		w.over = true
		w.kill()
		return 0, ErrOutputLimit
	}
	w.buf = append(w.buf, p...)
	return len(p), nil
}

// ended is the result of a command run under ctx, a child of parent with the command's own timeout.
func ended(parent, ctx context.Context, out []byte, err error) ([]byte, error) {
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
