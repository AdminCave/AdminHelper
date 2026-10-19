// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
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
// whole report cycle stalls and systemd kills the oneshot at its TimeoutStartSec
// (no push, no FRPC sync for that run). A var only so tests can shorten it.
var pluginTimeout = 15 * time.Second

// runWithTimeout runs a plugin command under pluginTimeout, mirroring the docker
// path, so a hung external tool can never block the report cycle. Through runTimed, a
// call the timeout ended returns context.DeadlineExceeded, which the systemctl and sc
// reasons (commandFailure) name as a timeout instead of the ExitError exec reports
// ("signal: killed" on Linux, "exit status 1" on Windows).
func runWithTimeout(name string, args ...string) ([]byte, error) {
	return runTimed(pluginTimeout, name, args...)
}

// dockerCLI indirects collectDocker's docker lookup and calls so tests can drive every path without
// docker, which is slow and host-dependent (same reason as pluginCollectors, 6.18).
var dockerCLI = struct {
	lookPath func(file string) (string, error)
	run      func(args ...string) ([]byte, error)
}{exec.LookPath, runDocker}

// runDocker runs one docker CLI call under dockerTimeout.
func runDocker(args ...string) ([]byte, error) {
	return runTimed(dockerTimeout, "docker", args...)
}

// runTimed runs a command under timeout. A call the timeout killed returns context.DeadlineExceeded:
// exec itself reports it as the ExitError "signal: killed", which would pass a hanging tool off as a
// failing one.
func runTimed(timeout time.Duration, name string, args ...string) ([]byte, error) {
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	out, err := exec.CommandContext(ctx, name, args...).Output()
	if err != nil && ctx.Err() != nil {
		return out, ctx.Err()
	}
	return out, err
}

// collectDocker collects Docker container status (cross-platform). No docker binary means Docker is
// not installed and stays silent (nil). With the CLI present the block is always sent: a daemon that
// does not answer, a failing or hanging call or unreadable output is available=false with an error
// code, so the monitoring service can raise it instead of seeing no data. Every abort is logged, so
// `diagnose` shows the reason.
func collectDocker() map[string]any {
	if _, err := dockerCLI.lookPath("docker"); err != nil {
		return nil
	}
	if _, err := dockerCLI.run("info"); err != nil {
		return dockerUnavailable("info", "daemon_unreachable", err)
	}

	out, err := dockerCLI.run("ps", "-a", "--format", "{{json .}}")
	if err != nil {
		return dockerUnavailable("ps", "cli_failed", err)
	}
	listed, ids, skipped := parseDockerPS(out)
	if skipped > 0 {
		logger.Warnf("docker ps: %d unreadable line(s) skipped", skipped)
		if len(listed) == 0 {
			return dockerUnavailable("ps", "parse_failed", nil)
		}
	}
	containers := make([]map[string]any, 0, len(listed))
	if len(listed) == 0 {
		return map[string]any{"available": true, "error": nil, "containers": containers}
	}

	// ONE batch inspect for all containers, as plain JSON: a Go template on .State.Health.Status fails
	// for a container without a healthcheck.
	out, err = dockerCLI.run(append([]string{"inspect", "--type", "container"}, ids...)...)
	if errors.Is(err, context.DeadlineExceeded) {
		return dockerUnavailable("inspect", "timeout", err)
	}
	var inspected []dockerInspect
	if jsonErr := json.Unmarshal(out, &inspected); jsonErr != nil || len(inspected) == 0 {
		if err != nil {
			return dockerUnavailable("inspect", "cli_failed", err)
		}
		return dockerUnavailable("inspect", "parse_failed", nil)
	}
	// A container that vanished between ps and inspect makes the CLI exit 1 but still print the
	// others; it is gone, so it drops out of the report. An empty list (daemon gone) failed above.
	byShortID := make(map[string]dockerInspect, len(inspected))
	for _, c := range inspected {
		if len(c.ID) >= 12 {
			byShortID[c.ID[:12]] = c
		}
	}
	for _, c := range listed {
		in, ok := byShortID[c["id"]]
		if !ok {
			continue
		}
		// state from the same snapshot as exit_code and oom_killed, so they never contradict.
		state := c["state"]
		if in.State.Status != "" {
			state = in.State.Status
		}
		health := ""
		if in.State.Health != nil {
			health = in.State.Health.Status
		}
		containers = append(containers, map[string]any{
			"id":             c["id"],
			"name":           c["name"],
			"image":          c["image"],
			"state":          state,
			"status":         c["status"],
			"restart_policy": in.HostConfig.RestartPolicy.Name,
			"exit_code":      in.State.ExitCode,
			"oom_killed":     in.State.OOMKilled,
			"restart_count":  in.RestartCount,
			"health":         health,
		})
	}
	return map[string]any{"available": true, "error": nil, "containers": containers}
}

