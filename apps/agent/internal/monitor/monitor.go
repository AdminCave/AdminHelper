// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"fmt"
	"os"
	"strings"

	"adminhelper-agent/internal/config"
)

// Init performs the initial setup of the monitor agent.
func Init(url, apiKey, serverID, services, cacert string, insecure bool) error {
	url = strings.TrimRight(url, "/")

	monitorDir := config.MonitorDir()
	// Holds the agent API key + pinned CA cert -> 0700.
	if err := os.MkdirAll(monitorDir, 0700); err != nil {
		return fmt.Errorf("Verzeichnis anlegen: %w", err)
	}
	_ = os.Chmod(monitorDir, 0700)

	// Copy the CA cert if provided
	storedCACert := ""
	if cacert != "" {
		if _, err := os.Stat(cacert); err != nil {
			return fmt.Errorf("CA-Zertifikat nicht gefunden: %s", cacert)
		}
		dest := config.MonitorDir() + "/ca.crt"
		data, err := os.ReadFile(cacert)
		if err != nil {
			return err
		}
		if err := os.WriteFile(dest, data, 0644); err != nil {
			return err
		}
		storedCACert = dest
		logMsg("CA-Zertifikat kopiert: %s", dest)
	}

	// Write the config
	entries := []config.KeyValue{
		{Key: "MONITOR_URL", Value: url},
		{Key: "API_KEY", Value: apiKey},
		{Key: "SERVER_ID", Value: serverID},
	}
	if services != "" {
		entries = append(entries, config.KeyValue{Key: "SERVICES", Value: services})
	}
	if storedCACert != "" {
		entries = append(entries, config.KeyValue{Key: "CACERT", Value: storedCACert})
	}
	if insecure {
		entries = append(entries, config.KeyValue{Key: "INSECURE", Value: "1"})
	}
	if err := config.WriteKeyValue(config.MonitorConfFile(), entries); err != nil {
		return fmt.Errorf("Config schreiben: %w", err)
	}
	logMsg("Config geschrieben: %s", config.MonitorConfFile())

	// Test push
	var serviceList []string
	if services != "" {
		for _, s := range strings.Split(services, ",") {
			if n := strings.TrimSpace(s); n != "" {
				serviceList = append(serviceList, n)
			}
		}
	}
	report := BuildReport(serviceList)
	if err := PushReport(url, apiKey, serverID, report, storedCACert, insecure); err != nil {
		logMsg("WARNUNG: Test-Push fehlgeschlagen: %v", err)
		logMsg("Pruefe URL und API-Key")
	} else {
		logMsg("Test-Push erfolgreich")
	}

	// Activate the service (platform-specific)
	if err := enableMonitorService(); err != nil {
		logMsg("WARNUNG: Service konnte nicht aktiviert werden: %v", err)
		logMsg("Bitte manuell aktivieren")
	}

	return nil
}

// Push reads the config and sends a one-off report.
func Push() error {
	cfg, err := config.LoadMonitorConfig()
	if err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		return fmt.Errorf("Config laden: %w", err)
	}
	if cfg.MonitorURL == "" || cfg.APIKey == "" || cfg.ServerID == "" {
		return fmt.Errorf("Config unvollstaendig — bitte erneut mit init einrichten")
	}

	report := BuildReport(cfg.Services)
	if err := PushReport(cfg.MonitorURL, cfg.APIKey, cfg.ServerID, report, cfg.CACert, cfg.Insecure); err != nil {
		logMsg("Report senden fehlgeschlagen: %v", err)
		return err
	}
	logMsg("Report gesendet")
	return nil
}
