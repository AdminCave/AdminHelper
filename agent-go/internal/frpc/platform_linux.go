// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package frpc

import (
	"fmt"
	"os/exec"
)

// enableFrpcService enables frpc and the AdminHelper agent timer via systemd.
func enableFrpcService() error {
	if err := exec.Command("systemctl", "daemon-reload").Run(); err != nil {
		return fmt.Errorf("daemon-reload: %w", err)
	}
	return exec.Command("systemctl", "enable", "--now", "frpc.service", "adminhelper-agent.timer").Run()
}

// restartFrpc restarts the frpc service.
func restartFrpc() error {
	return exec.Command("systemctl", "restart", "frpc.service").Run()
}
