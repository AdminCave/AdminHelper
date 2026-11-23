// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"os"
	"path/filepath"
	"reflect"
	"testing"
	"time"

	"github.com/shirou/gopsutil/v4/disk"
)

// The report's wire contract (R-0688): each block as the monitoring service receives it, held in
// testdata/report/<name>.json. The blocks are built from fixed inputs through the collectors' seams,
// so a change of a key, a type, null against [] or a field left out shows here. Typing the blocks
// must leave these files as they are; -update rewrites them and is for a deliberate wire change only.
var updateGolden = flag.Bool("update", false, "rewrite testdata/report/*.json from the current blocks")

// wireValue is v encoded and decoded again: what the monitoring service reads, not the Go types.
func wireValue(t *testing.T, v any) any {
	t.Helper()
	raw, err := json.Marshal(v)
	if err != nil {
		t.Fatalf("marshal %v: %v", v, err)
	}
	var out any
	if err := json.Unmarshal(raw, &out); err != nil {
		t.Fatalf("unmarshal %s: %v", raw, err)
	}
	return out
}

// wireShape is the wire value with each leaf replaced by its JSON type and each array by the shape of
// its first element, for blocks whose values come from the host.
func wireShape(v any) any {
	switch x := v.(type) {
	case nil:
		return "null"
	case bool:
		return "bool"
	case float64:
		return "number"
	case string:
		return "string"
	case []any:
		if len(x) == 0 {
			return []any{}
		}
		return []any{wireShape(x[0])}
	case map[string]any:
		out := make(map[string]any, len(x))
		for k, e := range x {
			out[k] = wireShape(e)
		}
		return out
	}
	return "unknown"
}

// checkGolden compares got (a wire value) with testdata/report/<name>.json.
func checkGolden(t *testing.T, name string, got any) {
	t.Helper()
	path := filepath.Join("testdata", "report", name+".json")
	pretty, err := json.MarshalIndent(got, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	if *updateGolden {
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, append(pretty, '\n'), 0o644); err != nil {
			t.Fatal(err)
		}
		return
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("%s: %v (a new block: go test ./internal/monitor/ -run TestReportGolden -update)", path, err)
	}
	var want any
	if err := json.Unmarshal(raw, &want); err != nil {
		t.Fatalf("%s: %v", path, err)
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("%s: the wire changed\n got: %s\nwant: %s", path, pretty, raw)
	}
}

func TestReportGoldenDocker(t *testing.T) {
	stubDocker(t, map[string]dockerReply{
		"info": {}, "ps": {out: dockerPSFixture}, "inspect": {out: dockerInspectFixture},
	})
	checkGolden(t, "docker", wireValue(t, collectDocker(context.Background())))
	stubDocker(t, map[string]dockerReply{
		"info": {}, "ps": {out: dockerComposePSFixture}, "inspect": {out: dockerComposeInspectFixture},
	})
	checkGolden(t, "docker_compose", wireValue(t, collectDocker(context.Background())))
	checkGolden(t, "docker_unavailable",
		wireValue(t, dockerUnavailable("info", "daemon_unreachable", errors.New("exit status 1"))))
}

func TestReportGoldenProxmox(t *testing.T) {
	// A fixed node name: the pvesh helpers of the other tests take this host's, which would put it in
	// the golden file and fail on every other machine.
	const node = "pve-golden"
	nodePath := "/nodes/" + node
	local := "[" + pveshBackup("local", 100, 1760000000) + "," +
		`{"volid":"local:backup/vzdump-qemu-102-x.vma.zst","vmid":102,"ctime":1760000000}]`
	pbs := `[{"volid":"pbs:backup/vm/100/2025-10-10T09:46:40Z","vmid":100,"ctime":1760086400,"size":2147483648,` +
		`"verification":{"state":"ok"}},` +
		`{"volid":"pbs:backup/ct/101/2025-10-09T08:53:20Z","vmid":101,"ctime":1760000000,"size":1,"verification":{"state":"failed"}}]`
	stubPvesh(t, map[string]dockerReply{
		nodePath + "/status": {out: pveshNodeStatusFixture},
		pveshStorages: {out: "[" + pveshStorageOn(t, node, "local", "backup,iso", "available") + "," +
			pveshStorageOn(t, node, "pbs", "backup,iso", "available") + "]"},
		nodePath + "/storage/local/content": {out: local},
		nodePath + "/storage/pbs/content":   {out: pbs},
		pveshVMs:                            {out: pveshGuestsFixture},
		pveshJobs:                           {out: pveshJobsFixture},
		nodePath + "/tasks":                 {out: pveshFailedTask(backupTaskUPID, backupTaskStart)},
		nodePath + "/tasks/" + backupTaskUPID + "/log": {out: pveshLog(t,
			"INFO: starting new backup job: vzdump 100 102 --storage local --mode snapshot",
			"ERROR: Backup of VM 102 failed - no space left on device",
			"ERROR: Backup job failed with errors",
		)},
	})
	pveshCLI.hostname = func() (string, error) { return node + ".example.org", nil }
	if err := os.WriteFile(pveshCLI.corosyncConf, []byte(corosyncConfFixture), 0o600); err != nil {
		t.Fatal(err)
	}
	block, _ := collectProxmox(context.Background(), nil, backupDetailsNow)
	checkGolden(t, "proxmox", wireValue(t, block))
	checkGolden(t, "proxmox_unavailable", wireValue(t, proxmoxUnavailable("node_status_failed", "exit status 1")))
}

