// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package service

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

const serviceName = "adminhelper-agent"

// Install registers the AdminHelper agent as a systemd service with a timer.
func Install() error {
	exePath, err := os.Executable()
	if err != nil {
		return fmt.Errorf("eigenen Pfad ermitteln: %w", err)
	}

	// Copy the binary to a root-owned location first, so the root systemd unit
	// never pins ExecStart to a path a non-root user can write. Running
	// `sudo adminhelper-agent service install` from /home or /tmp would otherwise
	// leave a root unit pointing at a user-writable file — the user swaps the
	// binary and gets root code execution every 5 min. The Windows installer does
	// the same into Program Files (3.12). The fixed path also has no spaces, so the
	// unquoted ExecStart interpolation is safe.
	const dest = "/usr/local/bin/adminhelper-agent"
	if exePath != dest {
		data, err := os.ReadFile(exePath)
		if err != nil {
			return fmt.Errorf("Binary lesen: %w", err)
		}
		if err := os.WriteFile(dest, data, 0755); err != nil {
			return fmt.Errorf("Binary nach %s kopieren: %w", dest, err)
		}
	}

	// Write the service unit.
	// Twin of the packaged units in apps/agent/systemd/ (adminhelper-agent.service
	// + .timer, shipped via deb/rpm): both install paths must share the
	// `run --once` + timer semantics — keep them in sync. Only ExecStart differs
	// (dynamic exe path instead of /usr/bin).
	serviceUnit := fmt.Sprintf(`[Unit]
Description=AdminHelper Agent — FRPC Sync + Monitoring
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=%s run --once
# < OnUnitActiveSec=300 (Timer), but enough for the serial collector timeouts (Docker,
# smartctl 30s/disk) plus the monitor-push retry — 60s let a single dying disk + a push
# retry get SIGTERM'd, losing every report (4.13). Keep in sync with the packaged unit.
TimeoutStartSec=270
`, dest)

	// Write the timer unit
	timerUnit := `[Unit]
Description=AdminHelper Agent Timer (FRPC Sync + Monitoring alle 5 Minuten)

[Timer]
OnBootSec=60
OnUnitActiveSec=300
RandomizedDelaySec=30
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

// Uninstall deregisters the AdminHelper agent service.
func Uninstall() error {
	// Best-effort teardown: a missing/already-stopped unit is fine, but a real
	// failure (e.g. no root -> disable fails, timer keeps firing) must be visible
	// rather than masked by the success line below.
	for _, args := range [][]string{
		{"stop", serviceName + ".timer"},
		{"disable", serviceName + ".timer"},
		{"stop", serviceName + ".service"},
		{"disable", serviceName + ".service"},
	} {
		if err := exec.Command("systemctl", args...).Run(); err != nil {
			fmt.Printf("WARNUNG: systemctl %s: %v\n", strings.Join(args, " "), err)
		}
	}

	unitDir := "/etc/systemd/system"
	for _, unit := range []string{serviceName + ".service", serviceName + ".timer"} {
		if err := os.Remove(filepath.Join(unitDir, unit)); err != nil && !os.IsNotExist(err) {
			fmt.Printf("WARNUNG: %s entfernen: %v\n", unit, err)
		}
	}

	if err := exec.Command("systemctl", "daemon-reload").Run(); err != nil {
		fmt.Printf("WARNUNG: systemctl daemon-reload: %v\n", err)
	}
	fmt.Println("Service deinstalliert.")
	return nil
}
