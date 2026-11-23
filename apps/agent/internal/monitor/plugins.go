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
	"io"
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

// DockerBlock is the docker block. Containers is never nil: the wire carries [] for no container,
// also when docker is unavailable. Error is null while available and the error code otherwise.
type DockerBlock struct {
	Available    bool              `json:"available"`
	Error        *string           `json:"error"`
	ErrorMessage string            `json:"error_message,omitempty"`
	Containers   []DockerContainer `json:"containers"`
}

// DockerContainer is one container of the docker block. The compose fields, ports and started_at come
// only when inspect has them (putDockerDetails).
type DockerContainer struct {
	ID             string   `json:"id"`
	Name           string   `json:"name"`
	Image          string   `json:"image"`
	State          string   `json:"state"`
	Status         string   `json:"status"`
	RestartPolicy  string   `json:"restart_policy"`
	ExitCode       int      `json:"exit_code"`
	OOMKilled      bool     `json:"oom_killed"`
	RestartCount   int      `json:"restart_count"`
	Health         string   `json:"health"`
	ComposeProject string   `json:"compose_project,omitempty"`
	ComposeService string   `json:"compose_service,omitempty"`
	ComposeNumber  int      `json:"compose_number,omitempty"`
	Ports          []string `json:"ports,omitempty"`
	StartedAt      *int64   `json:"started_at,omitempty"`
}

// collectDocker collects Docker container status (cross-platform). No docker binary means Docker is
// not installed and stays silent (nil). With the CLI present the block is always sent: a daemon that
// does not answer, a failing or hanging call or unreadable output is available=false with an error
// code, so the monitoring service can raise it instead of seeing no data. Every abort is logged, so
// `diagnose` shows the reason.
func collectDocker(ctx context.Context) *DockerBlock {
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
	containers := make([]DockerContainer, 0, len(listed))
	if len(listed) == 0 {
		return &DockerBlock{Available: true, Containers: containers}
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
		in, ok := byShortID[c.ID]
		if !ok {
			continue
		}
		// state from the same snapshot as exit_code and oom_killed, so they never contradict.
		state := c.State
		if in.State.Status != "" {
			state = in.State.Status
		}
		health := ""
		if in.State.Health != nil {
			health = in.State.Health.Status
		}
		entry := DockerContainer{
			ID:            c.ID,
			Name:          c.Names,
			Image:         c.Image,
			State:         state,
			Status:        c.Status,
			RestartPolicy: in.HostConfig.RestartPolicy.Name,
			ExitCode:      in.State.ExitCode,
			OOMKilled:     in.State.OOMKilled,
			RestartCount:  in.RestartCount,
			Health:        health,
		}
		putDockerDetails(&entry, in)
		containers = append(containers, entry)
	}
	return &DockerBlock{Available: true, Containers: containers}
}

// maxDockerPorts caps the published ports listed per container, as the discovery caps its port list.
const maxDockerPorts = 64

// maxComposeLabel is the longest compose project or service name sent, the discovery's limit.
const maxComposeLabel = 255

