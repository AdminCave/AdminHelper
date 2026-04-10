//go:build linux

package frpc

import (
	"fmt"
	"os/exec"
)

// enableFrpcService aktiviert frpc und den AdminHelper-Agent-Timer via systemd.
func enableFrpcService() error {
	if err := exec.Command("systemctl", "daemon-reload").Run(); err != nil {
		return fmt.Errorf("daemon-reload: %w", err)
	}
	return exec.Command("systemctl", "enable", "--now", "frpc.service", "adminhelper-agent.timer").Run()
}

// restartFrpc startet den frpc-Service neu.
func restartFrpc() error {
	return exec.Command("systemctl", "restart", "frpc.service").Run()
}
