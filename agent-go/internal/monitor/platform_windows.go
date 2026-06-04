// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package monitor

import "fmt"

// enableMonitorService registers the monitor with the Windows service.
// In normal operation, the monitor push is driven by the AdminHelper agent Windows service.
func enableMonitorService() error {
	// TODO: integrate with the AdminHelper agent Windows service
	fmt.Println("Hinweis: Bitte adminhelper-agent service install ausfuehren um den Windows-Dienst zu registrieren.")
	return nil
}
