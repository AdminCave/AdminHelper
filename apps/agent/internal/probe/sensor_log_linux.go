// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package probe

import "fmt"

// journalOfThisHost returns ErrUnsupported on a host systemd does not run: it keeps no journal.
func journalOfThisHost() error {
	if !systemdBooted() {
		return fmt.Errorf("%w: systemd does not run this host", ErrUnsupported)
	}
	return nil
}
