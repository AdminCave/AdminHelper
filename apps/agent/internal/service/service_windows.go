// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package service

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"golang.org/x/sys/windows"
	"golang.org/x/sys/windows/registry"
	"golang.org/x/sys/windows/svc/eventlog"

	"adminhelper-agent/internal/config"
	"adminhelper-agent/internal/logging"
)

const serviceName = "AdminHelper-Agent"
const serviceDisplayName = "AdminHelper Agent — FRPC Sync + Monitoring"

// prepareInstallDir creates the program directory, or takes over an existing one, with the
// protected DACL of the data directory: the service runs its binaries from there as
// LocalSystem, so only SYSTEM and the Administrators may write to it.
func prepareInstallDir(dir string) error {
	return config.EnsureSecureDir(dir)
}

// programDirName is the agent's own folder under Program Files. "AdminHelper" is the MSI folder of
// the desktop app (its productName), which a protected DACL would close to its users.
const programDirName = "AdminHelper Agent"

// programDir returns the agent's program directory. The Program Files folder comes from the
// known-folder API, not from %ProgramFiles%, which the calling environment can set.
func programDir() (string, error) {
	pf, err := windows.KnownFolderPath(windows.FOLDERID_ProgramFiles, 0)
	if err != nil {
		return "", fmt.Errorf("Program Files folder: %w", err)
	}
	return filepath.Join(pf, programDirName), nil
}

// installBinary copies src to dest and hands dest to the Administrators group: under the policy
// "object creator" a file an elevated administrator writes belongs to that user, and the owner
// may change the DACL of the binary the service runs as LocalSystem.
func installBinary(src, dest string) error {
	data, err := os.ReadFile(src)
	if err != nil {
		return fmt.Errorf("Binary lesen: %w", err)
	}
	if err := os.WriteFile(dest, data, 0755); err != nil {
		return fmt.Errorf("Binary kopieren: %w", err)
	}
	if err := config.OwnByAdministrators(dest); err != nil {
		return fmt.Errorf("owner of %s: %w", dest, err)
	}
	return nil
}

// Install registers the AdminHelper agent as a native Windows service.
func Install() error {
	exePath, err := os.Executable()
	if err != nil {
		return fmt.Errorf("eigenen Pfad ermitteln: %w", err)
	}

	installDir, err := programDir()
	if err != nil {
		return err
	}
	if err := prepareInstallDir(installDir); err != nil {
		return fmt.Errorf("Installationsverzeichnis anlegen: %w", err)
	}

	// Copy the binary into the installation directory if needed
	destPath := filepath.Join(installDir, "adminhelper-agent.exe")
	if !strings.EqualFold(exePath, destPath) {
		if err := installBinary(exePath, destPath); err != nil {
			return err
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

	// Without a registered source, Windows keeps the agent's entries in the Application
	// log without a description.
	if err := registerEventSource(logging.EventSource); err != nil {
		fmt.Printf("WARNING: register the event source %s: %v\n", logging.EventSource, err)
	}

	// Recovery: restart after failure (after 60 seconds). Log a failure like the sc start below —
	// silently ignoring it left a missing auto-restart policy invisible (4.85).
	if out, err := exec.Command("sc", "failure", serviceName,
		"reset=", "86400",
		"actions=", "restart/60000/restart/60000/restart/60000",
	).CombinedOutput(); err != nil {
		fmt.Printf("WARNUNG: Recovery-Policy setzen: %s (%v)\n", string(out), err)
	}

	// Start the service
	if out, err := exec.Command("sc", "start", serviceName).CombinedOutput(); err != nil {
		fmt.Printf("WARNUNG: Service starten: %s\n", string(out))
	}

	fmt.Printf("Windows Service '%s' installiert und gestartet.\n", serviceName)
	return nil
}

// logger tags the hint of EnableTimer, so that it lands in agent.log and the diagnostics, not
// only on stdout.
var logger = logging.For("service")

// EnableTimer has no timer to enable on Windows: the agent's Windows service (service install)
// runs the cycles. It only gives that hint.
func EnableTimer() error {
	logger.Infof("Windows: Monitor-Push laeuft ueber den Agent-Dienst — bitte 'adminhelper-agent service install' ausfuehren.")
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

	if err := removeEventSource(logging.EventSource); err != nil {
		fmt.Printf("WARNING: remove the event source %s: %v\n", logging.EventSource, err)
	}

	fmt.Printf("Windows Service '%s' deinstalliert.\n", serviceName)
	return nil
}

// eventSourcesKey is the registry key below HKEY_LOCAL_MACHINE that holds the sources
// of the Application log; eventlog installs and removes them there.
const eventSourcesKey = `SYSTEM\CurrentControlSet\Services\EventLog\Application`

// registerEventSource registers source for the Application log with EventCreate.exe as
// its message file, for errors, warnings and information. A source that is already
// registered is no error and stays as it is.
func registerEventSource(source string) error {
	// eventlog.Install reports an existing source only as an error text, so look first.
	if k, err := registry.OpenKey(registry.LOCAL_MACHINE, eventSourcesKey+`\`+source, registry.QUERY_VALUE); err == nil {
		k.Close()
		return nil
	}
	return eventlog.InstallAsEventCreate(source, eventlog.Error|eventlog.Warning|eventlog.Info)
}

// removeEventSource removes the registration of source from the Application log. A
// source that is not registered is no error.
func removeEventSource(source string) error {
	if err := eventlog.Remove(source); err != nil && !errors.Is(err, registry.ErrNotExist) {
		return err
	}
	return nil
}
