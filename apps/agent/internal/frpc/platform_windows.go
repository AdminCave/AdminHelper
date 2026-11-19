// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package frpc

import (
	"bytes"
	"context"
	"fmt"

	"adminhelper-agent/internal/config"
)

// The hooks go to the supervisor of the agent service (supervisor_windows.go). Outside the
// service process they fail with errNotSupervised: frpc then does not run, and the sync must not
// report that it does (R-0708).

// enableFrpcService starts frpc unless it runs already.
func enableFrpcService(context.Context) error {
	s := current.Load()
	if s == nil {
		return errNotSupervised
	}
	return s.enable()
}

// restartFrpc stops frpc and starts it again on frpc.toml.
func restartFrpc(context.Context) error {
	s := current.Load()
	if s == nil {
		return errNotSupervised
	}
	return s.restart()
}

// disableFrpc stops frpc until the next enable.
func disableFrpc(context.Context) error {
	s := current.Load()
	if s == nil {
		return errNotSupervised
	}
	return s.disable()
}

// frpcActive reports whether the supervisor runs frpc.
func frpcActive(context.Context) (bool, error) {
	s := current.Load()
	if s == nil {
		return false, errNotSupervised
	}
	return s.pid() != 0, nil
}

// frpcDown reports whether frpc does not run, also while the supervisor waits to restart it.
func frpcDown(ctx context.Context) (bool, error) {
	active, err := frpcActive(ctx)
	if err != nil {
		return false, err
	}
	return !active, nil
}

// frpcOwnsAdminPort reports whether the frpc the supervisor runs listens on 127.0.0.1:port, and
// no other process there: the reload carries the admin password.
func frpcOwnsAdminPort(port int) bool {
	s := current.Load()
	if s == nil {
		return false
	}
	pid := s.pid()
	if pid == 0 {
		return false
	}
	table, err := tcpListeners()
	if err != nil {
		logger.Warnf("read the TCP listeners: %v", err)
		return false
	}
	return listenerOwnedBy(table, port, pid)
}

// reloadFrpc has the running frpc take the proxies from frpc.toml again, over its admin API on
// loopback: `frpc reload` reads port, user and password from the same file.
func reloadFrpc(ctx context.Context) error {
	s := current.Load()
	if s == nil {
		return errNotSupervised
	}
	if err := verifyFrpcExe(s.exe); err != nil {
		return err
	}
	ctx, cancel := context.WithTimeout(ctx, reloadTimeout)
	defer cancel()
	out, err := frpcCommand(ctx, s.exe, "reload", "-c", config.FrpConfigFile()).CombinedOutput()
	if err != nil {
		return fmt.Errorf("frpc reload: %w: %s", err, bytes.TrimSpace(out))
	}
	return nil
}