func TestReportGoldenZFS(t *testing.T) {
	fixture, err := os.ReadFile("testdata/zpool-status-scrub.json")
	if err != nil {
		t.Fatal(err)
	}
	stubZpool(t, map[string]dockerReply{
		"list":      {out: "probe\t240M\t64.3M\t176M\t26%\tONLINE\t15%\n"},
		"status -j": {out: string(fixture)},
	})
	checkGolden(t, "zfs", wireValue(t, collectZFS(context.Background())))
	checkGolden(t, "zfs_unavailable", wireValue(t, zfsUnavailable(errors.New("exit status 1"))))
}

func TestReportGoldenLoadShed(t *testing.T) {
	over := loadReading{LoadPerCPU: ptr(2.5), Iowait: ptr(25), MemAvailable: ptr(7.5)}
	checkGolden(t, "load_shed_over", wireValue(t, loadShed{Active: true, Since: 1_700_000_000, Hits: 3}.block(over)))
	checkGolden(t, "load_shed_clear", wireValue(t, loadShed{}.block(loadReading{})))
}

func TestReportGoldenTopProcesses(t *testing.T) {
	const mib = 1 << 20
	first := map[int32]processReading{
		1:  {name: "systemd", cpu: 10, rss: 12 * mib},
		11: {name: "postgres", cpu: 100, rss: 900 * mib},
		12: {name: "java", cpu: 200, rss: 2000 * mib},
	}
	second := map[int32]processReading{
		1:  {name: "systemd", cpu: 10.02, rss: 12 * mib},
		11: {name: "postgres", cpu: 100.6, rss: 950 * mib},
		12: {name: "java", cpu: 201, rss: 2100 * mib},
	}
	stubProcesses(t, 2*time.Second, first, second)
	checkGolden(t, "top_processes", wireValue(t, collectTopProcesses(context.Background())))
}

// FreeBSD's and Windows' service blocks are built without a build tag, so their contract is checked
// on every platform.
func TestReportGoldenRCServices(t *testing.T) {
	run, _ := fakeService(t, rcHostAnswers(t))
	files := rcFiles(map[string]string{
		"/etc/rc.d/newsyslog":       rcNewsyslogScript,
		"/usr/local/etc/rc.d/nginx": rcNginxScript,
	})
	checkGolden(t, "systemd_freebsd", wireValue(t, rcServiceHealth(context.Background(), run, files)))

	run, _ = fakeService(t, map[string]rcCall{
		"cron status":   {rcCronRunning, nil},
		"sshd status":   {rcSshdTwoPids, nil},
		"nginx status":  {rcNginxStopped, smartctlExit(t, 1)},
		"nosuch status": {rcNoSuchScript, smartctlExit(t, 1)},
	})
	checkGolden(t, "services_freebsd",
		wireValue(t, rcWatchedServices(context.Background(), run, []string{"cron", "sshd", "nginx", "nosuch"})))
}

func TestReportGoldenFreeBSDSystemState(t *testing.T) {
	stubVirtualization(t, "bhyve", "guest")
	stubFreeBSDCalls(t, true, map[string]dockerReply{
		fbsdVersionHost: {out: "15.0-RELEASE-p3\n15.0-RELEASE-p1\n15.0-RELEASE-p3\n"},
		fbsdAudit:       {out: "curl-8.11.0\nopenssl-3.0.15_1,1\n", err: smartctlExit(t, 1)},
		fbsdAudit + " FreeBSD-15.0_3 FreeBSD-kernel-15.0_3": {out: "FreeBSD-15.0_3\n", err: smartctlExit(t, 1)},
	})
	block, _ := freebsdSystemState(context.Background(), reportState{})
	checkGolden(t, "system_state_freebsd", wireValue(t, block))
}

func TestReportGoldenSCServices(t *testing.T) {
	events := scmEventXML("7031", "2026-11-12T10:00:00.1234567Z", "Print Spooler") +
		scmEventXML("7034", "2026-11-12T08:30:15.9876543Z", "myagent")
	got := scServiceHealth([]byte(scExitFixture), nil, func() ([]byte, error) { return []byte(events), nil },
		func([]string) map[string]string {
			return map[string]string{
				"Dnscache": "enabled", "Spooler": "enabled", "AppMgmt": "enabled", "MyAgent": "manual",
				"W32Time": "enabled", "BadSvc": "disabled",
			}
		})
	checkGolden(t, "systemd_windows", wireValue(t, got))
	checkGolden(t, "systemd_windows_sc_failed",
		wireValue(t, scServiceHealth(nil, errors.New("exit status 5"), nil, nil)))
}

func TestReportGoldenSmart(t *testing.T) {
	stubReportHost(t)
	pluginCollectors.smart = collectSmart
	stubSmartctl(t, dockerReply{out: smartScanFixture}, map[string]dockerReply{
		"/dev/sda":   {out: ataFixture},
		"/dev/nvme0": {out: nvmeFixture},
	})
	checkGolden(t, "smart", smartWire(t, BuildReport(nil)))

	stubSmartctl(t, dockerReply{out: `{"devices":[]}`}, nil)
	checkGolden(t, "smart_absent", smartWire(t, BuildReport(nil)))
}

func TestReportGoldenResources(t *testing.T) {
	stubResources(t, "linux")
	checkGolden(t, "resources_swap_cpu", wireValue(t, collectSwapAndCPUCount()))
	checkGolden(t, "resources_network", wireValue(t, collectNetwork()))

	const gib = 1 << 30
	usage := &disk.UsageStat{Total: 100 * gib, Used: 42 * gib, Free: 58 * gib, UsedPercent: 42, InodesTotal: 1000,
		InodesUsedPercent: 12.34}
	checkGolden(t, "resources_disks", wireValue(t, []DiskInfo{
		diskInfo(disk.PartitionStat{Mountpoint: "/", Fstype: "ext4"}, usage, "linux"),
		diskInfo(disk.PartitionStat{Mountpoint: "C:", Fstype: "NTFS"}, usage, "windows"),
	}))
}
