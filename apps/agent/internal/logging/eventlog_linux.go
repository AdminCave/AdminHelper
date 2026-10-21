// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package logging

// platformReporter returns nil on Linux: systemd keeps the service's stdout in the
// journal, so Init has nothing to report elsewhere.
func platformReporter() reportFunc {
	return nil
}
