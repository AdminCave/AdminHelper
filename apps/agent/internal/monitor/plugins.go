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
	"maps"
	"net"
	"net/netip"
	"os"
	"os/exec"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"
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
		entry := map[string]any{
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
		}
		putDockerDetails(entry, in)
		containers = append(containers, entry)
	}
	return map[string]any{"available": true, "error": nil, "containers": containers}
}

// maxDockerPorts caps the published ports listed per container, as the discovery caps its port list.
const maxDockerPorts = 64

// maxComposeLabel is the longest compose project or service name sent, the discovery's limit.
const maxComposeLabel = 255

// putDockerDetails sets the compose project and service, the published ports and the start time of
// the inspected container in entry, each only when inspect has it.
func putDockerDetails(entry map[string]any, in dockerInspect) {
	if project := composeLabel(in.Config.Labels, "com.docker.compose.project"); project != "" {
		entry["compose_project"] = project
	}
	if service := composeLabel(in.Config.Labels, "com.docker.compose.service"); service != "" {
		entry["compose_service"] = service
	}
	if ports := publishedPorts(in.NetworkSettings.Ports); len(ports) > 0 {
		entry["ports"] = ports
	}
	// A container that never ran carries the zero time 0001-01-01T00:00:00Z.
	if started, err := time.Parse(time.RFC3339Nano, in.State.StartedAt); err == nil && !started.IsZero() {
		entry["started_at"] = started.Unix()
	}
}

// composeLabel is the label key of labels if it fits maxComposeLabel characters without a control
// character, else "" — the discovery's rule: a cut name would group the container under another
// project.
func composeLabel(labels map[string]string, key string) string {
	return labelText(labels[key])
}

// labelText is s if it fits maxComposeLabel characters without a control character, else "".
func labelText(s string) string {
	if utf8.RuneCountInString(s) > maxComposeLabel || strings.ContainsFunc(s, isControl) {
		return ""
	}
	return s
}

// isControl reports a C0 control character or DEL.
func isControl(r rune) bool { return r < 0x20 || r == 0x7f }

// publishedPorts are the host bindings of the port map m (keyed <port>/<protocol>) as
// host_ip:host_port->port/protocol, the host part as the docker CLI writes it ([::]:8080 for IPv6, no
// address for a binding without one); sorted, at most maxDockerPorts. A port without bindings (null)
// or with an unreadable one is not published.
func publishedPorts(m map[string][]dockerPortBinding) []string {
	var ports []string
	for spec, bindings := range m {
		port, proto, _ := strings.Cut(spec, "/")
		port, ok := portNumber(port)
		if !ok || (proto != "tcp" && proto != "udp" && proto != "sctp") {
			continue
		}
		for _, b := range bindings {
			hostPort, ok := portNumber(b.HostPort)
			if !ok {
				continue
			}
			host := hostPort
			if b.HostIP != "" {
				addr, err := netip.ParseAddr(b.HostIP)
				if err != nil {
					continue
				}
				host = net.JoinHostPort(addr.String(), hostPort)
			}
			ports = append(ports, host+"->"+port+"/"+proto)
		}
	}
	slices.Sort(ports)
	ports = slices.Compact(ports)
	return ports[:min(len(ports), maxDockerPorts)]
}

// portNumber is s as a port number 1-65535 in decimal without leading zeros.
func portNumber(s string) (string, bool) {
	n, err := strconv.ParseUint(s, 10, 16)
	if err != nil || n == 0 {
		return "", false
	}
	return strconv.FormatUint(n, 10), true
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
		StartedAt string
		Health    *struct{ Status string }
	}
	HostConfig struct {
		RestartPolicy struct{ Name string }
	}
	Config struct {
		Labels map[string]string
	}
	NetworkSettings struct {
		Ports map[string][]dockerPortBinding
	}
}

