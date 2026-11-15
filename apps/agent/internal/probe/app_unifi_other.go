// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build !linux

package probe

import "context"

// unifiOwner is unitOwner: the UniFi OS Server runs on Linux alone.
func unifiOwner(ctx context.Context, name string) (func(pid int32) bool, error) {
	return unitOwner(ctx, name)
}
