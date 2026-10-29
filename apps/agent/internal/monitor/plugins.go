// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"bytes"
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

// runWithTimeout runs a plugin command under pluginTimeout and ctx, mirroring the docker
// path, so a hung external tool can never block the report cycle. Through runTimed, a
// call the timeout ended returns context.DeadlineExceeded, which the systemctl and sc
// reasons (commandFailure) name as a timeout instead of the ExitError exec reports
// ("signal: killed" on Linux, "exit status 1" on Windows).
func runWithTimeout(ctx context.Context, name string, args ...string) ([]byte, error) {
	return runTimed(ctx, pluginTimeout, name, args...)
}

// dockerCLI indirects collectDocker's docker lookup and calls so tests can drive every path without
// docker, which is slow and host-dependent (same reason as pluginCollectors, 6.18).
var dockerCLI = struct {
	lookPath func(file string) (string, error)
	run      func(ctx context.Context, args ...string) ([]byte, error)
}{exec.LookPath, runDocker}

// runDocker runs one docker CLI call under dockerTimeout.
func runDocker(ctx context.Context, args ...string) ([]byte, error) {
	return runTimed(ctx, dockerTimeout, "docker", args...)
}

// commandWaitDelay bounds how long runTimed waits for a command's pipes once its context ended or the
// command exited. The kill reaches only the tool: a grandchild that inherited its stdout (a daemon, a
// pager) kept the pipe open, and Output read it past the timeout until the grandchild ended.
const commandWaitDelay = 2 * time.Second

