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
	"maps"
	"net/http"
	"strings"
	"time"

	"adminhelper-agent/internal/config"
	"adminhelper-agent/internal/credentials"
	"adminhelper-agent/internal/discovery"
	"adminhelper-agent/internal/enroll"
	"adminhelper-agent/internal/httpclient"
	"adminhelper-agent/internal/probe"
)

// BuildReport collects all metrics and builds the report. Without a report state it measures the CPU
// with the 1s sample; monitor init's test push neither reads nor writes the state, and runs no probe.
func BuildReport(serviceNames []string) map[string]any {
	report, _ := buildReportWithState(context.Background(), serviceNames, nil, reportState{}, time.Now())
	return report
}

// probeWork is what the probe phase of a run works with: the plan's probes and the credentials stored
// on this host (credentials.Load), or why they could not be read; and whether the plan asks for a
// discovery of this host, with the markers it looks for; and whether it asks for the error lines of
// failed units.
type probeWork struct {
	probes      []probe.Probe
	creds       map[string]credentials.Credential
	credsErr    error
	scan        bool
	markers     []probe.Marker
	serviceLogs bool
}

// discoveryCollector is the discovery's name in the self-measurement and the throttle.
const discoveryCollector = "discovery"

// runDiscovery discovers this host; a seam for the tests.
var runDiscovery = discovery.Run

