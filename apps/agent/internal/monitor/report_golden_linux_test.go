// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"context"
	"maps"
	"slices"
	"testing"
	"time"

	"adminhelper-agent/internal/credentials"
	"adminhelper-agent/internal/discovery"
	"adminhelper-agent/internal/probe"
)

// The blocks only Linux builds: host facts carry runtime.GOOS, the systemd and system state blocks
// read systemctl, apt and /proc, and the report's own key set is the Linux one.

func TestReportGoldenHostFacts(t *testing.T) {
	stubHostFacts(t, "docker", "zpool", "pvesh")
	checkGolden(t, "host_linux", wireValue(t, collectHostFacts()))
}

func TestReportGoldenSystemdLinux(t *testing.T) {
	fixEpoch(t, factEpoch)
	stubCollector(t, map[string]systemctlReply{
		listUnitsArgs:     {out: collectorListUnits},
		listUnitFilesArgs: {out: collectorListUnitFiles},
		listFailedArgs:    {out: "smartmontools.service loaded failed failed Self Monitoring and Reporting Technology (SMART) Daemon\n"},
		recheckShow:       {out: showBlocks257},
		aliasShow:         {out: aliasBlocks},
		factShow:          {out: factBlocks257},
	})
	checkGolden(t, "systemd_linux", wireValue(t, collectServiceHealth(context.Background())))

	out := []byte("Id=nginx.service\nActiveState=active\nMainPID=1234\n\n" +
		"Id=sshd.service\nActiveState=inactive\nMainPID=0\n\n" +
		"Id=redis.service\nActiveState=active\nMainPID=5678")
	checkGolden(t, "services_linux",
		wireValue(t, parseWatchedServices(out, []string{"redis", "missing", "nginx", "sshd.service"})))
}

func TestReportGoldenSystemStateLinux(t *testing.T) {
	stubSystemCLI(t, map[string]dockerReply{
		"apt-get": {}, "timedatectl": {out: timedatectlShow}, "journalctl": {out: oomJournal},
	})
	stubRebootFlag(t, true)
	stubRebootPkgs(t, "linux-image-6.12.57+deb13-amd64\n")
	stubVMStat(t, vmstatWithOOMKill(5))
	stubUpdates(t, updatesNow, dockerReply{out: aptUbuntuFixture})
	saved := uint64(3)
	block, _ := collectSystemState(context.Background(), reportState{OOMKill: &saved})
	checkGolden(t, "system_state_linux", wireValue(t, block))
}

func TestReportGoldenServiceLogs(t *testing.T) {
	stubReportHost(t)
	failed := []string{"a.service", "b.service"}
	since := map[string]string{"a.service": "2026-11-19T04:00:00Z"}
	details := true
	stubFailedUnits(t, &failed, since, &details)
	stubServiceLogReader(t, map[string]bool{"b.service": true})
	report, _ := buildReportWithState(context.Background(), nil, &probeWork{serviceLogs: true}, reportState{}, time.Now())
	checkGolden(t, "systemd_failed_logs", wireValue(t, report["systemd"]))
}

// TestReportGoldenShape holds the report's keys and their JSON types with the collectors stubbed;
// memory, load and uptime are this host's, so only the shape is the contract. Disks, temperatures
// and top_processes come and go with the host and are left out; the watched services have their
// own golden file, since systemctl would answer for this host.
func TestReportGoldenShape(t *testing.T) {
	stubReportHost(t)
	stubResources(t, "linux")
	report, _ := wireValue(t, BuildReport(nil)).(map[string]any)
	if resources, ok := report["resources"].(map[string]any); ok {
		for _, k := range []string{"disks", "temperatures", "top_processes"} {
			delete(resources, k)
		}
	}
	checkGolden(t, "report_shape_linux", wireShape(report))
}

// TestReportGoldenKeys holds the report's top-level keys and those of its systemd block when every
// collector has something to say, the watched services are asked for and the plan sends credentials
// and asks for a discovery. The blocks' contents have golden files of their own.
func TestReportGoldenKeys(t *testing.T) {
	stubReportHost(t)
	stubResources(t, "linux")
	pluginCollectors.docker = func(context.Context) *DockerBlock { return &DockerBlock{Available: true} }
	pluginCollectors.proxmox = func(context.Context, *backupIndexCheck, time.Time) (map[string]any, *backupIndexCheck) {
		return map[string]any{"available": true}, nil
	}
	pluginCollectors.zfs = func(context.Context) map[string]any { return map[string]any{"available": true} }
	systemStateCollector = func(_ context.Context, st reportState) (*SystemState, reportState) {
		required := false
		return &SystemState{RebootRequired: &required}, st
	}
	runDiscovery = func(context.Context, []probe.Marker) discovery.Inventory { return discovery.Inventory{} }
	// A name systemctl is never asked for: the watched list is there without this host's answer.
	work := &probeWork{creds: map[string]credentials.Credential{}, scan: true}
	report, _ := buildReportWithState(context.Background(), []string{"not a unit"}, work, reportState{}, time.Now())
	wire, _ := wireValue(t, report).(map[string]any)
	systemd, _ := wire["systemd"].(map[string]any)
	checkGolden(t, "report_keys_linux", map[string]any{"report": sortedKeys(wire), "systemd": sortedKeys(systemd)})
}

// sortedKeys are m's keys in order, as a wire value.
func sortedKeys(m map[string]any) []any {
	keys := slices.Sorted(maps.Keys(m))
	out := make([]any, len(keys))
	for i, k := range keys {
		out[i] = k
	}
	return out
}
