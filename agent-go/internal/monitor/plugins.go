package monitor

import (
	"encoding/json"
	"os/exec"
	"strconv"
	"strings"
)

// collectDocker sammelt Docker Container-Status (plattform-uebergreifend).
func collectDocker() map[string]any {
	if _, err := exec.LookPath("docker"); err != nil {
		return nil
	}
	// Daemon erreichbar?
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
		// Restart-Policy via docker inspect
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

// collectProxmox sammelt Proxmox-Metriken (nur auf Linux mit pvesh).
func collectProxmox() map[string]any {
	if _, err := exec.LookPath("pvesh"); err != nil {
		return nil
	}

	result := map[string]any{"node": nil, "vms": []any{}}

	// Node-Status
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

	// VMs + LXC Container
	vmsOut, err := exec.Command("pvesh", "get", "/cluster/resources", "--type", "vm",
		"--output-format", "json").Output()
	if err == nil {
		var vms []map[string]any
		if json.Unmarshal(vmsOut, &vms) == nil {
			var vmList []map[string]any
			for _, vm := range vms {
				vmid := int(getFloat(vm, "vmid", 0))
				if vmid == 0 {
					continue
				}
				vmInfo := map[string]any{
					"vmid":           vmid,
					"name":           vm["name"],
					"status":         vm["status"],
					"type":           vm["type"],
					"last_backup_ts": findLastBackup(vmid),
				}
				vmList = append(vmList, vmInfo)
			}
			result["vms"] = vmList
		}
	}

	if result["node"] == nil && len(result["vms"].([]any)) == 0 {
		return nil
	}
	return result
}

// TODO(human): Soll hier ein Cache fuer die Storage-Liste eingebaut werden,
// oder reicht die aktuelle Implementierung fuer den MVP?
// Bedenke: Bei vielen VMs (50+) und mehreren Storages entstehen viele API-Calls.
func findLastBackup(vmid int) any {
	storagesOut, err := exec.Command("pvesh", "get", "/storage",
		"--output-format", "json").Output()
	if err != nil {
		return nil
	}
	var storages []map[string]any
	if json.Unmarshal(storagesOut, &storages) != nil {
		return nil
	}

	var newestCtime int64
	for _, storage := range storages {
		content, _ := storage["content"].(string)
		if !strings.Contains(content, "backup") {
			continue
		}
		sid, _ := storage["storage"].(string)
		backupsOut, err := exec.Command("pvesh", "get",
			"/nodes/localhost/storage/"+sid+"/content",
			"--content", "backup", "--vmid", strconv.Itoa(vmid),
			"--output-format", "json").Output()
		if err != nil {
			continue
		}
		var items []map[string]any
		if json.Unmarshal(backupsOut, &items) != nil {
			continue
		}
		for _, item := range items {
			ct := int64(getFloat(item, "ctime", 0))
			if ct > newestCtime {
				newestCtime = ct
			}
		}
	}
	if newestCtime == 0 {
		return nil
	}
	return newestCtime
}

// collectZFS sammelt ZFS Pool-Informationen (nur Linux).
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

	// Fehler-Details bei nicht-ONLINE Pools
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

// getFloat extrahiert einen float64-Wert aus einer Map.
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
