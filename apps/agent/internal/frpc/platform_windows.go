// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package frpc

import (
	"fmt"
	"os/exec"
)

// enableFrpcService starts the frpc process on Windows.
// In service mode, frpc is managed by the AdminHelper agent service itself.
func enableFrpcService() error {
	// Start frpc as a background process — in service mode the Windows
	// service takes over management.
	// TODO: integrate with the Windows Service Manager
	return exec.Command("sc", "start", "frpc").Run()
}

// restartFrpc restarts frpc on Windows.
func restartFrpc() error {
	if err := exec.Command("sc", "stop", "frpc").Run(); err != nil {
		fmt.Printf("[adminhelper-agent-frpc] WARNUNG: frpc stop: %v\n", err)
	}
	return exec.Command("sc", "start", "frpc").Run()
}
