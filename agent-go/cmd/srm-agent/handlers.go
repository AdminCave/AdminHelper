package main

import (
	"srm-agent/internal/frpc"
	"srm-agent/internal/monitor"
	"srm-agent/internal/service"
)

func frpcInitRun(url, token, serverID, cacert string, insecure bool) error {
	return frpc.Init(url, token, serverID, cacert, insecure)
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
