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

// Install registriert den AdminHelper-Agent als nativen Windows Service.
func Install() error {
	exePath, err := os.Executable()
	if err != nil {
		return fmt.Errorf("eigenen Pfad ermitteln: %w", err)
	}

	// Zielverzeichnis: C:\Program Files\AdminHelper\
	installDir := filepath.Join(os.Getenv("ProgramFiles"), "AdminHelper")
	if err := os.MkdirAll(installDir, 0755); err != nil {
		return fmt.Errorf("Installationsverzeichnis anlegen: %w", err)
	}

	// Binary ins Installationsverzeichnis kopieren falls noetig
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

	// Windows Service registrieren via sc.exe
	// Der Service startet "adminhelper-agent.exe run" als Hauptprozess
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

	// Recovery: Neustart nach Fehler (nach 60 Sekunden)
	exec.Command("sc", "failure", serviceName,
		"reset=", "86400",
		"actions=", "restart/60000/restart/60000/restart/60000",
	).Run()

	// Service starten
	if out, err := exec.Command("sc", "start", serviceName).CombinedOutput(); err != nil {
		fmt.Printf("WARNUNG: Service starten: %s\n", string(out))
	}

	fmt.Printf("Windows Service '%s' installiert und gestartet.\n", serviceName)
	return nil
}

// Uninstall deregistriert den Windows Service.
func Uninstall() error {
	// Service stoppen
	exec.Command("sc", "stop", serviceName).Run()

	// Service entfernen
	out, err := exec.Command("sc", "delete", serviceName).CombinedOutput()
	if err != nil {
		return fmt.Errorf("Service entfernen: %s (%w)", string(out), err)
	}

	fmt.Printf("Windows Service '%s' deinstalliert.\n", serviceName)
	return nil
}
