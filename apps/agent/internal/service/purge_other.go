// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build !windows

package service

import "errors"

// PurgeSupported is false: on Linux and FreeBSD the package manager owns the agent's files.
const PurgeSupported = false

// Purge is only for Windows; service uninstall --purge refuses before it gets here.
func Purge() error {
	return errors.New("uninstall --purge is for Windows; remove the package with its package manager")
}
