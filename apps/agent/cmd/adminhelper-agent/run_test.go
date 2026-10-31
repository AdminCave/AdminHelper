// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package main

import (
	"context"
	"fmt"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

// setStopWait shortens stopWait for one test.
func setStopWait(t *testing.T, d time.Duration) {
	t.Helper()
	old := stopWait
	stopWait = d
	t.Cleanup(func() { stopWait = old })
}

// setCycle replaces the cycle of runLoop and the Windows service for one test.
func setCycle(t *testing.T, f func(context.Context)) {
	t.Helper()
	old := cycle
	cycle = f
	t.Cleanup(func() { cycle = old })
}

// serveInBackground runs serve on its own goroutine; the channel closes when it returns.
func serveInBackground(ctx context.Context, interval time.Duration, cycle func(context.Context)) <-chan struct{} {
	returned := make(chan struct{})
	go func() {
		serve(ctx, interval, cycle)
		close(returned)
	}()
	return returned
}

// within fails the test unless ch is closed within d.
func within(t *testing.T, ch <-chan struct{}, d time.Duration, what string) {
	t.Helper()
	select {
	case <-ch:
	case <-time.After(d):
		t.Fatalf("%s: not within %s", what, d)
	}
}

func TestServeCancelEndsTheRunningCycle(t *testing.T) {
	started := make(chan struct{})
	ended := make(chan struct{})
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// The cycle ends only through its ctx and needs a moment after that, so a
	// serve that does not wait for it returns before ended is closed.
	returned := serveInBackground(ctx, time.Hour, func(ctx context.Context) {
		close(started)
		<-ctx.Done()
		time.Sleep(100 * time.Millisecond)
		close(ended)
	})
	within(t, started, 2*time.Second, "first cycle started")

	cancel()
	within(t, returned, 2*time.Second, "serve returned after cancel")
	select {
	case <-ended:
	default:
		t.Fatal("serve returned before the running cycle ended")
	}
}

func TestServeStopWaitBoundsACycleThatIgnoresTheContext(t *testing.T) {
	setStopWait(t, 200*time.Millisecond)
	started := make(chan struct{})
	release := make(chan struct{})
	t.Cleanup(func() { close(release) })
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	returned := serveInBackground(ctx, time.Hour, func(context.Context) {
		close(started)
		<-release
	})
	within(t, started, 2*time.Second, "first cycle started")

	cancelled := time.Now()
	cancel()
	within(t, returned, 2*time.Second, "serve returned after cancel")
	if waited := time.Since(cancelled); waited < 200*time.Millisecond {
		t.Fatalf("serve returned after %s, before stopWait (200ms) was up", waited)
	}
}

func TestServeNeverRunsTwoCycles(t *testing.T) {
	var running, total atomic.Int32
	var overlap atomic.Bool
	second := make(chan struct{})
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// About twenty ticks fall into every cycle.
	returned := serveInBackground(ctx, 5*time.Millisecond, func(ctx context.Context) {
		if running.Add(1) > 1 {
			overlap.Store(true)
		}
		if total.Add(1) == 2 {
			close(second)
		}
		select {
		case <-time.After(100 * time.Millisecond):
		case <-ctx.Done():
		}
		running.Add(-1)
	})
	within(t, second, 2*time.Second, "second cycle started")

	cancel()
	within(t, returned, 2*time.Second, "serve returned after cancel")
	if overlap.Load() {
		t.Fatal("two cycles ran at the same time")
	}
}

// setRunPhases replaces the budgets and the phases of runOnce for one test.
func setRunPhases(t *testing.T, run, renew, sync time.Duration,
	renewF func(context.Context), syncF, pushF func(context.Context) error) {
	t.Helper()
	oldRun, oldRenew, oldSync := runBudget, renewBudget, syncBudget
	oldRenewF, oldSyncF, oldPushF := renewPhase, syncPhase, pushPhase
	runBudget, renewBudget, syncBudget = run, renew, sync
	renewPhase, syncPhase, pushPhase = renewF, syncF, pushF
	t.Cleanup(func() {
		runBudget, renewBudget, syncBudget = oldRun, oldRenew, oldSync
		renewPhase, syncPhase, pushPhase = oldRenewF, oldSyncF, oldPushF
	})
}

func TestRunOnceBudgetKeepsThePushWhenSyncHangs(t *testing.T) {
	var renewReturned, syncDeadline, syncEnded time.Time
	var pushCalls atomic.Int32
	var pushCtxErr error
	var pushDeadline time.Time
	var pushHasDeadline bool
	setRunPhases(t, time.Second, 200*time.Millisecond, 200*time.Millisecond,
		func(ctx context.Context) {
			<-ctx.Done()
			renewReturned = time.Now()
		},
		func(ctx context.Context) error {
			syncDeadline, _ = ctx.Deadline()
			<-ctx.Done()
			syncEnded = time.Now()
			return ctx.Err()
		},
		func(ctx context.Context) error {
			pushCalls.Add(1)
			pushCtxErr = ctx.Err()
			pushDeadline, pushHasDeadline = ctx.Deadline()
			return nil
		})

	start := time.Now()
	done := make(chan struct{})
	go func() {
		_ = runOnce(context.Background())
		close(done)
	}()
	within(t, done, 1500*time.Millisecond, "runOnce returned")

	if got := pushCalls.Load(); got != 1 {
		t.Fatalf("push calls = %d, want 1", got)
	}
	if pushCtxErr != nil {
		t.Fatalf("the push got an ended context: %v", pushCtxErr)
	}
	// The push runs under the run's budget, which leaves monitor.Push its reserve.
	if !pushHasDeadline || pushDeadline.After(start.Add(1100*time.Millisecond)) {
		t.Fatalf("push deadline = %v (set %v), want the run's budget of 1s", pushDeadline.Sub(start), pushHasDeadline)
	}
	// The sync budget starts when the renewal is back, not with the run: a sync
	// context derived from the renewal's, or a wrong budget, ends earlier.
	if min := renewReturned.Add(200 * time.Millisecond); syncDeadline.Before(min) {
		t.Fatalf("sync deadline %s before the renewal's return + 200ms (%s)",
			syncDeadline.Sub(start), min.Sub(start))
	}
	if syncEnded.Sub(start) > 900*time.Millisecond {
		t.Fatalf("the sync ended %s after the start, want it at its own budget", syncEnded.Sub(start))
	}
}

func TestRunOnceBudgetEndsWithTheParent(t *testing.T) {
	renewing := make(chan struct{})
	var syncErr, pushErr atomic.Value
	setRunPhases(t, time.Minute, time.Minute, time.Minute,
		func(ctx context.Context) {
			close(renewing)
			<-ctx.Done()
		},
		func(ctx context.Context) error {
			syncErr.Store(fmt.Sprint(ctx.Err()))
			return ctx.Err()
		},
		func(ctx context.Context) error {
			pushErr.Store(fmt.Sprint(ctx.Err()))
			return ctx.Err()
		})

	parent, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan struct{})
	go func() {
		_ = runOnce(parent)
		close(done)
	}()
	within(t, renewing, time.Second, "renewal started")
	cancel()
	within(t, done, time.Second, "runOnce returned after the parent ended")

	if got := syncErr.Load(); got != context.Canceled.Error() {
		t.Fatalf("sync context = %v, want %v", got, context.Canceled)
	}
	if got := pushErr.Load(); got != context.Canceled.Error() {
		t.Fatalf("push context = %v, want %v", got, context.Canceled)
	}
}

