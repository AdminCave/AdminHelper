// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package config

// EnsureSecureDir(dir string) error is defined in securedir_linux.go and
// securedir_windows.go: it creates a secret-bearing directory before its first use
// and restricts it to the agent.

// The well-known SIDs of LocalSystem and of the built-in Administrators group.
const (
	systemSID         = "S-1-5-18"
	administratorsSID = "S-1-5-32-544"
)

// trustedOwner reports whether an existing directory whose owner is the SID sid
// (string form) is one the agent keeps. Only Windows asks: the agent runs as
// LocalSystem there and creates its directories owned by the Administrators, so a
// directory with any other owner is not one the agent created.
func trustedOwner(sid string) bool {
	return sid == systemSID || sid == administratorsSID
}
