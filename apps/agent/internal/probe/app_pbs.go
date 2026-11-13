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
	"math"
	"os/exec"
	"slices"
	"strings"
)

// pbsGet runs `proxmox-backup-debug api get <path> <args> --output-format json` and decodes the
// list it answers. proxmox-backup-debug (src/bin/proxmox_backup_debug/api.rs) asks the local API
// daemon over its loopback connection, as root without a ticket of its own; it only reads with get.
func pbsGet(ctx context.Context, path string, args ...string) ([]map[string]any, error) {
	call := append(append([]string{"api", "get", path}, args...), "--output-format", "json")
	out, err := runAppTool(ctx, "proxmox-backup-debug", call...)
	if err != nil {
		return nil, err
	}
	var items []map[string]any
	if err := json.Unmarshal(out, &items); err != nil {
		return nil, fmt.Errorf("proxmox-backup-debug: %s answered no list", path)
	}
	return items, nil
}

// pbsJobTypes are the task types of the jobs the view rates, by the prefix of their worker type:
// garbage_collection, verificationjob and verify…, syncjob, prune and prunejob (src/api2/node/tasks.rs).
var pbsJobTypes = []string{"garbage_collection", "verif", "sync", "prune"}

// pbsStatus reads the datastores of the local Proxmox Backup Server: how many, how many are in a
// maintenance mode, the fullest one in percent, the days until the first one is estimated full, and
// how many garbage collection, verify, sync and prune jobs failed their last run. No datastore, job
// or remote name leaves it.
//
// pbs-api-types datastore.rs: GET /config/datastore lists DataStoreConfig with maintenance-mode
// (a property string of type read-only, offline or delete) when one is set; GET
// /status/datastore-usage lists per store total and used in bytes and estimated-full-date, "the UNIX
// epoch when the storage will be full", each optional (what it holds without enough history, 0 or a
// negative value, is not checked against a live server; neither adds a date here).
// src/api2/node/tasks.rs, GET /nodes/localhost/tasks: the newest tasks with worker_type, worker_id,
// endtime and status; running ones are left out. A status "OK" is a run without fault, "WARNINGS: <n>" one with warnings; the
// strings come from proxmox-rest-server and are not checked against a live server.
func pbsStatus(ctx context.Context, _ Target) (map[string]any, error) {
	stores, err := pbsGet(ctx, "/config/datastore")
	if err != nil {
		return nil, err
	}
	maintenance := 0
	for _, store := range stores {
		if mode, _ := store["maintenance-mode"].(string); mode != "" {
			maintenance++
		}
	}
	usage, err := pbsGet(ctx, "/status/datastore-usage")
	if err != nil {
		return nil, err
	}
	maxUsed, minFull := -1.0, math.Inf(1)
	for _, item := range usage {
		total, okTotal := pveCount(item["total"])
		used, okUsed := pveCount(item["used"])
		if okTotal && okUsed && total > 0 {
			maxUsed = max(maxUsed, 100*used/total)
		}
		// An estimate in the past (the regression of a store that shrinks) or none at all (a store
		// without history) adds no date.
		if full, ok := pveCount(item["estimated-full-date"]); ok && full > float64(now().Unix()) {
			minFull = min(minFull, (full-float64(now().Unix()))/86400)
		}
	}
	// One call per job type, so the backup and reader tasks of a busy server cannot push the last
	// run of a job out of the window.
	var tasks []map[string]any
	for _, kind := range pbsJobTypes {
		some, err := pbsGet(ctx, "/nodes/localhost/tasks", "--typefilter", kind, "--limit", "50")
		if err != nil {
			return nil, err
		}
		tasks = append(tasks, some...)
	}
	values := map[string]any{
		"datastores": len(stores), "maintenance": maintenance, "tasks_failed": pbsFailedJobs(tasks),
	}
	if maxUsed >= 0 {
		values["max_used_pct"] = math.Round(maxUsed*10) / 10
	}
	if !math.IsInf(minFull, 1) {
		values["min_full_days"] = int(minFull)
	}
	return values, nil
}

