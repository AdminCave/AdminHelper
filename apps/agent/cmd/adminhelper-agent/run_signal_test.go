// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package main

import (
	"context"
	"os"
	"os/signal"
	"syscall"
	"testing"
	"time"
)

func TestServeRunLoopEndsOnSIGTERMDuringACycle(t *testing.T) {
	started := make(chan struct{})
	sawEnd := make(chan struct{})
	setCycle(t, func(ctx context.Context) {
		close(started)
		<-ctx.Done()
		close(sawEnd)
	})
	t.Cleanup(func() { signal.Reset(os.Interrupt, syscall.SIGTERM) })

	result := make(chan error, 1)
	go func() { result <- runLoop() }()
	// The cycle runs only after runLoop has registered for the signals.
	within(t, started, 2*time.Second, "first cycle started")

	if err := syscall.Kill(os.Getpid(), syscall.SIGTERM); err != nil {
		t.Fatalf("send SIGTERM: %v", err)
	}
	select {
	case err := <-result:
		if err != nil {
			t.Fatalf("runLoop: %v", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("runLoop did not return within 2s of SIGTERM")
	}
	select {
	case <-sawEnd:
	default:
		t.Fatal("the running cycle did not see its ctx end")
	}
}