// dockerUnavailable is the block for an installed docker that could not be read. code is what the
// monitoring service evaluates (daemon_unreachable | timeout | cli_failed | parse_failed; a call the
// timeout killed is always timeout), error_message names the call and its exit status — never stderr
// or a path.
func dockerUnavailable(call, code string, err error) map[string]any {
	text := "docker " + call + " output unreadable"
	switch {
	case errors.Is(err, context.DeadlineExceeded):
		code = "timeout"
		text = fmt.Sprintf("docker %s timed out after %s", call, dockerTimeout)
	case err != nil:
		text = "docker " + call + " failed: " + commandFailure("docker", dockerTimeout, err)
	}
	logger.Warnf("%s, docker reported as unavailable (%s)", text, code)
	return map[string]any{
		"available":     false,
		"error":         code,
		"error_message": text,
		"containers":    []map[string]any{},
	}
}

// dockerPSLine holds only the `docker ps` fields the report uses. A struct, not map[string]string:
// encoding/json then ignores every other field whatever its type — the CLI prints Platform as an
// object since 28.2, which made the map decode fail for every line.
type dockerPSLine struct {
	ID     string
	Names  string
	Image  string
	State  string
	Status string
}

// parseDockerPS parses `docker ps -a --format {{json .}}` (one JSON object per line) into container
// maps and their IDs, skipping blank lines and counting unparseable ones in skipped — the parsing,
// testable without docker (6.16).
func parseDockerPS(out []byte) (containers []map[string]string, ids []string, skipped int) {
	for _, line := range strings.Split(strings.TrimSpace(string(out)), "\n") {
		if line == "" {
			continue
		}
		var c dockerPSLine
		if err := json.Unmarshal([]byte(line), &c); err != nil {
			skipped++
			continue
		}
		containers = append(containers, map[string]string{
			"id":     c.ID,
			"name":   c.Names,
			"image":  c.Image,
			"state":  c.State,
			"status": c.Status,
		})
		ids = append(ids, c.ID)
	}
	return containers, ids, skipped
}

// dockerInspect holds only the `docker inspect` fields the report uses (Engine API
// ContainerInspectResponse). A struct, so every other field is ignored whatever its type; Health is a
// pointer because inspect omits it for a container without a healthcheck.
type dockerInspect struct {
	ID           string `json:"Id"`
	RestartCount int
	State        struct {
		Status    string
		ExitCode  int
		OOMKilled bool
		Health    *struct{ Status string }
	}
	HostConfig struct {
		RestartPolicy struct{ Name string }
	}
}

// pveshCLI indirects collectProxmox's pvesh lookup and calls so tests can drive every path without
// pvesh (same reason as dockerCLI).
var pveshCLI = struct {
	lookPath func(file string) (string, error)
	run      func(args ...string) ([]byte, error)
}{exec.LookPath, runPvesh}

// runPvesh runs one pvesh call under pluginTimeout (runWithTimeout).
func runPvesh(args ...string) ([]byte, error) {
	return runWithTimeout("pvesh", args...)
}

// collectProxmox collects Proxmox metrics (Linux with pvesh only).
func collectProxmox() map[string]any {
	if _, err := pveshCLI.lookPath("pvesh"); err != nil {
		return nil
	}

	result := map[string]any{"node": nil, "vms": []any{}}

	// Node status
	host, err := os.Hostname()
	if err != nil {
		return nil
	}
	nodeName, _, _ := strings.Cut(host, ".") // FQDN -> short name (pvesh nodes are short)
	nodeOut, err := pveshCLI.run("get", "/nodes/"+nodeName+"/status", "--output-format", "json")
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

	// Build the backup index once for all VMs (O(Storages) instead of O(VMs × Storages)). Without
	// every backup storage read, each VM whose backups sit on a missing one would go out without
	// last_backup_ts, which the server reads as "No backup" (critical): the block stays out instead.
	backupIndex, err := buildBackupIndex(nodeName)
	if err != nil {
		logger.Warnf("%s, proxmox left out of the report", err)
		return nil
	}

	// VMs + LXC containers. Only an array is a VM list (null decodes without error, to a nil slice):
	// without one the block stays out, since the server reads a block without VMs as "no VMs" (ok).
	// Logged, so `diagnose` shows the reason.
	vmsOut, err := pveshCLI.run("get", "/cluster/resources", "--type", "vm", "--output-format", "json")
	if err != nil {
		logger.Warnf("pvesh get /cluster/resources failed: %s, proxmox left out of the report",
			commandFailure("pvesh", pluginTimeout, err))
		return nil
	}
	var vms []map[string]any
	if json.Unmarshal(vmsOut, &vms) != nil || vms == nil {
		logger.Warnf("pvesh get /cluster/resources output unreadable, proxmox left out of the report")
		return nil
	}
	var vmList []map[string]any
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
	result["vms"] = vmList

	if result["node"] == nil && len(vmList) == 0 {
		return nil
	}
	return result
}

