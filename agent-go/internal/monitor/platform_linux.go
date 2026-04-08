//go:build linux

package monitor

import "os/exec"

// enableMonitorService aktiviert den SRM-Agent-Timer via systemd.
func enableMonitorService() error {
	return exec.Command("systemctl", "enable", "--now", "srm-agent.timer").Run()
}
