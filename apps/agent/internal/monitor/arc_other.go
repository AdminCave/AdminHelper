// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build !linux && !freebsd

package monitor

// arcReclaimable is 0: the agent reads the ZFS ARC on Linux and FreeBSD only.
func arcReclaimable() uint64 { return 0 }
