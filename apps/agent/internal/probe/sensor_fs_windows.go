// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package probe

import (
	"fmt"
	"os"
)

// dirStatfs is Linux and FreeBSD alone: Windows has no statfs.
func dirStatfs(*os.Root, string, string) (fsUsage, error) {
	return fsUsage{}, fmt.Errorf("%w: sensor fs reads statfs, which Windows lacks", ErrUnsupported)
}
