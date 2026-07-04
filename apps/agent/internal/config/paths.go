// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package config

// Platform-specific paths are defined in paths_linux.go and paths_windows.go.
// Each file exports:
//   FrpDir()     — base directory for frpc configuration
//   MonitorDir() — base directory for monitor configuration
//   LogDir()     — directory for the rotating agent log file

import "path/filepath"

// Derived paths (platform-independent)

func FrpConfigFile() string      { return filepath.Join(FrpDir(), "frpc.toml") }
func LogFile() string            { return filepath.Join(LogDir(), "agent.log") }
func FrpAdminHelperConf() string { return filepath.Join(FrpDir(), "adminhelper.conf") }
func FrpHashFile() string        { return filepath.Join(FrpDir(), ".config-hash") }
func FrpPkiDir() string          { return filepath.Join(FrpDir(), "pki") }
func FrpCACert() string          { return filepath.Join(FrpDir(), "ca.crt") }
func MonitorConfFile() string    { return filepath.Join(MonitorDir(), "monitor.conf") }
func MonitorCACert() string      { return filepath.Join(MonitorDir(), "ca.crt") }

// AgentPkiDir is the base directory for the agent's enrolled mTLS identity
// (ADR 0001: the client cert the agent presents on server pushes). Shared by the
// monitor push and the frpc sync. The file layout inside it is owned by the
// enroll package (key 0600 + cert + pinned trust bundle).
func AgentPkiDir() string { return filepath.Join(MonitorDir(), "identity") }

// MonitorInventoryStateFile persists the service-inventory throttle state
// ({hash, last_full_sent_unix}). It lives next to monitor.conf because the
// agent runs as a oneshot (systemd timer / scheduled task) — in-memory state
// does not survive between pushes.
func MonitorInventoryStateFile() string {
	return filepath.Join(MonitorDir(), ".inventory-state.json")
}
