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
	// Enable each unit separately: a combined `enable --now frpc.service
	// adminhelper-agent.timer` fails atomically if the timer unit is not
	// installed yet, dragging frpc down with it.
	if err := exec.Command("systemctl", "enable", "--now", "frpc.service").Run(); err != nil {
		return fmt.Errorf("enable frpc.service: %w", err)
	}
	if err := exec.Command("systemctl", "enable", "--now", "adminhelper-agent.timer").Run(); err != nil {
		return fmt.Errorf("enable adminhelper-agent.timer: %w", err)
	}
	return nil
}

// restartFrpc restarts the frpc service.
func restartFrpc() error {
	return exec.Command("systemctl", "restart", "frpc.service").Run()
}

// disableFrpc stops the frpc service and keeps it from starting at boot.
func disableFrpc() error {
	return exec.Command("systemctl", "disable", "--now", "frpc.service").Run()
}
