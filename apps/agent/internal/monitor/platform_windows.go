// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package monitor

// enableMonitorService is a deliberate no-op on Windows: the monitor push is driven
// by the AdminHelper agent Windows service (service install), not a separate monitor
// service. The hint goes through the package logger so it lands in the agent log /
// diagnostics, not just stdout.
func enableMonitorService() error {
	logger.Infof("Windows: Monitor-Push laeuft ueber den Agent-Dienst — bitte 'adminhelper-agent service install' ausfuehren.")
	return nil
}
