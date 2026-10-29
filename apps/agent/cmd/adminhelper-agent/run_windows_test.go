// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package main

import (
	"context"
	"sync/atomic"
	"testing"
	"time"

	"golang.org/x/sys/windows/svc"
)

func TestServeWindowsStopWaitsForTheCycle(t *testing.T) {
	started := make(chan struct{})
	var ended atomic.Bool
	// The cycle ends only through its ctx and needs a moment after that, so an
	// Execute that does not wait for it returns before ended is set.
	setCycle(t, func(ctx context.Context) {
		close(started)
		<-ctx.Done()
		time.Sleep(100 * time.Millisecond)
		ended.Store(true)
	})

	r := make(chan svc.ChangeRequest, 1)
	changes := make(chan svc.Status, 8)
	returned := make(chan struct{})
	var svcSpecific bool
	var exitCode uint32
	go func() {
		svcSpecific, exitCode = (&agentService{}).Execute(nil, r, changes)
		close(returned)
	}()
	within(t, started, 2*time.Second, "first cycle started")

	r <- svc.ChangeRequest{Cmd: svc.Stop}
	within(t, returned, 2*time.Second, "Execute returned after Stop")
	if !ended.Load() {
		t.Fatal("Execute returned before the running cycle ended")
	}
	if svcSpecific || exitCode != 0 {
		t.Fatalf("Execute = (%v, %d), want (false, 0)", svcSpecific, exitCode)
	}

	close(changes) // Execute has returned and sends nothing more
	var states []svc.Status
	stopPending := false
	for s := range changes {
		states = append(states, s)
		if s.State == svc.StopPending && s.WaitHint > 0 {
			stopPending = true
		}
	}
	if !stopPending {
		t.Fatalf("no StopPending with a WaitHint among %+v", states)
	}
}
