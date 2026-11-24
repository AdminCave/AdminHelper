// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"context"
	"time"

	"adminhelper-agent/internal/config"
	"adminhelper-agent/internal/credentials"
)

// Cycle is one run of the monitoring: the report Collect built and the state Done writes once the
// caller knows whether the report went out.
type Cycle struct {
	Report *Report

	reportStatePath string
	prev, next      reportState
	inventoryPath   string
	inventory       inventoryState
	sentFull        bool
}

// Collect builds the report of one run: the plan, the credentials, the collectors and the inventory
// throttle. It writes no state; Done does, after the push.
func Collect(ctx context.Context, cfg *config.MonitorConfig) *Cycle {
	plan := currentPlan(ctx, cfg, config.MonitorPlanFile())
	work := &probeWork{probes: plan.Probes, scan: plan.Scan, markers: plan.Discovery.Markers, serviceLogs: plan.ServiceLogs}
	work.creds, work.credsErr = credentials.Load(config.MonitorCredentialsFile())
	if work.credsErr != nil {
		logger.Warnf("the credentials cannot be read, the probes that need one report no_credential: %v", work.credsErr)
	}
	c := &Cycle{reportStatePath: config.MonitorReportStateFile(), inventoryPath: config.MonitorInventoryStateFile()}
	c.prev = loadReportState(c.reportStatePath)
	c.Report, c.next = buildReportWithState(ctx, cfg.Services, work, c.prev, time.Now())
	c.inventory, c.sentFull = throttleInventory(c.Report, c.inventoryPath, time.Now())
	return c
}

// Done writes the state the run leaves: all of it after a push that went through, after a lost one
// only what must not wait for the next push.
func (c *Cycle) Done(pushed bool) {
	if !pushed {
		// The probes that ran keep their results all the same: the next report carries them with their
		// own time, and they are not due again before their interval, however long the monitoring service
		// is away; a counting probe counts on from where the run of its kept result stopped. The
		// self-throttle counts what the collectors cost, sent or not, a refused credential stays
		// refused and a bound one stays bound. The load gate counts the runs it read, so a host under
		// load is not measured in full while the service is away. The hourly update count and the
		// backup index stay as read, or every run would read them again until a push goes through
		// (R-1700). The rest of the state stays as the last push left it.
		kept := c.prev
		kept.Probes = c.next.Probes
		kept.Throttle = c.next.Throttle
		kept.Brake = c.next.Brake
		kept.Bindings = c.next.Bindings
		kept.Cursors = c.next.Cursors
		kept.LoadShed = c.next.LoadShed
		kept.Updates = c.next.Updates
		kept.ProxmoxBackups = c.next.ProxmoxBackups
		if err := saveReportState(c.reportStatePath, kept); err != nil {
			logger.Warnf("saving the probe results and the self-throttle failed: %v", err)
		}
		return
	}
	if c.sentFull {
		// A write failure must never block the push flow — the next run then
		// simply sends the full inventory again.
		if err := saveInventoryState(c.inventoryPath, c.inventory); err != nil {
			logger.Warnf("Inventory-State speichern fehlgeschlagen: %v", err)
		}
	}
	// Saved only after the push went through, so a lost one leaves the window the next CPU share is
	// measured over open instead of moving it.
	if err := saveReportState(c.reportStatePath, c.next); err != nil {
		logger.Warnf("saving the report state failed: %v", err)
	}
}
