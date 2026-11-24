// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Package push sets the monitor up (Init, the TOFU pin) and runs it: Push collects a report with
// package monitor, sends it with package send and keeps the report state through a lost push.
package push

import (
	"context"
	"fmt"
	"os"
	"time"

	"adminhelper-agent/internal/config"
	"adminhelper-agent/internal/logging"
	"adminhelper-agent/internal/monitor"
	"adminhelper-agent/internal/monitor/send"
)

// logger keeps the component of the monitor's logs, where these lines stood before.
var logger = logging.For("monitor")

// Reserve is the time a run keeps for send.Report after the collection: one
// request of at most 15 s, the retry delay of 10 s and the retry's 15 s
// (send.RetryDelay, the client timeout), plus a margin. A variable so tests can shorten it.
var Reserve = 45 * time.Second

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

	// With a deadline (a run of the agent), the collection ends Reserve before it:
	// a slow tool costs its part of the report, not the push. Without one (monitor push
	// by hand) the collection runs as long as its tools do.
	collectCtx := ctx
	if deadline, ok := ctx.Deadline(); ok {
		var cancel context.CancelFunc
		collectCtx, cancel = context.WithDeadline(ctx, deadline.Add(-Reserve))
		defer cancel()
	}
	c := monitor.Collect(collectCtx, cfg)
	if err := send.Report(ctx, send.Params{
		URL:      cfg.MonitorURL,
		APIKey:   cfg.APIKey,
		ServerID: cfg.ServerID,
		Report:   c.Report,
		TLS:      config.TLSOpts{CACert: cfg.CACert, Insecure: cfg.Insecure},
	}); err != nil {
		logger.Errorf("Report senden fehlgeschlagen: %v", err)
		c.Done(false)
		return err
	}
	c.Done(true)
	logger.Infof("Report gesendet")
	return nil
}
