// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build !linux

package probe

import "fmt"

// journalOfThisHost returns ErrUnsupported: the log sensor reads the systemd journal, and the Windows
// event log is not read yet.
func journalOfThisHost() error {
	return fmt.Errorf("%w: the log sensor reads the systemd journal of Linux hosts", ErrUnsupported)
}
