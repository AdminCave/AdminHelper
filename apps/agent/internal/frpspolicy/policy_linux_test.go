// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package frpspolicy

import (
	"path/filepath"
	"syscall"
	"testing"
	"time"
)

// Opening a FIFO without a writer blocks; the plugin would hang every NewProxy on it.
func TestSourceRefusesAFIFO(t *testing.T) {
	path := filepath.Join(t.TempDir(), "frps-policy.json")
	if err := syscall.Mkfifo(path, 0o644); err != nil {
		t.Fatal(err)
	}
	done := make(chan error, 1)
	go func() {
		_, err := NewSource(path).Current()
		done <- err
	}()
	select {
	case err := <-done:
		if err == nil {
			t.Error("Current on a FIFO = nil, want an error")
		}
	case <-time.After(5 * time.Second):
		t.Fatal("Current blocked on a FIFO")
	}
}
