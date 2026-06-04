// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package config

// Platform-specific paths are defined in paths_linux.go and paths_windows.go.
// Each file exports:
//   FrpDir()     — base directory for frpc configuration
//   MonitorDir() — base directory for monitor configuration

import "path/filepath"

// Derived paths (platform-independent)

func FrpConfigFile() string      { return filepath.Join(FrpDir(), "frpc.toml") }
func FrpAdminHelperConf() string { return filepath.Join(FrpDir(), "adminhelper.conf") }
func FrpHashFile() string        { return filepath.Join(FrpDir(), ".config-hash") }
func FrpPkiDir() string          { return filepath.Join(FrpDir(), "pki") }
func FrpCACert() string          { return filepath.Join(FrpDir(), "ca.crt") }
func MonitorConfFile() string    { return filepath.Join(MonitorDir(), "monitor.conf") }
