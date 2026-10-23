// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"context"
	"crypto/tls"
	"encoding/pem"
	"fmt"
	"net"
	"net/url"
	"os"
	"strings"
	"time"

	"adminhelper-agent/internal/config"
)

// InitParams groups monitor.Init's arguments (6 same-typed positionals before).
type InitParams struct {
	URL      string
	APIKey   string
	ServerID string
	Services string
	TLS      config.TLSOpts
}

// preserveServices keeps the configured watch list when a re-provisioning (token rotation) passes an
// empty services string, so the list isn't wiped. Extracted from Init for testability (6.15).
func preserveServices(services string) string {
	if services != "" {
		return services
	}
	if existing, err := config.LoadMonitorConfig(); err == nil && len(existing.Services) > 0 {
		return strings.Join(existing.Services, ",")
	}
	return services
}

// enableTimer is a variable so tests of Init never run systemctl.
var enableTimer = enableMonitorService

// Init performs the initial setup of the monitor agent.
func Init(p InitParams) error {
	url := p.URL
	apiKey := p.APIKey
	serverID := p.ServerID
	services := p.Services
	cacert := p.TLS.CACert
	insecure := p.TLS.Insecure

	url = strings.TrimRight(url, "/")
	if err := config.RequireHTTPS(url); err != nil {
		return err
	}
	// One trust source per call, as in provision.Run: beside --insecure,
	// httpclient.New skips the check even with a CA file.
	if cacert != "" && insecure {
		return fmt.Errorf("--cacert cannot be combined with --insecure: --cacert already verifies the server")
	}

	monitorDir := config.MonitorDir()
	// Holds the agent API key + pinned CA cert: 0700 on Linux, a protected ACL on
	// Windows, where it is the data root.
	if err := config.EnsureDataDir(monitorDir); err != nil {
		return fmt.Errorf("Verzeichnis anlegen: %w", err)
	}

	// Copy the CA cert if provided
	storedCACert := ""
	if cacert != "" {
		if _, err := os.Stat(cacert); err != nil {
			return fmt.Errorf("CA-Zertifikat nicht gefunden: %s", cacert)
		}
		dest := config.MonitorCACert()
		data, err := os.ReadFile(cacert)
		if err != nil {
			return err
		}
		if err := config.WriteFile(dest, data, 0644); err != nil {
			return err
		}
		storedCACert = dest
		logger.Infof("CA-Zertifikat kopiert: %s", dest)
	}

	// A blind --insecure (the deb/rpm postinst's alternative setup path) pins the
	// presented server cert (TOFU), so --insecure applies only to this init call —
	// the same defense provision.Run uses via pinIfBlindInsecure. Without a pin it
	// fails before monitor.conf is written: monitor.conf never stores INSECURE,
	// which would run every 5-minute push with TLS verification off, leaking the
	// long-lived API key each cycle.
	if insecure {
		pemBytes, err := fetchServerCertPEM(url)
		if err != nil {
			return fmt.Errorf("--insecure: cannot fetch the server certificate to pin: %w; run monitor init with --cacert instead", err)
		}
		if len(pemBytes) == 0 {
			return fmt.Errorf("--insecure: the server presented no certificate to pin; run monitor init with --cacert instead")
		}
		dest := config.MonitorCACert()
		if err := config.WriteFile(dest, pemBytes, 0644); err != nil {
			return fmt.Errorf("--insecure: cannot pin the server certificate: %w; run monitor init with --cacert instead", err)
		}
		storedCACert = dest
		logger.Infof("Server-Zertifikat gepinnt (TOFU) — --insecure gilt nur fuer diesen Aufruf.")
	}

	// Preserve an existing SERVICES line on re-provisioning: a token rotation passes empty services
	// and must not wipe the configured watch list (the derivation is in preserveServices so it is
	// unit-tested without the full HTTPS/TOFU/push path, 6.15).
	services = preserveServices(services)

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
	if err := config.WriteKeyValue(config.MonitorConfFile(), entries); err != nil {
		return fmt.Errorf("Config schreiben: %w", err)
	}
	logger.Infof("Config geschrieben: %s", config.MonitorConfFile())

	// Test push
	report := BuildReport(config.SplitServices(services))
	if err := PushReport(context.Background(), PushReportParams{
		URL:      url,
		APIKey:   apiKey,
		ServerID: serverID,
		Report:   report,
		TLS:      config.TLSOpts{CACert: storedCACert},
	}); err != nil {
		logger.Warnf("Test-Push fehlgeschlagen: %v", err)
		logger.Warnf("Pruefe URL und API-Key")
	} else {
		logger.Infof("Test-Push erfolgreich")
	}

	// Activate the service (platform-specific)
	if err := enableTimer(); err != nil {
		logger.Warnf("Service konnte nicht aktiviert werden: %v", err)
		logger.Warnf("Bitte manuell aktivieren")
	}

	return nil
}

// fetchServerCertPEM opens a bare TLS connection to url's host (verification off)
// solely to capture the presented certificate chain as PEM, so a blind --insecure
// init can pin it (TOFU) instead of persisting INSECURE=1. The captured cert is
// verified against nothing here — it is pinned immediately, matching provision.Run.
func fetchServerCertPEM(rawURL string) ([]byte, error) {
	u, err := url.Parse(rawURL)
	if err != nil {
		return nil, err
	}
	host := u.Host
	if u.Port() == "" {
		host = net.JoinHostPort(u.Hostname(), "443")
	}
	dialer := &net.Dialer{Timeout: 10 * time.Second}
	conn, err := tls.DialWithDialer(dialer, "tcp", host, &tls.Config{InsecureSkipVerify: true}) //nolint:gosec // TOFU capture, cert is pinned immediately
	if err != nil {
		return nil, err
	}
	defer conn.Close()
	var pemBytes []byte
	for _, c := range conn.ConnectionState().PeerCertificates {
		pemBytes = append(pemBytes, pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: c.Raw})...)
	}
	return pemBytes, nil
}

// Push reads the config and sends a one-off report. The ctx aborts the push
// retry backoff on shutdown so a stopping service is not blocked up to 10s.
func Push(ctx context.Context) error {
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

	reportStatePath := config.MonitorReportStateFile()
	report, nextReportState := buildReportWithState(cfg.Services, loadReportState(reportStatePath), time.Now())
	statePath := config.MonitorInventoryStateFile()
	newState, sentFull := throttleInventory(report, statePath, time.Now())
	if err := PushReport(ctx, PushReportParams{
		URL:      cfg.MonitorURL,
		APIKey:   cfg.APIKey,
		ServerID: cfg.ServerID,
		Report:   report,
		TLS:      config.TLSOpts{CACert: cfg.CACert, Insecure: cfg.Insecure},
	}); err != nil {
		logger.Errorf("Report senden fehlgeschlagen: %v", err)
		return err
	}
	if sentFull {
		// A write failure must never block the push flow — the next run then
		// simply sends the full inventory again.
		if err := saveInventoryState(statePath, newState); err != nil {
			logger.Warnf("Inventory-State speichern fehlgeschlagen: %v", err)
		}
	}
	// Saved only after the push went through, so a lost one leaves the window the next CPU share is
	// measured over open instead of moving it.
	if err := saveReportState(reportStatePath, nextReportState); err != nil {
		logger.Warnf("saving the report state failed: %v", err)
	}
	logger.Infof("Report gesendet")
	return nil
}