// buildReportWithState is BuildReport measured against prev, the state the last successful push
// saved, with the due ones of work's probes run after the collectors. It also returns the state to
// save once this report has been pushed. ctx ends the tool calls of the system state, service
// (systemctl, sc), docker, proxmox, zfs and smart collectors and the probes. Every collector runs in a
// measuring frame (self.collectors); the optional ones and the probes are throttled by their
// time-limit hits, and under load the load gate holds them and a discovery back (self.load_shed).
// Without work no probe runs and the report names no credential.
func buildReportWithState(ctx context.Context, serviceNames []string, work *probeWork, prev reportState, now time.Time) (map[string]any, reportState) {
	m := newSelfMeasure(prev.Throttle)
	report := map[string]any{"report_version": 4}

	var cpuNow *cpuSample
	var resources map[string]any
	m.core(ctx, "resources", func(ctx context.Context) {
		resources, cpuNow = collectResources(ctx, prev.CPU, now)
		report["resources"] = resources
		report["uptime_seconds"] = collectUptime()
		report["host"] = collectHostFacts()
	})
	report["timestamp"] = time.Now().UTC().Format("2006-01-02T15:04:05Z")

	// The collector hands prev on with what it measured replaced, so a value it could not read this
	// time stays the base for the next report.
	var next reportState
	m.core(ctx, "system_state", func(ctx context.Context) {
		var systemState map[string]any
		systemState, next = systemStateCollector(ctx, prev)
		if len(systemState) > 0 {
			report["system_state"] = systemState
		}
	})
	next.CPU = cpuNow

	// Service health (platform-specific)
	m.core(ctx, "services", func(ctx context.Context) {
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
	})

	// The core always runs; what comes after it waits while the host is under load.
	reading := readLoad(resources, prev.CPU, cpuNow)
	next.LoadShed = prev.LoadShed.after(len(reading.over()) > 0, now)
	m.shedding = next.LoadShed.Active

	// Auto-detected plugins (via pluginCollectors so tests can stub the subprocess calls).
	m.optional(ctx, "docker", func(ctx context.Context) {
		if docker := pluginCollectors.docker(ctx); docker != nil {
			report["docker"] = docker
		}
	})
	// A throttled run leaves next.ProxmoxBackups as prev had it, so the saved index stays.
	m.optional(ctx, "proxmox", func(ctx context.Context) {
		proxmox, backups := pluginCollectors.proxmox(ctx, prev.ProxmoxBackups, now)
		next.ProxmoxBackups = backups
		if proxmox != nil {
			report["proxmox"] = proxmox
		}
	})
	m.optional(ctx, "zfs", func(ctx context.Context) {
		if zfs := pluginCollectors.zfs(ctx); zfs != nil {
			report["zfs"] = zfs
		}
	})
	m.optional(ctx, "smart", func(ctx context.Context) {
		if smart, absent := pluginCollectors.smart(ctx); smart != nil {
			report["smart"] = smart
		} else {
			report["smart_absent"] = map[string]string{"reason": absent}
		}
	})
	// The error lines of a failed unit go out once per failure while the plan asks for them
	// (servicelogs.go); on Windows those of a stopped automatic service with an exit, which the block
	// names in log_units. The failures that ended are forgotten even in a run that reads no lines; with
	// the switch off the state is empty, so lines go out anew once it is on again. Between two runs
	// its throttle stays as it was.
	if svc, _ := report["systemd"].(map[string]any); work != nil && work.serviceLogs && serviceLogsSupported && svc != nil {
		failed, since := serviceLogUnits(svc)
		if serviceLogUnitsListed {
			svc["log_units"] = failed
		}
		next.ServiceLogs = stillFailed(prev.ServiceLogs, failed, since)
		m.optional(ctx, serviceLogsCollector, func(ctx context.Context) {
			if logs := collectServiceLogs(ctx, failed, since, next.ServiceLogs); len(logs) > 0 {
				svc["failed_logs"] = logs
			}
		})
	} else {
		next.ServiceLogs = nil
		if t, ok := prev.Throttle[serviceLogsCollector]; ok {
			m.next[serviceLogsCollector] = t
		}
	}

	// The probes run in what is left of ctx. A probe that times out is its own result, not a hit: one
	// hanging service would slow down the probes of every other. The phase's hit is a due probe the
	// run's time did not leave room for; its factor stretches the interval of every probe.
	probeFactor := prev.Throttle[probesCollector].factor()
	acc := &probe.Access{Brake: maps.Clone(prev.Brake), Bindings: maps.Clone(prev.Bindings), Cursors: maps.Clone(prev.Cursors)}
	var probes []probe.Probe
	if work != nil {
		probes, acc.Credentials, acc.StoreErr = work.probes, work.creds, work.credsErr
		// The refs alone, so the monitoring service can tell a missing credential; a store that could
		// not be read sends no block, and the refs the service has stay.
		if work.credsErr == nil {
			stored := map[string]bool{}
			for _, ref := range credentials.Refs(work.creds) {
				stored[ref] = true
			}
			report["credentials"] = stored
		}
	}
	if m.shedding {
		// No probe runs: the plan's probes send their last results, and they are due once it is over.
		next.Probes = probe.Results{}
		for _, p := range probes {
			if res, ok := prev.Probes[p.ID]; ok {
				next.Probes[p.ID] = res
			}
		}
		m.shed(probesCollector)
	} else {
		postponed := 0
		st := measured(ctx, func(ctx context.Context) {
			next.Probes, _, postponed = runDueProbes(ctx, probes, prev.Probes, probeFactor, acc, time.Now())
		})
		m.record(probesCollector, st, postponed)
	}
	report["probes"] = next.Probes
	next.Brake = acc.KeptBrake()
	next.Bindings = acc.KeptBindings()
	next.Cursors = acc.KeptCursors(probes)

	// A discovery runs when the monitoring service asks for one, in what is left of ctx; it takes a
	// frame of its own. Between two of them its throttle stays as it was. A discovery the load gate
	// holds back stays asked for until one is sent.
	if work != nil && work.scan {
		m.optional(ctx, discoveryCollector, func(ctx context.Context) {
			report["discovery"] = runDiscovery(ctx, work.markers)
		})
	} else if t, ok := prev.Throttle[discoveryCollector]; ok {
		m.next[discoveryCollector] = t
	}

	next.Throttle = m.next
	report["self"] = map[string]any{"collectors": m.stats, "load_shed": next.LoadShed.block(reading)}
	return report, next
}

