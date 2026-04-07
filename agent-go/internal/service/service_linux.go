//go:build linux

package service

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
)

const serviceName = "srm-agent"

// Install registriert den SRM-Agent als systemd-Service mit Timer.
func Install() error {
	exePath, err := os.Executable()
	if err != nil {
		return fmt.Errorf("eigenen Pfad ermitteln: %w", err)
	}

	// Service-Unit schreiben
	serviceUnit := fmt.Sprintf(`[Unit]
Description=SRM Agent — FRPC Sync + Monitoring
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=%s run

[Install]
WantedBy=multi-user.target
`, exePath)

	// Timer-Unit schreiben
	timerUnit := `[Unit]
Description=SRM Agent Timer (alle 5 Minuten)

[Timer]
OnBootSec=60
OnUnitActiveSec=300
Persistent=true

[Install]
WantedBy=timers.target
`

	unitDir := "/etc/systemd/system"
	svcFile := filepath.Join(unitDir, serviceName+".service")
	tmrFile := filepath.Join(unitDir, serviceName+".timer")

	if err := os.WriteFile(svcFile, []byte(serviceUnit), 0644); err != nil {
		return fmt.Errorf("Service-Unit schreiben: %w", err)
	}
	if err := os.WriteFile(tmrFile, []byte(timerUnit), 0644); err != nil {
		return fmt.Errorf("Timer-Unit schreiben: %w", err)
	}

	if err := exec.Command("systemctl", "daemon-reload").Run(); err != nil {
		return fmt.Errorf("daemon-reload: %w", err)
	}
	if err := exec.Command("systemctl", "enable", "--now", serviceName+".timer").Run(); err != nil {
		return fmt.Errorf("Timer aktivieren: %w", err)
	}
	fmt.Printf("Service installiert: %s.timer aktiv\n", serviceName)
	return nil
}

// Uninstall deregistriert den SRM-Agent Service.
func Uninstall() error {
	exec.Command("systemctl", "stop", serviceName+".timer").Run()
	exec.Command("systemctl", "disable", serviceName+".timer").Run()
	exec.Command("systemctl", "stop", serviceName+".service").Run()
	exec.Command("systemctl", "disable", serviceName+".service").Run()

	unitDir := "/etc/systemd/system"
	os.Remove(filepath.Join(unitDir, serviceName+".service"))
	os.Remove(filepath.Join(unitDir, serviceName+".timer"))

	exec.Command("systemctl", "daemon-reload").Run()
	fmt.Println("Service deinstalliert.")
	return nil
}