// runTimed runs a command under timeout and ctx, whichever ends first. A call either ended returns the
// context's error (context.DeadlineExceeded at the timeout or the deadline of ctx, context.Canceled
// when ctx was canceled): exec itself reports it as the ExitError "signal: killed", which would pass a
// hanging tool off as a failing one. exec.ErrWaitDelay means the command exited 0 and only a child of
// it held the pipe past commandWaitDelay: the command's output is complete, so it is no error.
func runTimed(ctx context.Context, timeout time.Duration, name string, args ...string) ([]byte, error) {
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, name, args...)
	cmd.WaitDelay = commandWaitDelay
	out, err := cmd.Output()
	if errors.Is(err, exec.ErrWaitDelay) {
		return out, nil
	}
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
func collectDocker(ctx context.Context) map[string]any {
	if _, err := dockerCLI.lookPath("docker"); err != nil {
		return nil
	}
	if _, err := dockerCLI.run(ctx, "info"); err != nil {
		return dockerUnavailable("info", "daemon_unreachable", err)
	}

	out, err := dockerCLI.run(ctx, "ps", "-a", "--format", "{{json .}}")
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
	out, err = dockerCLI.run(ctx, append([]string{"inspect", "--type", "container"}, ids...)...)
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

// pveshCLI indirects collectProxmox's pvesh lookup and calls, and the hostname its node name comes
// from, so tests can drive every path without pvesh (same reason as dockerCLI).
var pveshCLI = struct {
	lookPath func(file string) (string, error)
	run      func(ctx context.Context, args ...string) ([]byte, error)
	hostname func() (string, error)
}{exec.LookPath, runPvesh, os.Hostname}

// runPvesh runs one pvesh call under pluginTimeout (runWithTimeout).
func runPvesh(ctx context.Context, args ...string) ([]byte, error) {
	return runWithTimeout(ctx, "pvesh", args...)
}

// pveshGet runs `pvesh get <path> <args> --output-format json` and decodes the answer into out, a
// pointer to a map or a slice. On failure it returns the outage code and its text for
// proxmoxUnavailable, "" on success: a call the timeout ended is timeout, an exit status or a pvesh
// that did not start cli_failed, an answer that is no JSON of out's form parse_failed. null decodes
// without error, to a nil map or slice, so it is checked for on its own.
func pveshGet(ctx context.Context, out any, path string, args ...string) (code, text string) {
	call := "pvesh get " + path
	raw, err := pveshCLI.run(ctx, append(append([]string{"get", path}, args...), "--output-format", "json")...)
	switch {
	case errors.Is(err, context.DeadlineExceeded):
		return "timeout", fmt.Sprintf("%s timed out after %s", call, pluginTimeout)
	case err != nil:
		return "cli_failed", call + " failed: " + commandFailure("pvesh", pluginTimeout, err)
	case json.Unmarshal(raw, out) != nil || string(bytes.TrimSpace(raw)) == "null":
		return "parse_failed", call + " output unreadable"
	}
	return "", ""
}

// collectProxmox collects Proxmox metrics (Linux with pvesh only). No pvesh binary means Proxmox is
// not installed and stays silent (nil). With the CLI present the block is always sent: an unreadable
// hostname, or a node status, backup index or VM list that could not be read, is available=false
// with an error code (proxmoxUnavailable), so the monitoring service can raise it instead of seeing
// no data.
func collectProxmox(ctx context.Context) map[string]any {
	if _, err := pveshCLI.lookPath("pvesh"); err != nil {
		return nil
	}

	host, err := pveshCLI.hostname()
	if err != nil {
		return proxmoxUnavailable("cli_failed", "local hostname unreadable")
	}
	nodeName, _, _ := strings.Cut(host, ".") // FQDN -> short name (pvesh nodes are short)
	var nd map[string]any
	if code, text := pveshGet(ctx, &nd, "/nodes/"+nodeName+"/status"); code != "" {
		return proxmoxUnavailable(code, text)
	}
	memData, _ := nd["memory"].(map[string]any)
	total := getFloat(memData, "total", 1)
	if total == 0 {
		total = 1
	}
	node := map[string]any{
		"name":           nodeName,
		"cpu":            round1(getFloat(nd, "cpu", 0) * 100),
		"memory_percent": round1(getFloat(memData, "used", 0) / total * 100),
	}

	// Build the backup index once for all VMs (O(Storages) instead of O(VMs × Storages)). Without
	// every backup storage read, each VM whose backups sit on a missing one would go out without
	// last_backup_ts, which the server reads as "No backup" (critical): an outage instead.
	backupIndex, code, text := buildBackupIndex(ctx, nodeName)
	if code != "" {
		return proxmoxUnavailable(code, text)
	}

	// VMs + LXC containers. A VM list that could not be read is an outage, not an empty list: the
	// server reads a block without VMs as "no VMs" (ok).
	var vms []map[string]any
	if code, text = pveshGet(ctx, &vms, "/cluster/resources", "--type", "vm"); code != "" {
		return proxmoxUnavailable(code, text)
	}
	vmList := make([]map[string]any, 0, len(vms))
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
	return map[string]any{"available": true, "error": nil, "node": node, "vms": vmList}
}

// proxmoxUnavailable is the block for an installed pvesh whose node could not be read. code is what
// the monitoring service evaluates (timeout | cli_failed | parse_failed | backup_index_incomplete),
// text names the call and its exit status or the inactive storage — never stderr or a file path (as
// dockerUnavailable).
func proxmoxUnavailable(code, text string) map[string]any {
	logger.Warnf("%s, proxmox reported as unavailable (%s)", text, code)
	return map[string]any{
		"available":     false,
		"error":         code,
		"error_message": text,
		"node":          nil,
		"vms":           []map[string]any{},
	}
}

// buildBackupIndex fetches all backups of the local node's backup storages and builds a lookup map
// vmid -> newest ctime timestamp. Only O(Storages) API calls instead of O(VMs × Storages).
// nodeName is the resolved local node (not the literal "localhost", on which
// pvesh's implicit mapping is undocumented and could silently break).
// The storages come from /nodes/<node>/storage, which with --content backup lists only the enabled
// backup storages of this node (/storage also lists disabled and other nodes' ones, whose content
// call fails here). An incomplete index returns nil with the outage code and its text for
// proxmoxUnavailable, a complete one code "": the list or a content call could not be read
// (pveshGet), or a backup storage is not active (backup_index_incomplete).
func buildBackupIndex(ctx context.Context, nodeName string) (index map[int]int64, code, text string) {
	index = make(map[int]int64)

	storagesPath := "/nodes/" + nodeName + "/storage"
	var storages []map[string]any
	if code, text = pveshGet(ctx, &storages, storagesPath, "--content", "backup"); code != "" {
		return nil, code, text
	}

	for _, storage := range storages {
		sid, _ := storage["storage"].(string)
		// The API schema calls active a boolean, pve-storage sets it to 0 or 1: both readings count.
		// An inactive storage gets no content call, which would only fail with "storage ... is not online".
		if active, _ := storage["active"].(bool); !active && getFloat(storage, "active", 0) == 0 {
			return nil, "backup_index_incomplete", "backup storage " + sid + " not active"
		}

		// Fetch all backups of this storage at once (without the --vmid filter)
		var items []map[string]any
		if code, text = pveshGet(ctx, &items, storagesPath+"/"+sid+"/content", "--content", "backup"); code != "" {
			return nil, code, text
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
	return index, "", ""
}

// zpoolCLI indirects collectZFS's zpool lookup and calls so tests can drive every path without zpool
// (same reason as dockerCLI).
var zpoolCLI = struct {
	lookPath func(file string) (string, error)
	run      func(ctx context.Context, args ...string) ([]byte, error)
}{exec.LookPath, runZpool}

// runZpool runs one zpool call under pluginTimeout; runTimed, so a hung zpool is a timeout.
func runZpool(ctx context.Context, args ...string) ([]byte, error) {
	return runTimed(ctx, pluginTimeout, "zpool", args...)
}

// collectZFS collects ZFS pool information (Linux only). No zpool binary means ZFS is not installed
// and stays silent (nil). With the CLI present the block is always sent: a failing or hanging
// `zpool list` is available=false with an error code, so the monitoring service can raise it instead
// of seeing no data.
func collectZFS(ctx context.Context) map[string]any {
	if _, err := zpoolCLI.lookPath("zpool"); err != nil {
		return nil
	}

	out, err := zpoolCLI.run(ctx, "list", "-H", "-o",
		"name,size,alloc,free,cap,health")
	if err != nil {
		return zfsUnavailable(err)
	}

	pools := parseZpoolList(out)
	result := map[string]any{"available": true, "error": nil, "pools": pools}

	// Error details for non-ONLINE pools
	for _, p := range pools {
		if p["health"] != "ONLINE" {
			statusOut, err := zpoolCLI.run(ctx, "status", "-x")
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