// pbsFailedJobs counts the jobs whose newest finished task failed: a job is its worker type and
// worker id, so a later good run of the same job clears an earlier failure.
func pbsFailedJobs(tasks []map[string]any) int {
	type run struct {
		end    float64
		failed bool
	}
	newest := map[string]run{}
	for _, task := range tasks {
		kind, _ := task["worker_type"].(string)
		if !slices.ContainsFunc(pbsJobTypes, func(p string) bool { return strings.HasPrefix(kind, p) }) {
			continue
		}
		end, ok := pveCount(task["endtime"])
		status, isText := task["status"].(string)
		if !ok || !isText {
			continue
		}
		id, _ := task["worker_id"].(string)
		key := kind + "\x00" + id
		if r, seen := newest[key]; !seen || cmp.Compare(end, r.end) > 0 {
			newest[key] = run{end, status != "OK" && !strings.HasPrefix(status, "WARNINGS")}
		}
	}
	failed := 0
	for _, r := range newest {
		if r.failed {
			failed++
		}
	}
	return failed
}

// cephHealth reads the health of the Ceph cluster this host belongs to, as the admin keyring of root
// lets it: the overall status, the number of health checks raised, the fullest pool and the raw use
// of the cluster in percent. No pool, OSD or host name leaves it.
//
// src/mon/HealthMonitor.cc get_health_status: `ceph health -f json` writes status (HEALTH_OK,
// HEALTH_WARN or HEALTH_ERR) and checks, an object keyed by check code. src/mon/PGMap.cc: `ceph df
// -f json` writes stats.total_used_raw_ratio and per pool stats.percent_used, both fractions 0..1
// (the text table multiplies them by 100). The JSON forms are read from the source, not checked
// against a live cluster; a report of another form is an error, never a made-up health.
func cephHealth(ctx context.Context, _ Target) (map[string]any, error) {
	out, err := runAppTool(ctx, "ceph", "health", "-f", "json")
	if err != nil {
		return nil, err
	}
	var health struct {
		Status string                     `json:"status"`
		Checks map[string]json.RawMessage `json:"checks"`
	}
	if err := json.Unmarshal(out, &health); err != nil || !strings.HasPrefix(health.Status, "HEALTH_") {
		return nil, errors.New("ceph health: a report of another form")
	}
	out, err = runAppTool(ctx, "ceph", "df", "-f", "json")
	if err != nil {
		return nil, err
	}
	var df struct {
		Stats struct {
			RawRatio *float64 `json:"total_used_raw_ratio"`
		} `json:"stats"`
		Pools []struct {
			Stats struct {
				PercentUsed *float64 `json:"percent_used"`
			} `json:"stats"`
		} `json:"pools"`
	}
	if err := json.Unmarshal(out, &df); err != nil || df.Stats.RawRatio == nil || !cephFraction(*df.Stats.RawRatio) {
		return nil, errors.New("ceph df: a report of another form")
	}
	values := map[string]any{
		"health": health.Status, "checks": len(health.Checks),
		"raw_used_pct": math.Round(*df.Stats.RawRatio*1000) / 10,
	}
	maxPool := -1.0
	for _, pool := range df.Pools {
		if p := pool.Stats.PercentUsed; p != nil {
			if !cephFraction(*p) {
				return nil, errors.New("ceph df: a pool use of another form")
			}
			maxPool = max(maxPool, *p)
		}
	}
	if maxPool >= 0 {
		values["max_pool_used_pct"] = math.Round(maxPool*1000) / 10
	}
	return values, nil
}

func cephFraction(v float64) bool { return !math.IsNaN(v) && v >= 0 && v <= 1 }

// zfsSnapshots reads whether the snapshots sanoid keeps are fresh, as `sanoid --monitor-snapshots`
// rates them against the warn and crit ages of sanoid.conf: ok, warning or critical. The line it
// prints names datasets and stays on the host; only its exit status is read.
//
// sanoid (sub monitor_snapshots): exit 0 OK, 1 WARN, 2 CRIT. It reads its snapshot cache and, when
// that is older than five hours, lists the snapshots anew with `zfs get -Hrpt snapshot creation`
// and rewrites the cache; it takes, prunes and changes no snapshot. Whether it waits on the lock of
// a running `sanoid --cron` is not checked; the tool timeout bounds the call either way.
func zfsSnapshots(ctx context.Context, _ Target) (map[string]any, error) {
	_, err := runTool(ctx, toolTimeout, "sanoid", "--monitor-snapshots")
	var exitErr *exec.ExitError
	switch {
	case err == nil:
		return map[string]any{"status": "ok"}, nil
	case errors.Is(err, exec.ErrNotFound):
		return nil, fmt.Errorf("%w: sanoid is not installed", ErrUnsupported)
	case errors.As(err, &exitErr) && exitErr.ExitCode() == 1:
		return map[string]any{"status": "warning"}, nil
	case errors.As(err, &exitErr) && exitErr.ExitCode() == 2:
		return map[string]any{"status": "critical"}, nil
	}
	return nil, toolError("sanoid", err)
}
