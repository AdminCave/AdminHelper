//go:build linux

package monitor

import "os/exec"

// enableMonitorService aktiviert den Monitor-Timer via systemd.
func enableMonitorService() error {
	return exec.Command("systemctl", "enable", "--now", "srm-monitor-agent.timer").Run()
}
