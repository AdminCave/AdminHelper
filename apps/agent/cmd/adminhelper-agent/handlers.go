// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package main

import (
	"adminhelper-agent/internal/frpc"
	"adminhelper-agent/internal/monitor"
	"adminhelper-agent/internal/provision"
	"adminhelper-agent/internal/service"
)

func provisionRun(url, token, serverID, cacert string, insecure bool) error {
	return provision.Run(url, token, serverID, cacert, insecure)
}

func frpcSyncRun() error {
	return frpc.Sync()
}

func monitorInitRun(url, apiKey, serverID, services, cacert string, insecure bool) error {
	return monitor.Init(url, apiKey, serverID, services, cacert, insecure)
}

func monitorPushRun() error {
	return monitor.Push()
}

func serviceInstallRun() error {
	return service.Install()
}

func serviceUninstallRun() error {
	return service.Uninstall()
}
