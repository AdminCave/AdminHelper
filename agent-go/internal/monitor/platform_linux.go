//go:build linux

package monitor

import "os/exec"

// enableMonitorService aktiviert den AdminHelper-Agent-Timer via systemd.
func enableMonitorService() error {
	return exec.Command("systemctl", "enable", "--now", "adminhelper-agent.timer").Run()
}
