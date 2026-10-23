// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package main

import (
	"context"
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
