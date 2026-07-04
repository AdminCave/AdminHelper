// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"time"

	"adminhelper-agent/internal/config"
	"adminhelper-agent/internal/enroll"
	"adminhelper-agent/internal/httpclient"
)

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
	if len(serviceNames) > 0 {
		// Collect once and reuse for both the "watched" sub-key and the legacy
		// top-level "services" key: avoids double systemctl/sc subprocess spawns
		// per cycle and two snapshots that could disagree if a service flips.
		watched := collectWatchedServices(serviceNames)
		svcHealth["watched"] = watched
		report["services"] = watched
	}
	report["systemd"] = svcHealth

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

// pushRetryDelay is a variable so tests can shorten the backoff.
var pushRetryDelay = 10 * time.Second

// PushReportParams groups monitor.PushReport's arguments (7 positionals before).
type PushReportParams struct {
	URL      string
	APIKey   string
	ServerID string
	Report   map[string]any
	TLS      config.TLSOpts
}

// PushReport sends the report to the monitoring service. A lost push wastes a
// full 5-minute slot, so a transient failure (server restart, network blip)
// gets one retry after a short backoff. The backoff honors ctx so a shutdown
// (e.g. the Windows SCM stop) aborts the wait instead of blocking up to 10s.
func PushReport(ctx context.Context, p PushReportParams) error {
	url := p.URL
	apiKey := p.APIKey
	serverID := p.ServerID
	report := p.Report
	cacert := p.TLS.CACert
	insecure := p.TLS.Insecure

	endpoint := fmt.Sprintf("%s/agent/%s/report", url, serverID)

	data, err := json.Marshal(report)
	if err != nil {
		return fmt.Errorf("JSON-Encoding: %w", err)
	}

	// Present the enrolled mTLS client cert when available (custom-root-only);
	// fall back to the legacy pinned-CA/insecure client until the agent enrolls.
	client, err := enroll.ServerClient(config.AgentPkiDir(), cacert, insecure, 15*time.Second)
	if err != nil {
		return err
	}

	if err := pushOnce(ctx, client, endpoint, apiKey, data); err != nil {
		logger.Warnf("Push fehlgeschlagen (%v), Retry in %s...", err, pushRetryDelay)
		select {
		case <-time.After(pushRetryDelay):
		case <-ctx.Done():
			return ctx.Err()
		}
		return pushOnce(ctx, client, endpoint, apiKey, data)
	}
	return nil
}

func pushOnce(ctx context.Context, client *http.Client, endpoint, apiKey string, data []byte) error {
	req, err := http.NewRequestWithContext(ctx, "POST", endpoint, bytes.NewReader(data))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-API-Key", apiKey)

	if _, err := httpclient.Do(client, req); err != nil {
		return fmt.Errorf("Push: %w", err)
	}
	return nil
}
