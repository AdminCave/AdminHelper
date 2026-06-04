// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package service

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

const serviceName = "AdminHelper-Agent"
const serviceDisplayName = "AdminHelper Agent — FRPC Sync + Monitoring"

// Install registers the AdminHelper agent as a native Windows service.
func Install() error {
	exePath, err := os.Executable()
	if err != nil {
		return fmt.Errorf("eigenen Pfad ermitteln: %w", err)
	}

	// Target directory: C:\Program Files\AdminHelper\
	installDir := filepath.Join(os.Getenv("ProgramFiles"), "AdminHelper")
	if err := os.MkdirAll(installDir, 0755); err != nil {
		return fmt.Errorf("Installationsverzeichnis anlegen: %w", err)
	}

	// Copy the binary into the installation directory if needed
	destPath := filepath.Join(installDir, "adminhelper-agent.exe")
	if !strings.EqualFold(exePath, destPath) {
		data, err := os.ReadFile(exePath)
		if err != nil {
			return fmt.Errorf("Binary lesen: %w", err)
		}
		if err := os.WriteFile(destPath, data, 0755); err != nil {
			return fmt.Errorf("Binary kopieren: %w", err)
		}
	}

	// Register the Windows service via sc.exe
	// The service starts "adminhelper-agent.exe run" as the main process
	binPath := fmt.Sprintf("\"%s\" run", destPath)
	out, err := exec.Command("sc", "create", serviceName,
		"binPath=", binPath,
		"DisplayName=", serviceDisplayName,
		"start=", "auto",
		"obj=", "LocalSystem",
	).CombinedOutput()
	if err != nil {
		return fmt.Errorf("Service registrieren: %s (%w)", string(out), err)
	}

	// Recovery: restart after failure (after 60 seconds)
	exec.Command("sc", "failure", serviceName,
		"reset=", "86400",
		"actions=", "restart/60000/restart/60000/restart/60000",
	).Run()

	// Start the service
	if out, err := exec.Command("sc", "start", serviceName).CombinedOutput(); err != nil {
		fmt.Printf("WARNUNG: Service starten: %s\n", string(out))
	}

	fmt.Printf("Windows Service '%s' installiert und gestartet.\n", serviceName)
	return nil
}

// Uninstall deregisters the Windows service.
func Uninstall() error {
	// Stop the service
	exec.Command("sc", "stop", serviceName).Run()

	// Remove the service
	out, err := exec.Command("sc", "delete", serviceName).CombinedOutput()
	if err != nil {
		return fmt.Errorf("Service entfernen: %s (%w)", string(out), err)
	}

	fmt.Printf("Windows Service '%s' deinstalliert.\n", serviceName)
	return nil
}
