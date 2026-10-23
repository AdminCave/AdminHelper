// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"time"

	"adminhelper-agent/internal/config"
	"adminhelper-agent/internal/enroll"
	"adminhelper-agent/internal/httpclient"
)

// BuildReport collects all metrics and builds the report. Without a report state it measures the CPU
// with the 1s sample; monitor init's test push neither reads nor writes the state.
func BuildReport(serviceNames []string) map[string]any {
	report, _ := buildReportWithState(context.Background(), serviceNames, reportState{}, time.Now())
	return report
}

// buildReportWithState is BuildReport measured against prev, the state the last successful push
// saved. It also returns the state to save once this report has been pushed. ctx ends the tool calls
// of the system state, service (systemctl, sc), docker, proxmox, zfs and smart collectors.
func buildReportWithState(ctx context.Context, serviceNames []string, prev reportState, now time.Time) (map[string]any, reportState) {
	cpuPercent, cpuNow := collectCPUSince(prev.CPU, now)
	resources := map[string]any{
		"cpu_percent": cpuPercent,
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
	if s := collectSwapAndCPUCount(); s != nil {
		for k, v := range s {
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
		"report_version": 3,
		"timestamp":      time.Now().UTC().Format("2006-01-02T15:04:05Z"),
		"resources":      resources,
		"uptime_seconds": collectUptime(),
		"host":           collectHostFacts(),
	}

	// The collector hands prev on with what it measured replaced, so a value it could not read this
	// time stays the base for the next report.
	systemState, next := systemStateCollector(ctx, prev)
	next.CPU = cpuNow
	if len(systemState) > 0 {
		report["system_state"] = systemState
	}

	// Service health (platform-specific)
	svcHealth := serviceHealthCollector(ctx)
	if len(serviceNames) > 0 {
		// Collect once and reuse for both the "watched" sub-key and the legacy
		// top-level "services" key: avoids double systemctl/sc subprocess spawns
		// per cycle and two snapshots that could disagree if a service flips.
		watched := collectWatchedServices(ctx, serviceNames)
		svcHealth["watched"] = watched
		report["services"] = watched
	}
	report["systemd"] = svcHealth

	// Auto-detected plugins (via pluginCollectors so tests can stub the subprocess calls).
	if docker := pluginCollectors.docker(ctx); docker != nil {
		report["docker"] = docker
	}
	if proxmox := pluginCollectors.proxmox(ctx); proxmox != nil {
		report["proxmox"] = proxmox
	}
	if zfs := pluginCollectors.zfs(ctx); zfs != nil {
		report["zfs"] = zfs
	}
	if smart, absent := pluginCollectors.smart(ctx); smart != nil {
		report["smart"] = smart
	} else {
		report["smart_absent"] = map[string]string{"reason": absent}
	}

	return report, next
}

// pushRetryDelay is a variable so tests can shorten the backoff.
var pushRetryDelay = 10 * time.Second

// pluginCollectors indirects the auto-detected plugin collectors so tests can stub the real
// docker/pvesh/zpool/smartctl subprocess calls, which are slow and host-dependent (6.18).
var pluginCollectors = struct {
	docker  func(context.Context) map[string]any
	proxmox func(context.Context) map[string]any
	zfs     func(context.Context) map[string]any
	smart   func(context.Context) ([]SmartDisk, string)
}{collectDocker, collectProxmox, collectZFS, collectSmart}

// serviceHealthCollector indirects the systemctl/sc service-health probe for the same reason (6.18).
var serviceHealthCollector = collectServiceHealth

// systemStateCollector indirects the system state probe for the same reason (6.18).
var systemStateCollector = collectSystemState

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
	// Close the pool's idle keep-alive connections on return: a fresh client is built per cycle, so
	// otherwise the discarded transport's idle conns linger up to ~90s (IdleConnTimeout) before GC.
	// Harmless in oneshot mode, tidier in the long-running loop / Windows service (5.6).
	defer client.CloseIdleConnections()

	if err := pushOnce(ctx, client, endpoint, apiKey, data); err != nil {
		// A permanent failure (rotated/revoked key, deleted server) won't heal on a
		// retry — surface it at once so the oneshot exits non-zero (4.81).
		if errors.Is(err, httpclient.ErrPermanent) {
			return err
		}
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