// run --once runs under the signal context, so SIGTERM (the timer unit stopping) ends the
// phase in flight instead of the process; like runLoop it restores the default handling at
// once, so a second signal ends a phase that ignores its context.
func TestRunOnceFlagEndsWithASignal(t *testing.T) {
	renewing, release, restored := make(chan struct{}), make(chan struct{}), make(chan struct{})
	var restore sync.Once
	var pushErr atomic.Value
	setRunPhases(t, time.Minute, time.Minute, time.Minute,
		func(ctx context.Context) {
			close(renewing)
			<-ctx.Done()
			<-release
		},
		func(ctx context.Context) error { return ctx.Err() },
		func(ctx context.Context) error {
			pushErr.Store(fmt.Sprint(ctx.Err()))
			return ctx.Err()
		})
	signaled, send := context.WithCancel(context.Background())
	defer send()
	old := signalContext
	signalContext = func() (context.Context, context.CancelFunc) {
		return signaled, func() { restore.Do(func() { close(restored) }) }
	}
	t.Cleanup(func() { signalContext = old })

	cmd := runCmd()
	cmd.SetArgs([]string{"--once"})
	done := make(chan struct{})
	go func() {
		_ = cmd.Execute()
		close(done)
	}()
	within(t, renewing, time.Second, "renewal started")
	send()
	within(t, restored, time.Second, "default signal handling restored while the renewal still runs")
	close(release)
	within(t, done, time.Second, "run --once returned after the signal")

	if got := pushErr.Load(); got != context.Canceled.Error() {
		t.Fatalf("push context = %v, want %v", got, context.Canceled)
	}
}
