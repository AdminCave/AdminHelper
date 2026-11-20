// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build !windows

package main

import "errors"

// applySelfUpdate exists on Windows only: elsewhere the package manager updates the agent.
func applySelfUpdate(string) error {
	return errors.New("self-update-apply is for Windows")
}

// runService is a no-op on non-Windows platforms: the agent always runs
// interactively / under systemd, never under the Windows SCM.
func runService() (handled bool, err error) {
	return false, nil
}