// putDockerDetails sets the compose project, service and container number, the published ports and the start time of
// the inspected container in entry, each only when inspect has it.
func putDockerDetails(entry *DockerContainer, in dockerInspect) {
	entry.ComposeProject = composeLabel(in.Config.Labels, "com.docker.compose.project")
	entry.ComposeService = composeLabel(in.Config.Labels, "com.docker.compose.service")
	// The replica number keys the container across recreation (ADR 0004 §12.6); compose numbers from 1.
	if n, err := strconv.Atoi(in.Config.Labels["com.docker.compose.container-number"]); err == nil && n > 0 {
		entry.ComposeNumber = n
	}
	entry.Ports = publishedPorts(in.NetworkSettings.Ports)
	// A container that never ran carries the zero time 0001-01-01T00:00:00Z.
	if started, err := time.Parse(time.RFC3339Nano, in.State.StartedAt); err == nil && !started.IsZero() {
		unix := started.Unix()
		entry.StartedAt = &unix
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
func dockerUnavailable(call, code string, err error) *DockerBlock {
	text := "docker " + call + " output unreadable"
	switch {
	case errors.Is(err, context.DeadlineExceeded):
		code = "timeout"
		text = fmt.Sprintf("docker %s timed out after %s", call, dockerTimeout)
	case err != nil:
		text = "docker " + call + " failed: " + commandFailure("docker", dockerTimeout, err)
	}
	logger.Warnf("%s, docker reported as unavailable (%s)", text, code)
	return &DockerBlock{Error: &code, ErrorMessage: text, Containers: []DockerContainer{}}
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

// parseDockerPS parses `docker ps -a --format {{json .}}` (one JSON object per line) into its lines
// and their IDs, skipping blank lines and counting unparseable ones in skipped — the parsing,
// testable without docker (6.16).
func parseDockerPS(out []byte) (containers []dockerPSLine, ids []string, skipped int) {
	for _, line := range strings.Split(strings.TrimSpace(string(out)), "\n") {
		if line == "" {
			continue
		}
		var c dockerPSLine
		if err := json.Unmarshal([]byte(line), &c); err != nil {
			skipped++
			continue
		}
		containers = append(containers, c)
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

// pveshCLI indirects collectProxmox's pvesh lookup and calls, the hostname its node name comes
// from and the corosync config its cluster name comes from, so tests can drive every path without
// pvesh (same reason as dockerCLI).
var pveshCLI = struct {
	lookPath     func(file string) (string, error)
	run          func(ctx context.Context, args ...string) ([]byte, error)
	hostname     func() (string, error)
	corosyncConf string
}{exec.LookPath, runPvesh, os.Hostname, "/etc/pve/corosync.conf"}

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

// ProxmoxBlock is the proxmox block. VMs is never nil (the wire carries [] for none, also when
// unavailable); Node is null and Error the code while unavailable, Error null while available.
type ProxmoxBlock struct {
	Available    bool           `json:"available"`
	Error        *string        `json:"error"`
	ErrorMessage string         `json:"error_message,omitempty"`
	Node         *ProxmoxNode   `json:"node"`
	VMs          []ProxmoxGuest `json:"vms"`
	ClusterName  string         `json:"cluster_name,omitempty"`
}

// ProxmoxNode is the local node of the proxmox block, cpu and memory in percent.
type ProxmoxNode struct {
	Name          string  `json:"name"`
	CPU           float64 `json:"cpu"`
	MemoryPercent float64 `json:"memory_percent"`
}

// ProxmoxGuest is a VM or container of the proxmox block. Name, status and type are pvesh's strings,
// null when it sends none; last_backup_ts is null without a backup. The backup details come only when
// known (putBackupDetails): backup_jobs is [] when the jobs were read and none covers the guest, and
// missing when they could not be read.
type ProxmoxGuest struct {
	VMID          int                `json:"vmid"`
	Name          *string            `json:"name"`
	Status        *string            `json:"status"`
	Type          *string            `json:"type"`
	LastBackupTS  *int64             `json:"last_backup_ts"`
	BackupStorage string             `json:"backup_storage,omitempty"`
	BackupSize    int64              `json:"backup_size,omitempty"`
	BackupVerify  string             `json:"backup_verify,omitempty"`
	BackupJobs    []ProxmoxBackupJob `json:"backup_jobs,omitzero"`
	BackupError   *string            `json:"backup_error,omitempty"`
	BackupErrorTS *int64             `json:"backup_error_ts,omitempty"`
}

// ProxmoxBackupJob is a backup job that covers a guest, each field only when the job names it.
type ProxmoxBackupJob struct {
	ID       string `json:"id,omitempty"`
	Schedule string `json:"schedule,omitempty"`
	Storage  string `json:"storage,omitempty"`
}

// collectProxmox collects Proxmox metrics (Linux with pvesh only). No pvesh binary means Proxmox is
// not installed and stays silent (nil). With the CLI present the block is always sent: an unreadable
// hostname, or a node status, backup index or VM list that could not be read, is available=false
// with an error code (proxmoxUnavailable), so the monitoring service can raise it instead of seeing
// no data. saved is the backup index of the last report (buildBackupIndex); the second result is the
// one to save, saved itself after an outage.
func collectProxmox(ctx context.Context, saved *backupIndexCheck, now time.Time) (*ProxmoxBlock, *backupIndexCheck) {
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
	node := &ProxmoxNode{
		Name:          nodeName,
		CPU:           round1(getFloat(nd, "cpu", 0) * 100),
		MemoryPercent: round1(getFloat(memData, "used", 0) / total * 100),
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
	vmList := make([]ProxmoxGuest, 0, len(vms))
	for _, vm := range vms {
		vmid := int(getFloat(vm, "vmid", 0))
		if vmid == 0 {
			continue
		}
		entry := ProxmoxGuest{VMID: vmid, Name: pveText(vm["name"]), Status: pveText(vm["status"]), Type: pveText(vm["type"])}
		if ts, ok := backupIndex[vmid]; ok {
			entry.LastBackupTS = &ts
		}
		guestNode, _ := vm["node"].(string)
		pool, _ := vm["pool"].(string)
		check.putBackupDetails(&entry, vmid, guestNode, pool)
		vmList = append(vmList, entry)
	}
	block := &ProxmoxBlock{Available: true, Node: node, VMs: vmList, ClusterName: corosyncClusterName(pveshCLI.corosyncConf)}
	return block, check
}

// maxCorosyncConf caps how much of corosync.conf is read; a real one is a few KiB.
const maxCorosyncConf = 1 << 20

// corosyncClusterName is totem.cluster_name from the corosync config at path, "" without the file
// (a node in no cluster: pvecm deletes it on leaving), without the key or with a name labelText
// rejects. A file read instead of `pvesh get /cluster/status`: no extra process per report (ADR 0004
// §11). Only that key in the top-level totem section counts, nothing from another section.
func corosyncClusterName(path string) string {
	f, err := os.Open(path)
	if err != nil {
		return ""
	}
	defer f.Close()
	raw, err := io.ReadAll(io.LimitReader(f, maxCorosyncConf))
	if err != nil {
		return ""
	}
	var sections []string
	for line := range strings.Lines(string(raw)) {
		line = strings.TrimSpace(line)
		switch {
		case line == "" || strings.HasPrefix(line, "#"):
		case strings.HasSuffix(line, "{"):
			sections = append(sections, strings.TrimSpace(strings.TrimSuffix(line, "{")))
		case line == "}":
			if len(sections) > 0 {
				sections = sections[:len(sections)-1]
			}
		case len(sections) == 1 && sections[0] == "totem":
			if key, value, ok := strings.Cut(line, ":"); ok && strings.TrimSpace(key) == "cluster_name" {
				return labelText(strings.TrimSpace(value))
			}
		}
	}
	return ""
}

// proxmoxUnavailable is the block for an installed pvesh whose node could not be read. code is what
// the monitoring service evaluates (timeout | cli_failed | parse_failed | backup_index_incomplete),
// text names the call and its exit status or the inactive storage — never stderr or a file path (as
// dockerUnavailable).
func proxmoxUnavailable(code, text string) *ProxmoxBlock {
	logger.Warnf("%s, proxmox reported as unavailable (%s)", text, code)
	return &ProxmoxBlock{Error: &code, ErrorMessage: text, VMs: []ProxmoxGuest{}}
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

// pveText is v if it is a string, else nil: a guest field pvesh did not send goes out as null.
func pveText(v any) *string {
	s, ok := v.(string)
	if !ok {
		return nil
	}
	return &s
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
func (check *backupIndexCheck) putBackupDetails(entry *ProxmoxGuest, vmid int, node, pool string) {
	if d, ok := check.Newest[vmid]; ok {
		entry.BackupStorage = d.Storage
		if d.Size > 0 {
			entry.BackupSize = d.Size
		}
		entry.BackupVerify = d.Verify
	}
	if check.Jobs != nil {
		entry.BackupJobs = []ProxmoxBackupJob{}
		for _, job := range check.Jobs {
			if job.covers(vmid, node, pool) {
				entry.BackupJobs = append(entry.BackupJobs, ProxmoxBackupJob{ID: job.ID, Schedule: job.Schedule, Storage: job.Storage})
			}
		}
	}
	if e, ok := check.Errors[vmid]; ok && e.Unix >= check.Index[vmid] {
		entry.BackupError = &e.Text
		entry.BackupErrorTS = &e.Unix
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

// ZFSBlock is the zfs block. Pools is never nil (the wire carries [] for none, also when
// unavailable); Error is null while available. Errors is the text of `zpool status -x`, sent only when
// a pool is not ONLINE and the call succeeded.
type ZFSBlock struct {
	Available    bool    `json:"available"`
	Error        *string `json:"error"`
	ErrorMessage string  `json:"error_message,omitempty"`
	Pools        []ZPool `json:"pools"`
	Errors       *string `json:"errors,omitempty"`
}

// ZPool is a pool of the zfs block as `zpool list` prints it, with its details (zpoolDetail) when
// `zpool status -j` gave them.
type ZPool struct {
	Name                 string `json:"name"`
	Size                 string `json:"size"`
	Allocated            string `json:"allocated"`
	Free                 string `json:"free"`
	CapacityPercent      int    `json:"capacity_percent"`
	Health               string `json:"health"`
	FragmentationPercent *int   `json:"fragmentation_percent,omitempty"`
	zpoolDetail
}

// zpoolDetail is what parseZpoolStatus reads of a pool: its last scrub and the vdevs with errors.
type zpoolDetail struct {
	Scrub      *ZPoolScrub      `json:"scrub,omitempty"`
	VdevErrors []ZPoolVdevError `json:"vdev_errors,omitempty"`
}

// ZPoolScrub is a pool's last scrub; End is left out while it runs or when zpool names none.
type ZPoolScrub struct {
	State  string `json:"state"`
	Errors uint64 `json:"errors"`
	End    uint64 `json:"end,omitempty"`
}

// ZPoolVdevError is a vdev with a read, write or checksum error.
type ZPoolVdevError struct {
	Name     string `json:"name"`
	Read     uint64 `json:"read"`
	Write    uint64 `json:"write"`
	Checksum uint64 `json:"checksum"`
}

// collectZFS collects ZFS pool information (Linux only). No zpool binary means ZFS is not installed
// and stays silent (nil). With the CLI present the block is always sent: a failing or hanging
// `zpool list` is available=false with an error code, so the monitoring service can raise it instead
// of seeing no data.
func collectZFS(ctx context.Context) *ZFSBlock {
	if _, err := zpoolCLI.lookPath("zpool"); err != nil {
		return nil
	}

	out, err := zpoolCLI.run(ctx, "list", "-H", "-o",
		"name,size,alloc,free,cap,health,frag")
	if err != nil {
		return zfsUnavailable(err)
	}

	pools := parseZpoolList(out)
	result := &ZFSBlock{Available: true, Pools: pools}

	// Error details for non-ONLINE pools
	for _, p := range pools {
		if p.Health != "ONLINE" {
			statusOut, err := zpoolCLI.run(ctx, "status", "-x")
			if err == nil {
				text := strings.TrimSpace(string(statusOut))
				result.Errors = &text
			}
			break
		}
	}

	if len(pools) > 0 {
		details := zpoolDetails(ctx)
		for i := range pools {
			pools[i].zpoolDetail = details[pools[i].Name]
		}
	}
	return result
}

// zfsUnavailable is the block for an installed zpool whose `zpool list` failed: error is timeout for
// a call the timeout killed, cli_failed otherwise; error_message names the exit status, never stderr
// or a path (as dockerUnavailable).
func zfsUnavailable(err error) *ZFSBlock {
	code, text := "cli_failed", "zpool list failed: "+commandFailure("zpool", pluginTimeout, err)
	if errors.Is(err, context.DeadlineExceeded) {
		code, text = "timeout", fmt.Sprintf("zpool list timed out after %s", pluginTimeout)
	}
	logger.Warnf("%s, zfs reported as unavailable (%s)", text, code)
	return &ZFSBlock{Error: &code, ErrorMessage: text, Pools: []ZPool{}}
}

// parseZpoolList parses `zpool list -H -o name,size,alloc,free,cap,health,frag` (tab-separated) into
// pool maps, skipping lines with too few columns and stripping the % from the capacity column — the
// positional parsing, testable without running zpool (6.16). fragmentation_percent is left out where
// zpool prints "-" (unknown, zpoolprops(7)) or something else than a percentage.
func parseZpoolList(out []byte) []ZPool {
	pools := []ZPool{}
	for _, line := range strings.Split(strings.TrimSpace(string(out)), "\n") {
		parts := strings.Split(line, "\t")
		if len(parts) < 6 {
			continue
		}
		capStr := strings.TrimRight(parts[4], "%")
		capPct, _ := strconv.Atoi(capStr)
		pool := ZPool{Name: parts[0], Size: parts[1], Allocated: parts[2], Free: parts[3], CapacityPercent: capPct,
			Health: parts[5]}
		if len(parts) > 6 {
			if frag, ok := zpoolPercent(parts[6]); ok {
				pool.FragmentationPercent = &frag
			}
		}
		pools = append(pools, pool)
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
func zpoolDetails(ctx context.Context) map[string]zpoolDetail {
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
func parseZpoolStatus(out []byte) map[string]zpoolDetail {
	var status zpoolStatus
	if err := json.Unmarshal(out, &status); err != nil {
		return nil
	}
	details := map[string]zpoolDetail{}
	for pool, st := range status.Pools {
		var detail zpoolDetail
		if scan := st.Scan; scan != nil && scan.Function == "SCRUB" && zpoolScanStates[scan.State] {
			detail.Scrub = &ZPoolScrub{State: scan.State, Errors: scan.Errors}
			if scan.State == "SCANNING" && scan.Pause > 0 {
				detail.Scrub.State = "PAUSED"
			}
			if scan.State != "SCANNING" {
				detail.Scrub.End = scan.EndTime
			}
		}
		for _, v := range st.Vdevs {
			if v.Read == 0 && v.Write == 0 && v.Checksum == 0 {
				continue
			}
			detail.VdevErrors = append(detail.VdevErrors,
				ZPoolVdevError{Name: labelText(v.Name), Read: v.Read, Write: v.Write, Checksum: v.Checksum})
		}
		slices.SortFunc(detail.VdevErrors, func(a, b ZPoolVdevError) int { return strings.Compare(a.Name, b.Name) })
		if len(detail.VdevErrors) > maxZpoolVdevErrors {
			detail.VdevErrors = detail.VdevErrors[:maxZpoolVdevErrors]
		}
		if detail.Scrub != nil || len(detail.VdevErrors) > 0 {
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