// buildBackupIndex fetches all backups of the local node's backup storages and builds a lookup map
// vmid -> newest ctime timestamp. Only O(Storages) API calls instead of O(VMs × Storages).
// nodeName is the resolved local node (not the literal "localhost", on which
// pvesh's implicit mapping is undocumented and could silently break).
// The storages come from /nodes/<node>/storage, which with --content backup lists only the enabled
// backup storages of this node (/storage also lists disabled and other nodes' ones, whose content
// call fails here). The error is the reason the index is incomplete: the list or a content call
// failed, hung or printed no JSON array, or a backup storage is not active.
func buildBackupIndex(nodeName string) (map[int]int64, error) {
	index := make(map[int]int64)

	storagesPath := "/nodes/" + nodeName + "/storage"
	storagesOut, err := pveshCLI.run("get", storagesPath, "--content", "backup", "--output-format", "json")
	if err != nil {
		return nil, fmt.Errorf("pvesh get %s failed: %s", storagesPath,
			commandFailure("pvesh", pluginTimeout, err))
	}
	// null decodes without error, to a nil slice; only an array is a storage list.
	var storages []map[string]any
	if json.Unmarshal(storagesOut, &storages) != nil || storages == nil {
		return nil, fmt.Errorf("pvesh get %s output unreadable", storagesPath)
	}

	for _, storage := range storages {
		sid, _ := storage["storage"].(string)
		// The API schema calls active a boolean, pve-storage sets it to 0 or 1: both readings count.
		// An inactive storage gets no content call, which would only fail with "storage ... is not online".
		if active, _ := storage["active"].(bool); !active && getFloat(storage, "active", 0) == 0 {
			return nil, fmt.Errorf("backup storage %s not active", sid)
		}

		// Fetch all backups of this storage at once (without the --vmid filter)
		contentPath := storagesPath + "/" + sid + "/content"
		backupsOut, err := pveshCLI.run("get", contentPath, "--content", "backup", "--output-format", "json")
		if err != nil {
			return nil, fmt.Errorf("pvesh get %s failed: %s", contentPath,
				commandFailure("pvesh", pluginTimeout, err))
		}
		var items []map[string]any
		if json.Unmarshal(backupsOut, &items) != nil || items == nil {
			return nil, fmt.Errorf("pvesh get %s output unreadable", contentPath)
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
	return index, nil
}

// zpoolCLI indirects collectZFS's zpool lookup and calls so tests can drive every path without zpool
// (same reason as dockerCLI).
var zpoolCLI = struct {
	lookPath func(file string) (string, error)
	run      func(args ...string) ([]byte, error)
}{exec.LookPath, runZpool}

// runZpool runs one zpool call under pluginTimeout; runTimed, so a hung zpool is a timeout.
func runZpool(args ...string) ([]byte, error) {
	return runTimed(pluginTimeout, "zpool", args...)
}

// collectZFS collects ZFS pool information (Linux only). No zpool binary means ZFS is not installed
// and stays silent (nil). With the CLI present the block is always sent: a failing or hanging
// `zpool list` is available=false with an error code, so the monitoring service can raise it instead
// of seeing no data.
func collectZFS() map[string]any {
	if _, err := zpoolCLI.lookPath("zpool"); err != nil {
		return nil
	}

	out, err := zpoolCLI.run("list", "-H", "-o",
		"name,size,alloc,free,cap,health")
	if err != nil {
		return zfsUnavailable(err)
	}

	pools := parseZpoolList(out)
	result := map[string]any{"available": true, "error": nil, "pools": pools}

	// Error details for non-ONLINE pools
	for _, p := range pools {
		if p["health"] != "ONLINE" {
			statusOut, err := zpoolCLI.run("status", "-x")
			if err == nil {
				result["errors"] = strings.TrimSpace(string(statusOut))
			}
			break
		}
	}
	return result
}

// zfsUnavailable is the block for an installed zpool whose `zpool list` failed: error is timeout for
// a call the timeout killed, cli_failed otherwise; error_message names the exit status, never stderr
// or a path (as dockerUnavailable).
func zfsUnavailable(err error) map[string]any {
	code, text := "cli_failed", "zpool list failed: "+commandFailure("zpool", pluginTimeout, err)
	if errors.Is(err, context.DeadlineExceeded) {
		code, text = "timeout", fmt.Sprintf("zpool list timed out after %s", pluginTimeout)
	}
	logger.Warnf("%s, zfs reported as unavailable (%s)", text, code)
	return map[string]any{
		"available":     false,
		"error":         code,
		"error_message": text,
		"pools":         []map[string]any{},
	}
}

// parseZpoolList parses `zpool list -H -o name,size,alloc,free,cap,health` (tab-separated) into pool
// maps, skipping lines with too few columns and stripping the % from the capacity column — the
// positional parsing, testable without running zpool (6.16).
func parseZpoolList(out []byte) []map[string]any {
	pools := []map[string]any{}
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
	return pools
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
