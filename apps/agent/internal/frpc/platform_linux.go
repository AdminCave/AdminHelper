// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package frpc

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"time"

	"adminhelper-agent/internal/config"
)

// reloadTimeout bounds `frpc reload`: frpc answers on loopback at once, a hang counts as a failed
// reload, which a restart then replaces.
const reloadTimeout = 15 * time.Second

// systemctlTimeout caps every systemctl call of the FRP sync: a hung systemd or D-Bus would hold
// the run until the unit's TimeoutStartSec, and the push comes after the sync. A var only so tests
// can shorten it.
var systemctlTimeout = 15 * time.Second

// systemctl runs one systemctl call under systemctlTimeout and ctx. A call that one of them ended
// returns the context's error (context.DeadlineExceeded or context.Canceled): exec itself reports
// it as the ExitError "signal: killed", which would pass a hung systemctl off as a failing one.
func systemctl(ctx context.Context, args ...string) error {
	ctx, cancel := context.WithTimeout(ctx, systemctlTimeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, "systemctl", args...)
	cmd.WaitDelay = 2 * time.Second
	err := cmd.Run()
	if err != nil && ctx.Err() != nil {
		return ctx.Err()
	}
	return err
}

// enableFrpcService enables and starts frpc via systemd. It leaves adminhelper-agent.timer alone:
// the sync of every run calls it, also of a `run` without --once, beside which an enabled timer
// would run each cycle twice. Only the setup enables the timer (service.EnableTimer, R-0641).
func enableFrpcService(ctx context.Context) error {
	if err := systemctl(ctx, "daemon-reload"); err != nil {
		return fmt.Errorf("daemon-reload: %w", err)
	}
	if err := systemctl(ctx, "enable", "--now", "frpc.service"); err != nil {
		return fmt.Errorf("enable frpc.service: %w", err)
	}
	return nil
}

// restartFrpc restarts the frpc service.
func restartFrpc(ctx context.Context) error {
	return systemctl(ctx, "restart", "frpc.service")
}

// disableFrpc stops the frpc service and keeps it from starting at boot.
func disableFrpc(ctx context.Context) error {
	return systemctl(ctx, "disable", "--now", "frpc.service")
}

// frpcActive reports whether frpc.service runs; `is-active` exits non-zero for every other state.
// A call without an exit status (timeout, end of ctx, not started) is an error, not "not active":
// the sync would then renew the admin API and restart a frpc that may run.
func frpcActive(ctx context.Context) (bool, error) {
	err := systemctl(ctx, "is-active", "--quiet", "frpc.service")
	if err == nil {
		return true, nil
	}
	var exitErr *exec.ExitError
	if errors.As(err, &exitErr) && exitErr.ExitCode() > 0 {
		return false, nil
	}
	return false, fmt.Errorf("systemctl is-active frpc.service: %w", err)
}

// frpcDown reports whether frpc.service does not run, also while systemd waits to restart it.
func frpcDown(ctx context.Context) (bool, error) {
	active, err := frpcActive(ctx)
	if err != nil {
		return false, err
	}
	return !active, nil
}

// frpcOwnsAdminPort reports whether a socket owned by root listens on 127.0.0.1:port: frpc.service
// runs frpc as root, and the reload goes only to it.
func frpcOwnsAdminPort(port int) bool {
	table, err := os.ReadFile("/proc/net/tcp")
	if err != nil {
		return false
	}
	return listensOnLoopback(table, port, 0)
}

// reloadFrpc has the running frpc take the proxies from frpc.toml again, over its admin API on
// loopback (GET /api/reload). `frpc reload` reads the API's port, user and password from the
// same file; the binary is the one frpc.service runs.
func reloadFrpc(ctx context.Context) error {
	ctx, cancel := context.WithTimeout(ctx, reloadTimeout)
	defer cancel()
	out, err := exec.CommandContext(ctx, "/usr/bin/frpc", "reload", "-c", config.FrpConfigFile()).CombinedOutput()
	if err != nil {
		return fmt.Errorf("frpc reload: %w: %s", err, bytes.TrimSpace(out))
	}
	return nil
}