// dockerPortBinding is one host binding of a container port (Engine API PortBinding).
type dockerPortBinding struct {
	HostIP   string `json:"HostIp"`
	HostPort string
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
// no data. saved is the backup index of the last report (buildBackupIndex); the second result is the
// one to save, saved itself after an outage.
func collectProxmox(ctx context.Context, saved *backupIndexCheck, now time.Time) (map[string]any, *backupIndexCheck) {
	if _, err := pveshCLI.lookPath("pvesh"); err != nil {
		return nil, nil
	}

	host, err := pveshCLI.hostname()
	if err != nil {
		return proxmoxUnavailable("cli_failed", "local hostname unreadable"), saved
	}
	nodeName, _, _ := strings.Cut(host, ".") // FQDN -> short name (pvesh nodes are short)
	var nd map[string]any
	if code, text := pveshGet(ctx, &nd, "/nodes/"+nodeName+"/status"); code != "" {
		return proxmoxUnavailable(code, text), saved
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
	backupIndex, check, code, text := buildBackupIndex(ctx, nodeName, saved, now)
	if code != "" {
		return proxmoxUnavailable(code, text), saved
	}

	// VMs + LXC containers. A VM list that could not be read is an outage, not an empty list: the
	// server reads a block without VMs as "no VMs" (ok).
	var vms []map[string]any
	if code, text = pveshGet(ctx, &vms, "/cluster/resources", "--type", "vm"); code != "" {
		return proxmoxUnavailable(code, text), saved
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
		entry := map[string]any{
			"vmid":           vmid,
			"name":           vm["name"],
			"status":         vm["status"],
			"type":           vm["type"],
			"last_backup_ts": lastBackup,
		}
		guestNode, _ := vm["node"].(string)
		pool, _ := vm["pool"].(string)
		check.putBackupDetails(entry, vmid, guestNode, pool)
		vmList = append(vmList, entry)
	}
	return map[string]any{"available": true, "error": nil, "node": node, "vms": vmList}, check
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

// proxmoxBackupsEvery is how long a backup index read from the storages' content stays the index.
// Listing a storage's content activates the storage (pve-storage mounts a missing NFS/CIFS share and
// lists a PBS datastore over the network), so it runs at most this often, not in every report.
const proxmoxBackupsEvery = 30 * time.Minute

const (
	// maxBackupJobs caps the backup jobs kept from /cluster/backup, and so the jobs one guest names.
	maxBackupJobs = 64
	// maxBackupErrorRunes caps the text of a guest's vzdump error (Feld-Freigabe, Konzept §3.13).
	maxBackupErrorRunes = 200
	// backupLogLines caps the lines read from the log of a failed vzdump task: some 20 to 50 per guest.
	backupLogLines = 10000
)

// reBackupError is the line vzdump writes to its task log for a guest whose backup failed
// (pve-guest-common VZDump/Plugin.pm debugmsg: "ERROR: " and the message, without a timestamp;
// pve-manager PVE/VZDump.pm: "Backup of VM <vmid> failed - <first line of the error>").
var reBackupError = regexp.MustCompile(`^ERROR: Backup of VM ([0-9]+) failed - (.*)$`)

// reVerifyState is a verification state as PBS reports it (ok, failed): a short lowercase word.
var reVerifyState = regexp.MustCompile(`^[a-z][a-z0-9_-]{0,31}$`)

// buildBackupIndex returns the lookup map vmid -> newest backup ctime over the local node's backup
// storages, and the check to save. nodeName is the resolved local node (not the literal "localhost",
// on which pvesh's implicit mapping is undocumented and could silently break).
// The storages come from /cluster/resources --type storage, the status pvestatd keeps, which
// activates nothing (/nodes/<node>/storage activates every storage it lists); only those of this node
// whose content allows backups count. Their content is read with one call per storage, O(Storages)
// instead of O(VMs × Storages), and only when saved is not fresh (backupIndexCheck.fresh); else the
// saved index is the index. An incomplete index returns nil with the outage code and its text for
// proxmoxUnavailable, a complete one code "": a call could not be read (pveshGet), or a backup
// storage is not available (backup_index_incomplete). The details are read with the index, never on
// their own: the newest backup per guest from the same content, the backup jobs and the errors of the
// last failed vzdump task; a detail that cannot be read only leaves its part out.
func buildBackupIndex(ctx context.Context, nodeName string, saved *backupIndexCheck, now time.Time) (
	index map[int]int64, check *backupIndexCheck, code, text string) {
	var resources []map[string]any
	if code, text = pveshGet(ctx, &resources, "/cluster/resources", "--type", "storage"); code != "" {
		return nil, nil, code, text
	}
	var storages []string
	for _, res := range resources {
		node, _ := res["node"].(string)
		content, _ := res["content"].(string)
		if node != nodeName || !slices.Contains(strings.Split(content, ","), "backup") {
			continue
		}
		sid, _ := res["storage"].(string)
		// An unavailable storage gets no content call, which would only fail with "storage ... is not
		// online" or hang on its share.
		if status, _ := res["status"].(string); status != "available" {
			return nil, nil, "backup_index_incomplete", "backup storage " + sid + " not active"
		}
		storages = append(storages, sid)
	}
	slices.Sort(storages)
	if saved.fresh(nodeName, storages, now) {
		return saved.Index, saved, "", ""
	}

	index = make(map[int]int64)
	newest := make(map[int]backupDetail)
	for _, sid := range storages {
		// Fetch all backups of this storage at once (without the --vmid filter)
		var items []map[string]any
		path := "/nodes/" + nodeName + "/storage/" + sid + "/content"
		if code, text = pveshGet(ctx, &items, path, "--content", "backup"); code != "" {
			return nil, nil, code, text
		}
		for _, item := range items {
			vmid := int(getFloat(item, "vmid", 0))
			if vmid == 0 {
				continue
			}
			ct := int64(getFloat(item, "ctime", 0))
			if ct > index[vmid] {
				index[vmid] = ct
				newest[vmid] = backupDetailOf(sid, item)
			}
		}
	}
	check = &backupIndexCheck{CheckedUnix: now.Unix(), Node: nodeName, Storages: storages, Index: index, Newest: newest}
	check.Jobs = readBackupJobs(ctx)
	check.ErrorTask, check.Errors = readBackupErrors(ctx, nodeName, saved)
	return index, check, "", ""
}

// backupDetailOf is the detail of the backup item, a content entry of storage: its size, unless PBS
// lists it as 1 for a size it does not know (pve-storage PBSPlugin.pm), and its verification state.
func backupDetailOf(storage string, item map[string]any) backupDetail {
	d := backupDetail{Storage: storage}
	if size := getFloat(item, "size", 0); size > 1 && size < 1<<53 {
		d.Size = int64(size)
	}
	if verification, ok := item["verification"].(map[string]any); ok {
		if state, _ := verification["state"].(string); reVerifyState.MatchString(state) {
			d.Verify = state
		}
	}
	return d
}

// readBackupJobs returns the enabled vzdump jobs of the cluster (`pvesh get /cluster/backup`, jobs of
// vzdump.cron and jobs.cfg; pve-manager PVE/API2/Backup.pm), at most maxBackupJobs, in its order; nil
// when they could not be read, which leaves the jobs out of the report. A disabled job runs never
// (enabled defaults to 1).
func readBackupJobs(ctx context.Context) []backupJob {
	var items []map[string]any
	if code, text := pveshGet(ctx, &items, "/cluster/backup"); code != "" {
		logger.Warnf("%s, backup jobs left out (%s)", text, code)
		return nil
	}
	jobs := []backupJob{}
	for _, item := range items {
		if !pveBool(item["enabled"], true) {
			continue
		}
		if len(jobs) == maxBackupJobs {
			break
		}
		pool, _ := item["pool"].(string)
		node, _ := item["node"].(string)
		jobs = append(jobs, backupJob{
			ID:       labelText(pveString(item["id"])),
			Schedule: labelText(pveString(item["schedule"])),
			Storage:  labelText(pveString(item["storage"])),
			Pool:     pool,
			VMIDs:    vmidList(item["vmid"]),
			All:      pveBool(item["all"], false),
			Exclude:  vmidList(item["exclude"]),
			Node:     node,
		})
	}
	return jobs
}

// readBackupErrors returns the UPID of the last failed vzdump task on node and the errors its log
// names per guest; "" and nil when there is none or it could not be read. Failed means an error
// status (--statusfilter error, PVE::UPID status_is_error), not one with warnings only. The log of the
// task saved names is not read again: its errors are saved's.
func readBackupErrors(ctx context.Context, node string, saved *backupIndexCheck) (string, map[int]backupError) {
	var tasks []map[string]any
	path := "/nodes/" + node + "/tasks"
	if code, text := pveshGet(ctx, &tasks, path, "--typefilter", "vzdump", "--statusfilter", "error",
		"--limit", "1"); code != "" {
		logger.Warnf("%s, backup errors left out (%s)", text, code)
		return "", nil
	}
	if len(tasks) == 0 {
		return "", nil
	}
	upid, _ := tasks[0]["upid"].(string)
	start := int64(getFloat(tasks[0], "starttime", 0))
	if saved != nil && saved.ErrorTask != "" && saved.ErrorTask == upid {
		return upid, saved.Errors
	}
	logPath := path + "/" + upid + "/log"
	limit := strconv.Itoa(backupLogLines)
	// The UPID comes from pvesh: one that is no vzdump task of this form stays unread rather than
	// becoming a refused call.
	if start <= 0 || !commandAllowed("pvesh", []string{"get", logPath, "--limit", limit, "--output-format", "json"}) {
		logger.Warnf("last failed backup task of %s unreadable, backup errors left out", node)
		return "", nil
	}
	var lines []struct {
		T string `json:"t"`
	}
	if code, text := pveshGet(ctx, &lines, logPath, "--limit", limit); code != "" {
		logger.Warnf("%s, backup errors left out (%s)", text, code)
		return "", nil
	}
	errs := map[int]backupError{}
	for _, line := range lines {
		m := reBackupError.FindStringSubmatch(line.T)
		if m == nil {
			continue
		}
		if vmid, err := strconv.Atoi(m[1]); err == nil && vmid > 0 {
			errs[vmid] = backupError{Unix: start, Text: capBackupError(m[2])}
		}
	}
	return upid, errs
}

// capBackupError is text with each control character as a space, cut to maxBackupErrorRunes.
func capBackupError(text string) string {
	runes := []rune(strings.Map(func(r rune) rune {
		if isControl(r) {
			return ' '
		}
		return r
	}, text))
	if len(runes) > maxBackupErrorRunes {
		runes = runes[:maxBackupErrorRunes]
	}
	return string(runes)
}

// pveString is v if it is a string, else "".
func pveString(v any) string {
	s, _ := v.(string)
	return s
}

// pveBool reads a boolean of the PVE API, which pvesh prints as a number, a string or a JSON boolean
// depending on where the value comes from; a string as PVE::JSONSchema parse_boolean reads it. A
// missing or unreadable value is def.
func pveBool(v any, def bool) bool {
	switch b := v.(type) {
	case bool:
		return b
	case float64:
		return b != 0
	case string:
		switch strings.ToLower(b) {
		case "1", "on", "yes", "true":
			return true
		case "0", "off", "no", "false":
			return false
		}
	}
	return def
}

// vmidList reads a pve-vmid-list (a string of VMIDs, split as PVE::Tools split_list does: on NUL if it
// has one, else on ',', ';' and whitespace) or a single number; tokens that are no VMID are skipped,
// as is 0 (vzdump check_vmids).
func vmidList(v any) []int {
	var tokens []string
	switch s := v.(type) {
	case float64:
		tokens = []string{strconv.FormatFloat(s, 'f', -1, 64)}
	case string:
		if strings.Contains(s, "\x00") {
			tokens = strings.Split(s, "\x00")
		} else {
			tokens = strings.Fields(strings.NewReplacer(",", " ", ";", " ").Replace(s))
		}
	}
	var ids []int
	for _, tok := range tokens {
		if tok == "" || strings.Trim(tok, "0123456789") != "" {
			continue
		}
		if id, err := strconv.Atoi(tok); err == nil && id > 0 {
			ids = append(ids, id)
		}
	}
	return ids
}

// covers reports whether job backs up the guest vmid on node in pool, by the rule of vzdump
// (pve-manager PVE/VZDump.pm get_included_guests): a pool selects its members, else a VMID list its
// guests, else all guests but the excluded; a job bound to a node only the guests on it.
func (job backupJob) covers(vmid int, node, pool string) bool {
	var in bool
	switch {
	case job.Pool != "":
		in = pool == job.Pool
	case len(job.VMIDs) > 0:
		in = slices.Contains(job.VMIDs, vmid)
	case job.All:
		in = !slices.Contains(job.Exclude, vmid)
	}
	return in && (job.Node == "" || job.Node == node)
}

// putBackupDetails sets the backup details of the guest vmid on node in pool in entry, each only when
// known: storage, size and verification state of its newest backup; the jobs that cover it (an empty
// list when the jobs were read and none does); the error of the last failed vzdump task, unless the
// guest has a backup newer than that task's start.
func (check *backupIndexCheck) putBackupDetails(entry map[string]any, vmid int, node, pool string) {
	if d, ok := check.Newest[vmid]; ok {
		entry["backup_storage"] = d.Storage
		if d.Size > 0 {
			entry["backup_size"] = d.Size
		}
		if d.Verify != "" {
			entry["backup_verify"] = d.Verify
		}
	}
	if check.Jobs != nil {
		jobs := []map[string]any{}
		for _, job := range check.Jobs {
			if !job.covers(vmid, node, pool) {
				continue
			}
			wire := map[string]any{}
			for key, value := range map[string]string{"id": job.ID, "schedule": job.Schedule, "storage": job.Storage} {
				if value != "" {
					wire[key] = value
				}
			}
			jobs = append(jobs, wire)
		}
		entry["backup_jobs"] = jobs
	}
	if e, ok := check.Errors[vmid]; ok && e.Unix >= check.Index[vmid] {
		entry["backup_error"] = e.Text
		entry["backup_error_ts"] = e.Unix
	}
}

// fresh reports whether check is the index to use for the backup storages of node now: read less than
// proxmoxBackupsEvery ago, for the same node and the same storages, so a storage that was added or
// came back is read at once. A check from the future (the clock was set back) is due, as in
// securityUpdates, and so is one without an index (a state saved before, or a corrupt one).
func (check *backupIndexCheck) fresh(node string, storages []string, now time.Time) bool {
	if check == nil || check.Index == nil || check.Node != node || !slices.Equal(check.Storages, storages) {
		return false
	}
	age := now.Sub(time.Unix(check.CheckedUnix, 0))
	return age >= 0 && age < proxmoxBackupsEvery
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
		"name,size,alloc,free,cap,health,frag")
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

	if len(pools) > 0 {
		details := zpoolDetails(ctx)
		for _, p := range pools {
			name, _ := p["name"].(string)
			maps.Copy(p, details[name])
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

// parseZpoolList parses `zpool list -H -o name,size,alloc,free,cap,health,frag` (tab-separated) into
// pool maps, skipping lines with too few columns and stripping the % from the capacity column — the
// positional parsing, testable without running zpool (6.16). fragmentation_percent is left out where
// zpool prints "-" (unknown, zpoolprops(7)) or something else than a percentage.
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
		if len(parts) > 6 {
			if frag, ok := zpoolPercent(parts[6]); ok {
				pools[len(pools)-1]["fragmentation_percent"] = frag
			}
		}
	}
	return pools
}

// zpoolPercent reads a percentage as `zpool list` prints it without -p ("12%", libzfs
// zpool_get_prop), ok only for 0 to 100.
func zpoolPercent(s string) (int, bool) {
	digits, found := strings.CutSuffix(s, "%")
	n, err := strconv.Atoi(digits)
	if !found || err != nil || n < 0 || n > 100 {
		return 0, false
	}
	return n, true
}

// maxZpoolVdevErrors caps the vdevs with errors named per pool.
const maxZpoolVdevErrors = 32

// zpoolScanStates are the states of a scan that zpool status -j writes (pool_scan_state_str in
// cmd/zpool/zpool_main.c) and a scrub can be in; NONE means no scan. A paused scrub stays SCANNING
// with scrub_pause set (print_scan_scrub_resilver_status), the agent sends it as PAUSED.
var zpoolScanStates = map[string]bool{"SCANNING": true, "FINISHED": true, "CANCELED": true}

// zpoolStatus is what the pool details read of `zpool status -j --json-int --json-flat-vdevs`
// (zpool-status(8); zpool_main.c scan_status_nvlist, vdev_stats_nvlist): per pool, keyed by its name,
// the last scan and the error counters of every vdev, the pool's root vdev and the log, cache, spare,
// special and dedup vdevs included.
type zpoolStatus struct {
	Pools map[string]struct {
		Scan *struct {
			Function string `json:"function"`
			State    string `json:"state"`
			EndTime  uint64 `json:"end_time"`
			Errors   uint64 `json:"errors"`
			Pause    uint64 `json:"scrub_pause"`
		} `json:"scan_stats"`
		Vdevs map[string]struct {
			Name     string `json:"name"`
			Read     uint64 `json:"read_errors"`
			Write    uint64 `json:"write_errors"`
			Checksum uint64 `json:"checksum_errors"`
		} `json:"vdevs"`
	} `json:"pools"`
}

// zpoolDetails are the details of each pool by name (parseZpoolStatus). A zpool without -j (OpenZFS
// 2.2 and older), a call that fails or times out, or output it cannot read gives none and no error:
// the pools go out as before, like without `zpool status -x`.
func zpoolDetails(ctx context.Context) map[string]map[string]any {
	out, err := zpoolCLI.run(ctx, "status", "-j", "--json-int", "--json-flat-vdevs")
	if err != nil {
		return nil
	}
	return parseZpoolStatus(out)
}

// parseZpoolStatus reads per pool the last scrub — scrub {state, errors, end} where the last scan was
// a scrub, state SCANNING, PAUSED, FINISHED or CANCELED, end once it is no longer running — and
// vdev_errors, the vdevs with a read, write or checksum error {name, read, write, checksum}, sorted by
// name, at most maxZpoolVdevErrors; a pool with neither has no entry. Output it cannot read, a count
// as a string included, gives nil.
func parseZpoolStatus(out []byte) map[string]map[string]any {
	var status zpoolStatus
	if err := json.Unmarshal(out, &status); err != nil {
		return nil
	}
	details := map[string]map[string]any{}
	for pool, st := range status.Pools {
		detail := map[string]any{}
		if scan := st.Scan; scan != nil && scan.Function == "SCRUB" && zpoolScanStates[scan.State] {
			scrub := map[string]any{"state": scan.State, "errors": scan.Errors}
			if scan.State == "SCANNING" && scan.Pause > 0 {
				scrub["state"] = "PAUSED"
			}
			if scan.State != "SCANNING" && scan.EndTime > 0 {
				scrub["end"] = scan.EndTime
			}
			detail["scrub"] = scrub
		}
		var vdevs []map[string]any
		for _, v := range st.Vdevs {
			if v.Read == 0 && v.Write == 0 && v.Checksum == 0 {
				continue
			}
			vdevs = append(vdevs, map[string]any{
				"name": labelText(v.Name), "read": v.Read, "write": v.Write, "checksum": v.Checksum,
			})
		}
		slices.SortFunc(vdevs, func(a, b map[string]any) int {
			return strings.Compare(a["name"].(string), b["name"].(string))
		})
		if len(vdevs) > maxZpoolVdevErrors {
			vdevs = vdevs[:maxZpoolVdevErrors]
		}
		if len(vdevs) > 0 {
			detail["vdev_errors"] = vdevs
		}
		if len(detail) > 0 {
			details[pool] = detail
		}
	}
	return details
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
