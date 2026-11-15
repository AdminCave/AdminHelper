// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build !linux

package probe

import (
	"context"
	"fmt"
	"net"
	"os"
)

// dialRootSocket is Linux alone: the files of a container are read there.
func dialRootSocket(context.Context, *os.Root) (net.Conn, error) {
	return nil, fmt.Errorf("%w: the files of a container are read on Linux alone", ErrUnsupported)
}
