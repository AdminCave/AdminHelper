// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"context"
	"encoding/json"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"time"
)

// dockerTimeout caps every docker CLI call: a hanging daemon must not stall
// the whole 5-minute report cycle.
const dockerTimeout = 10 * time.Second

// pluginTimeout caps every non-docker plugin exec (pvesh, zpool). These
// tools really do hang: `zpool list` blocks indefinitely on a suspended pool and
// `pvesh` on quorum loss — exactly when monitoring matters most. Without a cap the
// whole report cycle stalls and systemd kills the oneshot at TimeoutStartSec=60
// (no push, no FRPC sync for that run).
const pluginTimeout = 15 * time.Second

// runWithTimeout runs a plugin command under pluginTimeout, mirroring the docker
// path, so a hung external tool can never block the report cycle.
func runWithTimeout(name string, args ...string) ([]byte, error) {
	ctx, cancel := context.WithTimeout(context.Background(), pluginTimeout)
	defer cancel()
	return exec.CommandContext(ctx, name, args...).Output()
}

// collectDocker collects Docker container status (cross-platform).
func collectDocker() map[string]any {
	if _, err := exec.LookPath("docker"); err != nil {
		return nil
	}
	// Is the daemon reachable?
	ctxInfo, cancelInfo := context.WithTimeout(context.Background(), dockerTimeout)
	defer cancelInfo()
	if err := exec.CommandContext(ctxInfo, "docker", "info").Run(); err != nil {
		return nil
	}

	ctxPs, cancelPs := context.WithTimeout(context.Background(), dockerTimeout)
	defer cancelPs()
	out, err := exec.CommandContext(ctxPs, "docker", "ps", "-a", "--format", "{{json .}}").Output()
	if err != nil {
		return nil
	}

	var containers []map[string]string
	var ids []string
	for _, line := range strings.Split(strings.TrimSpace(string(out)), "\n") {
		if line == "" {
			continue
		}
		var c map[string]string
		if err := json.Unmarshal([]byte(line), &c); err != nil {
			continue
		}
		containers = append(containers, map[string]string{
			"id":     c["ID"],
			"name":   c["Names"],
			"image":  c["Image"],
			"state":  c["State"],
			"status": c["Status"],
		})
		ids = append(ids, c["ID"])
	}
	if len(containers) == 0 {
		return nil
	}

	// Restart policies via ONE batch inspect instead of one call per container.
	policies := inspectRestartPolicies(ids)
	for _, container := range containers {
		if policy, ok := policies[container["id"]]; ok {
			container["restart_policy"] = policy
		}
	}
	return map[string]any{"containers": containers}
}

// inspectRestartPolicies fetches the restart policy of all given containers in
// a single `docker inspect` call. Returns a map keyed by the short (12-char)
// container ID as printed by `docker ps`.
func inspectRestartPolicies(ids []string) map[string]string {
	ctx, cancel := context.WithTimeout(context.Background(), dockerTimeout)
	defer cancel()
	args := append([]string{"inspect", "--format",
		"{{.Id}} {{.HostConfig.RestartPolicy.Name}}"}, ids...)
	// Output() returns the partial stdout alongside the error (e.g. when a
	// container vanished between ps and inspect) — parse what we got, the
	// missing IDs simply keep no restart_policy.
	out, _ := exec.CommandContext(ctx, "docker", args...).Output()

	policies := make(map[string]string, len(ids))
	for _, line := range strings.Split(strings.TrimSpace(string(out)), "\n") {
		fullID, policy, _ := strings.Cut(line, " ")
		if len(fullID) < 12 {
			continue
		}
		policies[fullID[:12]] = policy
	}
	return policies
}

