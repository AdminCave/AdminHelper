// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build !windows

package probe

import "context"

// osServiceForwarder: only Windows forwards ports through a service of its own (portproxy); the
// forwarder programs of the other systems are told by name.
func osServiceForwarder(context.Context, int32) (string, error) {
	return "", nil
}
