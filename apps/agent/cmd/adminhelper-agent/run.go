// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package main

import (
	"context"
	"errors"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/spf13/cobra"

	"adminhelper-agent/internal/config"
	"adminhelper-agent/internal/enroll"
	"adminhelper-agent/internal/frpc"
	"adminhelper-agent/internal/httpclient"
	"adminhelper-agent/internal/logging"
	"adminhelper-agent/internal/monitor"
)

const defaultInterval = 5 * time.Minute

// stopWait bounds how long a stop waits for the cycle in flight once its ctx has
// ended: every blocking call of a cycle ends with the ctx, and a cycle that still
// does not come back must not hold the stop any longer.
var stopWait = 10 * time.Second

// cycle is the work of one tick of runLoop and the Windows service; a seam for
// the tests.
var cycle = func(ctx context.Context) { _ = runOnce(ctx) }

var logger = logging.For("agent")

func runCmd() *cobra.Command {
	var once bool

	cmd := &cobra.Command{
		Use:   "run",
		Short: "FRPC-Sync + Monitor-Push ausfuehren",
		Long:  "Ohne --once: Dauerbetrieb (alle 5 Minuten). Mit --once: einmaliger Durchlauf (fuer systemd-Timer).",
		RunE: func(cmd *cobra.Command, args []string) error {
			if once {
				return runOnce(context.Background())
			}
			// On Windows, run under the SCM when started as a service (reports
			// SERVICE_RUNNING; otherwise sc start times out with error 1053).
			// Interactive runs and all other platforms fall through to runLoop.
			if handled, err := runService(); handled {
				return err
			}
			return runLoop()
		},
	}
	cmd.Flags().BoolVar(&once, "once", false, "Einmaliger Durchlauf (fuer systemd-Timer / Task Scheduler)")
	return cmd
}

func runLoop() error {
	logger.Infof("Starte Dauerbetrieb (Intervall: %s)", defaultInterval)

	// SIGINT/SIGTERM end ctx at once, and with it the cycle in flight.
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	// stop() at once restores the default handling, so a second Ctrl-C ends the
	// process instead of waiting for the cycle. wait is read here: the callback
	// runs on a goroutine nobody joins.
	wait := stopWait
	context.AfterFunc(ctx, func() {
		stop()
		logger.Infof("%v, stopping (waiting at most %s for a running cycle)", context.Cause(ctx), wait)
	})

	serve(ctx, defaultInterval, cycle)
	return nil
}

// serve runs cycle at once and then on every tick of interval, each run on its
// own goroutine so serve sees the end of ctx while a cycle runs. A tick that
// comes while a cycle still runs is dropped: cycles never overlap. Once ctx has
// ended, serve waits for the running cycle at most stopWait and returns.
func serve(ctx context.Context, interval time.Duration, cycle func(context.Context)) {
	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	busy := false
	// Buffered: a cycle that outlives stopWait can still finish after serve is gone.
	done := make(chan struct{}, 1)
	start := func() {
		if busy || ctx.Err() != nil {
			return
		}
		busy = true
		go func() {
			cycle(ctx)
			done <- struct{}{}
		}()
	}

	start()
	for {
		select {
		case <-done:
			busy = false
		case <-ticker.C:
			start()
		case <-ctx.Done():
			if busy {
				select {
				case <-done:
				case <-time.After(stopWait):
				}
			}
			return
		}
	}
}

// runOnce performs one sync+push cycle. It always attempts both (a broken sync must
// not skip the monitor push) and logs every error, but RETURNS an error only for a
// permanent failure (rotated/revoked key, deleted server) so a oneshot run exits
// non-zero and systemd's OnFailure fires. Transient failures (5xx, network) are
// logged and swallowed — the next run retries (4.80/4.81). The long-running loop
// discards the return and keeps ticking.
func runOnce(ctx context.Context) error {
	// The agent runs as a oneshot (systemd timer / scheduled task), so renewal
	// is a check-at-each-run rather than a background timer: if the enrolled cert
	// is past ~50 % of its lifetime, renew it before the pushes.
	maybeRenewIdentity()
	var permanent error
	if err := frpc.Sync(); err != nil {
		logger.Errorf("FRPC-Sync Fehler: %v", err)
		if errors.Is(err, httpclient.ErrPermanent) {
			permanent = err
		}
	}
	if err := monitor.Push(ctx); err != nil {
		logger.Errorf("Monitor-Push Fehler: %v", err)
		if permanent == nil && errors.Is(err, httpclient.ErrPermanent) {
			permanent = err
		}
	}
	return permanent
}

// maybeRenewIdentity renews the enrolled mTLS cert when due. Best-effort: a
// transient issuer outage must not abort the cycle — the current cert is still
// valid for the remaining lifetime.
func maybeRenewIdentity() {
	dir := config.AgentPkiDir()
	if !enroll.Provisioned(dir) {
		return
	}
	base, err := config.ServerBaseURL()
	if err != nil {
		return // no server URL configured yet; nothing to renew against
	}
	renewed, err := enroll.MaybeRenew(dir, base, 30*time.Second)
	if err != nil {
		logger.Warnf("Cert-Renew Fehler: %v", err)
		return
	}
	if renewed {
		logger.Infof("mTLS-Client-Zertifikat erneuert.")
	}
}
