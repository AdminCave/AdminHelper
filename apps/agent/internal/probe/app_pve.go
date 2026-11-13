// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"cmp"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"slices"
	"strings"
)

// hostName is the seam to the host's name, the node name pvesh is asked about.
var hostName = os.Hostname

// pveNode is the name of this host as a Proxmox VE node: the host name without its domain, as
// pvesh names nodes (the same as monitor.collectProxmox). pvesh does not take "localhost" for a
// node in every handler (pve-manager PVE/CLI/pvesh.pm only uses it to skip the proxy), so the
// view asks with the real name; it stays on the host, the allowlist class node checks its form.
func pveNode() (string, error) {
	host, err := hostName()
	if err != nil {
		return "", fmt.Errorf("pvesh: the host name is unreadable: %w", err)
	}
	node, _, _ := strings.Cut(host, ".")
	return node, nil
}

// pveGet runs `pvesh get <path> <args> --output-format json` and decodes the list it answers.
func pveGet(ctx context.Context, path string, args ...string) ([]map[string]any, error) {
	call := append(append([]string{"get", path}, args...), "--output-format", "json")
	out, err := runAppTool(ctx, "pvesh", call...)
	if err != nil {
		return nil, err
	}
	var items []map[string]any
	if err := json.Unmarshal(out, &items); err != nil {
		return nil, fmt.Errorf("pvesh: %s answered no list", path)
	}
	return items, nil
}

// pveFlag reads a boolean of the PVE API, which pvesh prints as true/false or as 1/0.
func pveFlag(v any) (flag, ok bool) {
	switch x := v.(type) {
	case bool:
		return x, true
	case float64:
		return x != 0, true
	case string:
		switch x {
		case "1":
			return true, true
		case "0":
			return false, true
		}
	}
	return false, false
}

// pveCount reads a non-negative count or epoch of the PVE API.
func pveCount(v any) (float64, bool) {
	x, ok := v.(float64)
	return x, ok && x >= 0
}

// pveCluster reads the state of the cluster this node belongs to: whether it is quorate, how many
// nodes are offline, how many HA services are in error, and how many replication jobs of this node
// failed their last run. No node, guest or job name leaves it.
//
// pve-manager PVE/API2/Cluster.pm, GET /cluster/status: one entry of type "cluster" with quorate,
// one of type "node" per member with online; a node outside a cluster has no cluster entry and is
// quorate on its own. pve-ha-manager src/PVE/API2/HA/Status.pm, GET /cluster/ha/status/current:
// entries of type "service" carry the raw CRM state in crm_state. pve-manager PVE/API2/Replication.pm,
// GET /nodes/{node}/replication: per job fail_count, the failed runs in a row. GET /cluster/replication
// is the job configuration only, without a state, so the view does not ask it.
func pveCluster(ctx context.Context, _ Target) (map[string]any, error) {
	node, err := pveNode()
	if err != nil {
		return nil, err
	}
	status, err := pveGet(ctx, "/cluster/status")
	if err != nil {
		return nil, err
	}
	quorate, offline := true, 0
	for _, item := range status {
		switch item["type"] {
		case "cluster":
			q, ok := pveFlag(item["quorate"])
			if !ok {
				return nil, errors.New("pvesh: /cluster/status quorate of another form")
			}
			quorate = q
		case "node":
			if online, ok := pveFlag(item["online"]); ok && !online {
				offline++
			}
		}
	}
	ha, err := pveGet(ctx, "/cluster/ha/status/current")
	if err != nil {
		return nil, err
	}
	haError := 0
	for _, item := range ha {
		// The CRM states of a service the HA manager could not keep running (ha-manager(1),
		// "Service States"): error, and fence and recovery while its node is fenced.
		if item["type"] == "service" && slices.Contains([]any{"error", "fence", "recovery"}, item["crm_state"]) {
			haError++
		}
	}
	jobs, err := pveGet(ctx, "/nodes/"+node+"/replication")
	if err != nil {
		return nil, err
	}
	failed := 0
	for _, job := range jobs {
		if n, ok := pveCount(job["fail_count"]); ok && n > 0 {
			failed++
		}
	}
	return map[string]any{
		"quorate": quorate, "nodes_offline": offline, "ha_error": haError, "replication_failed": failed,
	}, nil
}

// pveJobs reads the backup jobs of the cluster and the last vzdump runs of this node: how many jobs
// are enabled, how long ago the last run ended, and how many runs failed in a row since the last
// one that did not. Only states and times are read, no guest, storage or job name.
//
// pve-manager: GET /cluster/backup lists the jobs, enabled absent meaning enabled (as
// monitor.backupJobs reads it). PVE/API2/Tasks.pm, GET /nodes/{node}/tasks: the finished tasks of
// the task archive with endtime and status, the status "OK" for a run without fault and
// "WARNINGS: <n>" for one with warnings (pve-common upid_read_status, not checked against a live
// node); running tasks are not in the archive.
func pveJobs(ctx context.Context, _ Target) (map[string]any, error) {
	node, err := pveNode()
	if err != nil {
		return nil, err
	}
	backup, err := pveGet(ctx, "/cluster/backup")
	if err != nil {
		return nil, err
	}
	enabled := 0
	for _, job := range backup {
		if on, ok := pveFlag(job["enabled"]); !ok || on {
			enabled++
		}
	}
	tasks, err := pveGet(ctx, "/nodes/"+node+"/tasks", "--typefilter", "vzdump", "--limit", "50")
	if err != nil {
		return nil, err
	}
	type run struct {
		end    float64
		failed bool
	}
	var runs []run
	for _, task := range tasks {
		end, ok := pveCount(task["endtime"])
		status, isText := task["status"].(string)
		if !ok || !isText {
			continue
		}
		runs = append(runs, run{end, status != "OK" && !strings.HasPrefix(status, "WARNINGS")})
	}
	slices.SortFunc(runs, func(a, b run) int { return cmp.Compare(b.end, a.end) })
	failed := 0
	for _, r := range runs {
		if !r.failed {
			break
		}
		failed++
	}
	values := map[string]any{"jobs": enabled, "jobs_failed": failed}
	// Without a run there is no age; a made-up one would fire a rule on it.
	if len(runs) > 0 {
		values["last_run_age_s"] = max(0, int(float64(now().Unix())-runs[0].end))
	}
	return values, nil
}

// pveUpdates reads how many package updates this node has and whether its subscription is active.
//
// pve-manager PVE/API2/APT.pm, GET /nodes/{node}/apt/update: the list of upgradable packages from
// the local apt cache; GET never runs apt-get update (that is POST), at most it lists the cache anew.
// PVE/API2/Subscription.pm, GET /nodes/{node}/subscription: status one of new, notfound, active,
// invalid, expired, suspended; of the answer only status is read, never the key or server id.
func pveUpdates(ctx context.Context, _ Target) (map[string]any, error) {
	node, err := pveNode()
	if err != nil {
		return nil, err
	}
	updates, err := pveGet(ctx, "/nodes/"+node+"/apt/update")
	if err != nil {
		return nil, err
	}
	out, err := runAppTool(ctx, "pvesh", "get", "/nodes/"+node+"/subscription", "--output-format", "json")
	if err != nil {
		return nil, err
	}
	var sub struct {
		Status string `json:"status"`
	}
	if err := json.Unmarshal(out, &sub); err != nil || sub.Status == "" {
		return nil, errors.New("pvesh: /subscription answered no status")
	}
	return map[string]any{
		"updates": len(updates), "subscription_active": strings.EqualFold(sub.Status, "active"),
	}, nil
}