// collectResources is the report's resources block, the CPU share measured since prevCPU, and the CPU
// counters now. From topProcessesFrom CPU or memory it names the busiest processes; that runs outside
// the load gate, since it is under load that they are asked for.
func collectResources(ctx context.Context, prevCPU *cpuSample, now time.Time) (map[string]any, *cpuSample) {
	cpuPercent, cpuNow := collectCPUSince(prevCPU, now)
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
	if n := collectNetwork(); n != nil {
		for k, v := range n {
			resources[k] = v
		}
	}
	if disks := collectDisks(); len(disks) > 0 {
		resources["disks"] = disks
	}
	if temps := collectTemperatures(); len(temps) > 0 {
		resources["temperatures"] = temps
	}
	if underLoad(resources) {
		if top := collectTopProcesses(ctx); top != nil {
			resources["top_processes"] = top
		}
	}
	return resources, cpuNow
}

// pushRetryDelay is a variable so tests can shorten the backoff.
var pushRetryDelay = 10 * time.Second

// pluginCollectors indirects the auto-detected plugin collectors so tests can stub the real
// docker/pvesh/zpool/smartctl subprocess calls, which are slow and host-dependent (6.18).
var pluginCollectors = struct {
	docker  func(context.Context) map[string]any
	proxmox func(context.Context, *backupIndexCheck, time.Time) (map[string]any, *backupIndexCheck)
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

// A report carries the error lines of at most maxLogUnits failed units, maxLogLines lines each; the
// rest follow in the next report. The monitoring service keeps no more (MAX_LOG_UNITS,
// MAX_LOG_LINES in service_inventory.py).
const (
	maxLogUnits = 20
	maxLogLines = 10
)

// serviceLogsCollector is the error lines' name in the self-measurement and the throttle.
const serviceLogsCollector = "service_logs"

// serviceLogReader opens one run's reader of the error lines of a unit (newServiceLogReader); a seam
// for the tests.
var serviceLogReader = newServiceLogReader

// failedUnits are the failed units of the systemd block in its order, and the since of each from
// failed_details ("" for a unit without one).
func failedUnits(systemd map[string]any) ([]string, map[string]string) {
	failed, _ := systemd["failed"].([]string)
	since := map[string]string{}
	details, _ := systemd["failed_details"].([]map[string]string)
	for _, d := range details {
		since[d["unit"]] = d["since"]
	}
	return failed, since
}

// stillFailed is sent without the failures that ended: a unit no longer failed, or failed anew
// (another since), gets its lines again. A since that is not known on one side (no failed_details
// in this run or when the lines went out: the batched systemctl show failed) counts as the same
// failure, so a failed detail query sends nothing twice.
func stillFailed(sent map[string]string, failed []string, since map[string]string) map[string]string {
	kept := map[string]string{}
	for _, unit := range failed {
		s, ok := sent[unit]
		if !ok || (s != since[unit] && s != "" && since[unit] != "") {
			continue
		}
		if since[unit] != "" {
			s = since[unit]
		}
		kept[unit] = s
	}
	return kept
}

// collectServiceLogs reads the error lines of every failed unit whose failure has not been sent,
// at most maxLogUnits, and marks each read one in sent (unit → since). A unit whose lines could
// not be read stays unmarked and is asked again in the next report. The result is the
// systemd.failed_logs block: {unit: {since, lines}}, lines oldest first.
func collectServiceLogs(ctx context.Context, failed []string, since, sent map[string]string) map[string]any {
	logs := map[string]any{}
	read := serviceLogReader()
	for _, unit := range failed {
		if len(logs) == maxLogUnits {
			break
		}
		if _, done := sent[unit]; done {
			continue
		}
		lines, ok := read(ctx, unit)
		if !ok {
			continue
		}
		entry := map[string]any{"lines": lines}
		if since[unit] != "" {
			entry["since"] = since[unit]
		}
		logs[unit] = entry
		sent[unit] = since[unit]
	}
	return logs
}

// serviceLogLines are the last maxLogLines non-empty lines of journalctl's output, each through
// cleanLogLine. --lines counts entries, and one entry may span several lines.
func serviceLogLines(out []byte) []string {
	lines := []string{}
	for _, line := range strings.Split(string(out), "\n") {
		if strings.TrimSpace(line) != "" {
			lines = append(lines, line)
		}
	}
	if len(lines) > maxLogLines {
		lines = lines[len(lines)-maxLogLines:]
	}
	for i, line := range lines {
		lines[i] = cleanLogLine(line)
	}
	return lines
}