// collectProxmox collects Proxmox metrics (Linux with pvesh only).
func collectProxmox() map[string]any {
	if _, err := exec.LookPath("pvesh"); err != nil {
		return nil
	}

	result := map[string]any{"node": nil, "vms": []any{}}

	// Node status
	host, err := os.Hostname()
	if err != nil {
		return nil
	}
	nodeName, _, _ := strings.Cut(host, ".") // FQDN -> short name (pvesh nodes are short)
	nodeOut, err := runWithTimeout("pvesh", "get", "/nodes/"+nodeName+"/status",
		"--output-format", "json")
	if err == nil {
		var nd map[string]any
		if json.Unmarshal(nodeOut, &nd) == nil {
			memData, _ := nd["memory"].(map[string]any)
			total := getFloat(memData, "total", 1)
			if total == 0 {
				total = 1
			}
			result["node"] = map[string]any{
				"name":           nodeName,
				"cpu":            round1(getFloat(nd, "cpu", 0) * 100),
				"memory_percent": round1(getFloat(memData, "used", 0) / total * 100),
			}
		}
	}

	// Build the backup index once for all VMs (O(Storages) instead of O(VMs × Storages))
	backupIndex := buildBackupIndex(nodeName)

	// VMs + LXC containers
	var vmList []map[string]any
	vmsOut, err := runWithTimeout("pvesh", "get", "/cluster/resources", "--type", "vm",
		"--output-format", "json")
	if err == nil {
		var vms []map[string]any
		if json.Unmarshal(vmsOut, &vms) == nil {
			for _, vm := range vms {
				vmid := int(getFloat(vm, "vmid", 0))
				if vmid == 0 {
					continue
				}
				var lastBackup any
				if ts, ok := backupIndex[vmid]; ok {
					lastBackup = ts
				}
				vmList = append(vmList, map[string]any{
					"vmid":           vmid,
					"name":           vm["name"],
					"status":         vm["status"],
					"type":           vm["type"],
					"last_backup_ts": lastBackup,
				})
			}
		}
	}
	result["vms"] = vmList

	if result["node"] == nil && len(vmList) == 0 {
		return nil
	}
	return result
}

// buildBackupIndex fetches all backups of all storages and builds a lookup map
// vmid -> newest ctime timestamp. Only O(Storages) API calls instead of O(VMs × Storages).
// nodeName is the resolved local node (not the literal "localhost", on which
// pvesh's implicit mapping is undocumented and could silently break).
func buildBackupIndex(nodeName string) map[int]int64 {
	index := make(map[int]int64)

	storagesOut, err := runWithTimeout("pvesh", "get", "/storage",
		"--output-format", "json")
	if err != nil {
		return index
	}
	var storages []map[string]any
	if json.Unmarshal(storagesOut, &storages) != nil {
		return index
	}

	for _, storage := range storages {
		content, _ := storage["content"].(string)
		if !strings.Contains(content, "backup") {
			continue
		}
		sid, _ := storage["storage"].(string)

		// Fetch all backups of this storage at once (without the --vmid filter)
		backupsOut, err := runWithTimeout("pvesh", "get",
			"/nodes/"+nodeName+"/storage/"+sid+"/content",
			"--content", "backup", "--output-format", "json")
		if err != nil {
			continue
		}
		var items []map[string]any
		if json.Unmarshal(backupsOut, &items) != nil {
			continue
		}
		for _, item := range items {
			vmid := int(getFloat(item, "vmid", 0))
			if vmid == 0 {
				continue
			}
			ct := int64(getFloat(item, "ctime", 0))
			if ct > index[vmid] {
				index[vmid] = ct
			}
		}
	}
	return index
}

// collectZFS collects ZFS pool information (Linux only).
func collectZFS() map[string]any {
	if _, err := exec.LookPath("zpool"); err != nil {
		return nil
	}

	out, err := runWithTimeout("zpool", "list", "-H", "-o",
		"name,size,alloc,free,cap,health")
	if err != nil {
		return nil
	}

	var pools []map[string]any
	for _, line := range strings.Split(strings.TrimSpace(string(out)), "\n") {
		parts := strings.Split(line, "\t")
		if len(parts) < 6 {
			continue
		}
		capStr := strings.TrimRight(parts[4], "%")
		capPct, _ := strconv.Atoi(capStr)
		pools = append(pools, map[string]any{
			"name":             parts[0],
			"size":             parts[1],
			"allocated":        parts[2],
			"free":             parts[3],
			"capacity_percent": capPct,
			"health":           parts[5],
		})
	}
	if len(pools) == 0 {
		return nil
	}

	result := map[string]any{"pools": pools}

	// Error details for non-ONLINE pools
	for _, p := range pools {
		if p["health"] != "ONLINE" {
			statusOut, err := runWithTimeout("zpool", "status", "-x")
			if err == nil {
				result["errors"] = strings.TrimSpace(string(statusOut))
			}
			break
		}
	}
	return result
}

// getFloat extracts a float64 value from a map.
func getFloat(m map[string]any, key string, fallback float64) float64 {
	if m == nil {
		return fallback
	}
	v, ok := m[key]
	if !ok {
		return fallback
	}
	switch n := v.(type) {
	case float64:
		return n
	case int:
		return float64(n)
	case json.Number:
		f, _ := n.Float64()
		return f
	}
	return fallback
}
