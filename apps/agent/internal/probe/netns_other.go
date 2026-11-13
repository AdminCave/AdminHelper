// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build !linux

package probe

import (
	"context"
	"errors"
)

// namespaceProcesses is Linux only: only docker on Linux publishes ports without its own listener.
func namespaceProcesses(context.Context, int32, uint16) ([]int32, error) {
	return nil, errors.New("container namespaces are read on Linux only")
}
