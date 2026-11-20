// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package selfupdate

import (
	"errors"
	"fmt"
	"os"
	"strings"
	"time"
)

// ErrRolledBack means the staged release was installed but did not come up healthy, or its
// install failed, and the earlier agent runs again.
var ErrRolledBack = errors.New("selfupdate: rolled back")

// ApplyHooks are the steps of swapping in a staged release. apply_windows.go fills them with the
// service control manager and the program directory, the tests with fakes; the order lives in
// Apply, so that it is testable on every platform.
type ApplyHooks struct {
	// ClearHealthy removes the marker of an earlier start, so that only the new release can set it.
	ClearHealthy func() error
	// Backup saves the installed agent and frpc.exe, for Restore.
	Backup func() error
	// Install stops the service, puts the staged files in place and starts it.
	Install func() error
	// WaitHealthy reports whether the service of version finished a cycle in time.
	WaitHealthy func(version string) bool
	// Restore stops the service, puts the saved files back and starts it.
	Restore func() error
	// MarkFailed remembers version, so that the daily check does not offer it again.
	MarkFailed func(version string)
	Logf       func(format string, args ...any)
}

// Apply installs the staged release version and keeps it only if its service reports a healthy
// cycle; otherwise the earlier agent comes back and version is not tried again.
func Apply(h ApplyHooks, version string) error {
	if err := h.ClearHealthy(); err != nil {
		return fmt.Errorf("selfupdate: clear the health marker: %w", err)
	}
	// Nothing has changed yet: the version is not at fault, the next check tries again.
	if err := h.Backup(); err != nil {
		return fmt.Errorf("selfupdate: back up the installed agent: %w", err)
	}
	h.Logf("installing agent %s", version)
	if err := h.Install(); err != nil {
		return rollback(h, version, fmt.Errorf("install %s: %w", version, err))
	}
	if !h.WaitHealthy(version) {
		return rollback(h, version, fmt.Errorf("agent %s finished no cycle in time", version))
	}
	h.Logf("agent %s runs", version)
	return nil
}

// rollback marks version first, so that a restore that fails half way does not lead to the same
// update again the next day.
func rollback(h ApplyHooks, version string, cause error) error {
	h.MarkFailed(version)
	h.Logf("%v; restoring the earlier agent", cause)
	if err := h.Restore(); err != nil {
		return fmt.Errorf("selfupdate: %w; restoring the earlier agent failed: %w", cause, err)
	}
	return fmt.Errorf("%w: %w", ErrRolledBack, cause)
}

// writeMarker records that the service of version finished a cycle.
func writeMarker(path, version string) error {
	return os.WriteFile(path, []byte(version+"\n"), 0o600)
}

// waitHealthy polls path until it names version or timeout has passed.
func waitHealthy(path, version string, timeout, poll time.Duration) bool {
	deadline := time.Now().Add(timeout)
	for {
		if b, err := os.ReadFile(path); err == nil && strings.TrimSpace(string(b)) == version {
			return true
		}
		if time.Now().After(deadline) {
			return false
		}
		time.Sleep(poll)
	}
}
