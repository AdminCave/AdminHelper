// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package frpc

// FRP-on-Windows is not provisioned as a standalone service: only the
// AdminHelper-Agent service is registered (internal/service/service_windows.go),
// there is no `sc create frpc`. Firing `sc start frpc` / `sc stop frpc` at a
// non-existent service made every config change abort the whole FRP sync
// (sync.go treats a restart error as a hard return). Until frpc is integrated
// with the Windows Service Manager, these hooks skip cleanly (warn + nil) so the
// rest of the sync (config + hash already written to disk) is not lost.

// enableFrpcService is a no-op on Windows: no frpc service is registered.
func enableFrpcService() error {
	logger.Warnf("frpc-Dienst wird unter Windows nicht verwaltet — Aktivierung uebersprungen")
	return nil
}

// restartFrpc is a no-op on Windows: no frpc service is registered.
func restartFrpc() error {
	logger.Warnf("frpc-Dienst wird unter Windows nicht verwaltet — Neustart uebersprungen")
	return nil
}

// disableFrpc is a no-op on Windows: no frpc service is registered.
func disableFrpc() error {
	logger.Warnf("frpc service is not managed on Windows, skipping the stop")
	return nil
}

// frpcActive is always false on Windows: no frpc service is registered that could run.
func frpcActive() bool {
	return false
}
