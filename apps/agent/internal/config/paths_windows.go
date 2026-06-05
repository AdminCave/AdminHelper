// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package config

import (
	"os"
	"path/filepath"
)

func FrpDir() string {
	return filepath.Join(os.Getenv("ProgramData"), "AdminHelper", "frp")
}

func MonitorDir() string {
	return filepath.Join(os.Getenv("ProgramData"), "AdminHelper")
}
