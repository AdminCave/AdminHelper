// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package frpc

import (
	"bytes"
	"context"
	"fmt"
	"os"
	"os/exec"
	"time"

	"adminhelper-agent/internal/config"
)

// reloadTimeout bounds `frpc reload`: frpc answers on loopback at once, a hang counts as a failed
// reload, which a restart then replaces.
const reloadTimeout = 15 * time.Second

// enableFrpcService enables frpc and the AdminHelper agent timer via systemd.
func enableFrpcService() error {
	if err := exec.Command("systemctl", "daemon-reload").Run(); err != nil {
		return fmt.Errorf("daemon-reload: %w", err)
	}
	// Enable each unit separately: a combined `enable --now frpc.service
	// adminhelper-agent.timer` fails atomically if the timer unit is not
	// installed yet, dragging frpc down with it.
	if err := exec.Command("systemctl", "enable", "--now", "frpc.service").Run(); err != nil {
		return fmt.Errorf("enable frpc.service: %w", err)
	}
	if err := exec.Command("systemctl", "enable", "--now", "adminhelper-agent.timer").Run(); err != nil {
		return fmt.Errorf("enable adminhelper-agent.timer: %w", err)
	}
	return nil
}

// restartFrpc restarts the frpc service.
func restartFrpc() error {
	return exec.Command("systemctl", "restart", "frpc.service").Run()
}

// disableFrpc stops the frpc service and keeps it from starting at boot.
func disableFrpc() error {
	return exec.Command("systemctl", "disable", "--now", "frpc.service").Run()
}

// frpcActive reports whether frpc.service runs; `is-active` exits non-zero for every other state.
func frpcActive() bool {
	return exec.Command("systemctl", "is-active", "--quiet", "frpc.service").Run() == nil
}

// frpcDown reports whether frpc.service does not run, also while systemd waits to restart it.
func frpcDown() bool {
	return !frpcActive()
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
func reloadFrpc() error {
	ctx, cancel := context.WithTimeout(context.Background(), reloadTimeout)
	defer cancel()
	out, err := exec.CommandContext(ctx, "/usr/bin/frpc", "reload", "-c", config.FrpConfigFile()).CombinedOutput()
	if err != nil {
		return fmt.Errorf("frpc reload: %w: %s", err, bytes.TrimSpace(out))
	}
	return nil
}
