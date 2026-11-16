// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build !linux && !freebsd

package execx

import "os/exec"

// ownGroup is a no-op where the agent has no process groups to signal: the kill reaches the command only.
func ownGroup(*exec.Cmd) {}
