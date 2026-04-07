package monitor

import (
	"fmt"
	"os"
	"strings"

	"srm-agent/internal/config"
)

// Init fuehrt die Ersteinrichtung des Monitor-Agents durch.
func Init(url, apiKey, serverID, services, cacert string, insecure bool) error {
	url = strings.TrimRight(url, "/")

	monitorDir := config.MonitorDir()
	if err := os.MkdirAll(monitorDir, 0755); err != nil {
		return fmt.Errorf("Verzeichnis anlegen: %w", err)
	}

	// CA-Cert kopieren falls angegeben
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

	// Config schreiben
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

	// Test-Push
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

	// Service aktivieren (plattform-spezifisch)
	if err := enableMonitorService(); err != nil {
		logMsg("WARNUNG: Service konnte nicht aktiviert werden: %v", err)
		logMsg("Bitte manuell aktivieren")
	}

	return nil
}

// Push liest die Config und sendet einen einmaligen Report.
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
