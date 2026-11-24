// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Package send delivers a monitoring report to the monitoring service. It is a leaf: the report
// is only marshalled here, its content belongs to package monitor.
package send

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
	"adminhelper-agent/internal/logging"
)

// logger keeps the component of the monitor's logs, where these lines stood before.
var logger = logging.For("monitor")

// RetryDelay is the backoff before the one retry, a variable so tests can shorten it.
var RetryDelay = 10 * time.Second

// Params groups Report's arguments (7 positionals before).
type Params struct {
	URL      string
	APIKey   string
	ServerID string
	Report   any
	TLS      config.TLSOpts
}

// Report sends the report to the monitoring service. A lost push wastes a
// full 5-minute slot, so a transient failure (server restart, network blip)
// gets one retry after a short backoff. The backoff honors ctx so a shutdown
// (e.g. the Windows SCM stop) aborts the wait instead of blocking up to 10s.
func Report(ctx context.Context, p Params) error {
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
		logger.Warnf("Push fehlgeschlagen (%v), Retry in %s...", err, RetryDelay)
		select {
		case <-time.After(RetryDelay):
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
