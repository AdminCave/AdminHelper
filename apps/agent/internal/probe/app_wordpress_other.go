// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build !linux

package probe

import (
	"fmt"
	"os"
)

// openRegular is Linux alone: the files of a container are read there.
func openRegular(*os.Root, string, string) (*os.File, error) {
	return nil, fmt.Errorf("%w: the files of a container are read on Linux alone", ErrUnsupported)
}
