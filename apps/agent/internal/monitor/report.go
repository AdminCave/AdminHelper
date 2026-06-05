// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"bytes"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"time"
)

const logTag = "adminhelper-agent-monitor"

func logMsg(format string, args ...any) {
	fmt.Printf("[%s] %s\n", logTag, fmt.Sprintf(format, args...))
}

// BuildReport collects all metrics and builds the report.
func BuildReport(serviceNames []string) map[string]any {
	resources := map[string]any{
		"cpu_percent": collectCPU(),
	}
	if m := collectMemory(); m != nil {
		for k, v := range m {
			resources[k] = v
		}
	}
	if l := collectLoad(); l != nil {
		for k, v := range l {
			resources[k] = v
		}
	}
	if disks := collectDisks(); len(disks) > 0 {
		resources["disks"] = disks
	}
	if temps := collectTemperatures(); len(temps) > 0 {
		resources["temperatures"] = temps
	}

	report := map[string]any{
		"report_version": 2,
		"timestamp":      time.Now().UTC().Format("2006-01-02T15:04:05Z"),
		"resources":      resources,
		"uptime_seconds": collectUptime(),
	}

	// Service health (platform-specific)
	svcHealth := collectServiceHealth()
	if serviceNames != nil && len(serviceNames) > 0 {
		svcHealth["watched"] = collectWatchedServices(serviceNames)
	}
	report["systemd"] = svcHealth

	// Legacy: services key
	if len(serviceNames) > 0 {
		report["services"] = collectWatchedServices(serviceNames)
	}

	// Auto-detected plugins
	if docker := collectDocker(); docker != nil {
		report["docker"] = docker
	}
	if proxmox := collectProxmox(); proxmox != nil {
		report["proxmox"] = proxmox
	}
	if zfs := collectZFS(); zfs != nil {
		report["zfs"] = zfs
	}
	if smart := collectSmart(); smart != nil {
		report["smart"] = smart
	}

	return report
}

// PushReport sends the report to the monitoring service.
func PushReport(url, apiKey, serverID string, report map[string]any, cacert string, insecure bool) error {
	endpoint := fmt.Sprintf("%s/agent/%s/report", url, serverID)

	data, err := json.Marshal(report)
	if err != nil {
		return fmt.Errorf("JSON-Encoding: %w", err)
	}

	client, err := buildHTTPClient(cacert, insecure)
	if err != nil {
		return err
	}

	req, err := http.NewRequest("POST", endpoint, bytes.NewReader(data))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-API-Key", apiKey)

	resp, err := client.Do(req)
	if err != nil {
		return fmt.Errorf("Verbindungsfehler: %w", err)
	}
	defer resp.Body.Close()
	io.ReadAll(resp.Body)

	if resp.StatusCode >= 300 {
		return fmt.Errorf("HTTP-Fehler: %d", resp.StatusCode)
	}
	return nil
}

func buildHTTPClient(cacert string, insecure bool) (*http.Client, error) {
	tlsCfg := &tls.Config{}
	if insecure {
		tlsCfg.InsecureSkipVerify = true
	} else if cacert != "" {
		pem, err := os.ReadFile(cacert)
		if err != nil {
			return nil, fmt.Errorf("CA-Zertifikat lesen: %w", err)
		}
		pool := x509.NewCertPool()
		if !pool.AppendCertsFromPEM(pem) {
			return nil, fmt.Errorf("CA-Zertifikat ungueltig")
		}
		tlsCfg.RootCAs = pool
	}
	return &http.Client{
		Timeout:   15 * time.Second,
		Transport: &http.Transport{TLSClientConfig: tlsCfg},
	}, nil
}
