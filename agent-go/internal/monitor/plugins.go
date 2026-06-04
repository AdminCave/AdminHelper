// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"encoding/json"
	"os/exec"
	"strconv"
	"strings"
)

// collectDocker collects Docker container status (cross-platform).
func collectDocker() map[string]any {
	if _, err := exec.LookPath("docker"); err != nil {
		return nil
	}
	// Is the daemon reachable?
	if err := exec.Command("docker", "info").Run(); err != nil {
		return nil
	}

	out, err := exec.Command("docker", "ps", "-a", "--format", "{{json .}}").Output()
	if err != nil {
		return nil
	}

	var containers []map[string]string
	for _, line := range strings.Split(strings.TrimSpace(string(out)), "\n") {
		if line == "" {
			continue
		}
		var c map[string]string
		if err := json.Unmarshal([]byte(line), &c); err != nil {
			continue
		}
		container := map[string]string{
			"id":     c["ID"],
			"name":   c["Names"],
			"image":  c["Image"],
			"state":  c["State"],
			"status": c["Status"],
		}
		// Restart policy via docker inspect
		inspOut, err := exec.Command("docker", "inspect", "--format",
			"{{.HostConfig.RestartPolicy.Name}}", c["ID"]).Output()
		if err == nil {
			container["restart_policy"] = strings.TrimSpace(string(inspOut))
		}
		containers = append(containers, container)
	}
	if len(containers) == 0 {
		return nil
	}
	return map[string]any{"containers": containers}
}

// collectProxmox collects Proxmox metrics (Linux with pvesh only).
func collectProxmox() map[string]any {
	if _, err := exec.LookPath("pvesh"); err != nil {
		return nil
	}

	result := map[string]any{"node": nil, "vms": []any{}}

	// Node status
	hostname, err := exec.Command("hostname", "-s").Output()
	if err != nil {
		return nil
	}
	nodeName := strings.TrimSpace(string(hostname))
	nodeOut, err := exec.Command("pvesh", "get", "/nodes/"+nodeName+"/status",
		"--output-format", "json").Output()
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
	backupIndex := buildBackupIndex()

	// VMs + LXC containers
	var vmList []map[string]any
	vmsOut, err := exec.Command("pvesh", "get", "/cluster/resources", "--type", "vm",
		"--output-format", "json").Output()
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
func buildBackupIndex() map[int]int64 {
	index := make(map[int]int64)

	storagesOut, err := exec.Command("pvesh", "get", "/storage",
		"--output-format", "json").Output()
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
		backupsOut, err := exec.Command("pvesh", "get",
			"/nodes/localhost/storage/"+sid+"/content",
			"--content", "backup", "--output-format", "json").Output()
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

	out, err := exec.Command("zpool", "list", "-H", "-o",
		"name,size,alloc,free,cap,health").Output()
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
			statusOut, err := exec.Command("zpool", "status", "-x").Output()
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
