//go:build linux

package frpc

import (
	"fmt"
	"os/exec"
)

// enableFrpcService aktiviert frpc und den Sync-Timer via systemd.
func enableFrpcService() error {
	if err := exec.Command("systemctl", "daemon-reload").Run(); err != nil {
		return fmt.Errorf("daemon-reload: %w", err)
	}
	return exec.Command("systemctl", "enable", "--now", "frpc.service", "srm-frpc-sync.timer").Run()
}

// restartFrpc startet den frpc-Service neu.
func restartFrpc() error {
	return exec.Command("systemctl", "restart", "frpc.service").Run()
}
