// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"reflect"
	"testing"
	"time"
)

func pbsCall(path string, args ...string) []string {
	return append(append([]string{"proxmox-backup-debug", "api", "get", path}, args...), "--output-format", "json")
}

func TestPBSStatusReadsStoresUseEstimatesAndTheLastRunOfEachJob(t *testing.T) {
	old := now
	now = func() time.Time { return time.Unix(1_700_000_000, 0) }
	t.Cleanup(func() { now = old })
	calls := stubTools(t,
		answer{out: `[{"name":"store1","path":"/mnt/a"},
			{"name":"store2","path":"/mnt/b","maintenance-mode":"type=read-only,message=move"}]`},
		answer{out: `[{"store":"store1","total":1000,"used":500,"avail":500,"estimated-full-date":1703456000},
			{"store":"store2","total":1700,"used":1400,"avail":300,"estimated-full-date":1700907200},
			{"store":"store3","total":0,"used":0,"estimated-full-date":0},
			{"store":"store5","estimated-full-date":1699000000},
			{"store":"store4","error":"no such datastore"}]`},
		// One answer per job type; the newest run of each job decides.
		answer{out: `[{"worker_type":"garbage_collection","worker_id":"store1","endtime":1699990000,"status":"OK"},
			{"worker_type":"garbage_collection","worker_id":"store1","endtime":1699900000,"status":"TASK ERROR: out of space"}]`},
		answer{out: `[{"worker_type":"verificationjob","worker_id":"store2:v-1","endtime":1699980000,"status":"verification failed - please check the log"}]`},
		answer{out: `[{"worker_type":"syncjob","worker_id":"remote:store1:store2:s-1","endtime":1699970000,"status":"WARNINGS: 1"}]`},
		answer{out: `[{"worker_type":"prunejob","worker_id":"store1:p-1","endtime":1699960000,"status":"OK"},
			{"worker_type":"prunejob","worker_id":"store2:p-2","starttime":1699999000}]`},
	)
	got, err := pbsStatus(context.Background(), Target{Kind: kindUnit, Name: "proxmox-backup.service"})
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]any{
		"datastores": 2, "maintenance": 1, "max_used_pct": 82.4, "min_full_days": 10, "tasks_failed": 1,
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("pbs_status %v, want %v", got, want)
	}
	wantCalls := [][]string{
		pbsCall("/config/datastore"), pbsCall("/status/datastore-usage"),
		pbsCall("/nodes/localhost/tasks", "--typefilter", "garbage_collection", "--limit", "50"),
		pbsCall("/nodes/localhost/tasks", "--typefilter", "verif", "--limit", "50"),
		pbsCall("/nodes/localhost/tasks", "--typefilter", "sync", "--limit", "50"),
		pbsCall("/nodes/localhost/tasks", "--typefilter", "prune", "--limit", "50"),
	}
	if !reflect.DeepEqual(*calls, wantCalls) {
		t.Errorf("calls %q, want %q", *calls, wantCalls)
	}
}

func TestPBSStatusWithoutUseOrEstimateHasNeither(t *testing.T) {
	// A store shrinking since its last run has an estimate in the past: no date, not zero days.
	stubTools(t, answer{out: `[]`}, answer{out: `[{"store":"s","estimated-full-date":-1},{"store":"t","estimated-full-date":1}]`},
		answer{out: `[]`}, answer{out: `[]`}, answer{out: `[]`}, answer{out: `[]`})
	got, err := pbsStatus(context.Background(), Target{})
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]any{"datastores": 0, "maintenance": 0, "tasks_failed": 0}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("pbs_status %v, want %v without max_used_pct and min_full_days", got, want)
	}
}

func TestPBSFailedJobsTakesTheNewestRunOfEachJob(t *testing.T) {
	tasks := []map[string]any{
		// Out of order on purpose: the newer run of the same job failed.
		{"worker_type": "verify", "worker_id": "store1", "endtime": 100.0, "status": "OK"},
		{"worker_type": "verify", "worker_id": "store1", "endtime": 200.0, "status": "verification failed"},
		{"worker_type": "verify", "worker_id": "store2", "endtime": 300.0, "status": "OK"},
		{"worker_type": "sync", "worker_id": "store1", "endtime": 50.0, "status": "unexpected status"},
		{"worker_type": "prune", "worker_id": "store1", "endtime": 60.0, "status": "WARNINGS: 3"},
	}
	if got := pbsFailedJobs(tasks); got != 2 {
		t.Errorf("failed jobs %d, want 2", got)
	}
}

func TestCephHealthReadsStatusChecksAndUse(t *testing.T) {
	calls := stubTools(t,
		answer{out: `{"status":"HEALTH_WARN","checks":{"OSD_NEARFULL":{"severity":"HEALTH_WARN"},
			"POOL_NO_REDUNDANCY":{"severity":"HEALTH_WARN"}},"mutes":[]}`},
		answer{out: `{"stats":{"total_bytes":1000,"total_used_raw_bytes":432,"total_used_raw_ratio":0.4321},
			"pools":[{"name":"rbd","id":1,"stats":{"percent_used":0.1}},
				{"name":"cephfs_data","id":2,"stats":{"percent_used":0.756}},{"name":"x","id":3,"stats":{}}]}`},
	)
	got, err := cephHealth(context.Background(), Target{Kind: kindUnit, Name: "ceph-mon@pve1.service"})
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]any{"health": "HEALTH_WARN", "checks": 2, "raw_used_pct": 43.2, "max_pool_used_pct": 75.6}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("ceph_health %v, want %v", got, want)
	}
	wantCalls := [][]string{{"ceph", "health", "-f", "json"}, {"ceph", "df", "-f", "json"}}
	if !reflect.DeepEqual(*calls, wantCalls) {
		t.Errorf("calls %q, want %q", *calls, wantCalls)
	}
}

func TestCephHealthWithoutPoolsHasNoPoolUse(t *testing.T) {
	stubTools(t, answer{out: `{"status":"HEALTH_OK","checks":{}}`},
		answer{out: `{"stats":{"total_used_raw_ratio":0},"pools":[]}`})
	got, err := cephHealth(context.Background(), Target{})
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]any{"health": "HEALTH_OK", "checks": 0, "raw_used_pct": 0.0}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("ceph_health %v, want %v without max_pool_used_pct", got, want)
	}
}

func TestThePBSAndCephViewsFailWhatTheyCannotRead(t *testing.T) {
	cases := map[string]struct {
		read    func(context.Context, Target) (map[string]any, error)
		answers []answer
	}{
		"pbs no list":            {pbsStatus, []answer{{out: `{"data":[]}`}}},
		"pbs api down":           {pbsStatus, []answer{{err: toolExit(t, 255, "Error: connection refused\n")}}},
		"pbs tasks no list":      {pbsStatus, []answer{{out: `[]`}, {out: `[]`}, {out: `null x`}}},
		"ceph status other form": {cephHealth, []answer{{out: `{"health":{"status":"HEALTH_OK"}}`}}},
		"ceph no json":           {cephHealth, []answer{{out: `HEALTH_OK`}}},
		"ceph df no ratio":       {cephHealth, []answer{{out: `{"status":"HEALTH_OK"}`}, {out: `{"stats":{}}`}}},
		"ceph df ratio above 1":  {cephHealth, []answer{{out: `{"status":"HEALTH_OK"}`}, {out: `{"stats":{"total_used_raw_ratio":43.2}}`}}},
		"ceph pool above 1": {cephHealth, []answer{{out: `{"status":"HEALTH_OK"}`},
			{out: `{"stats":{"total_used_raw_ratio":0.4},"pools":[{"stats":{"percent_used":75.6}}]}`}}},
		"ceph mon down": {cephHealth, []answer{{err: toolExit(t, 1, "timed out\n")}}},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			stubTools(t, c.answers...)
			if _, err := c.read(context.Background(), Target{}); err == nil {
				t.Error("no error")
			}
		})
	}
	for tool, read := range map[string]func(context.Context, Target) (map[string]any, error){
		"proxmox-backup-debug": pbsStatus, "ceph": cephHealth, "sanoid": zfsSnapshots,
	} {
		stubTools(t, answer{err: notInstalled(tool)})
		if _, err := read(context.Background(), Target{}); !errors.Is(err, ErrUnsupported) {
			t.Errorf("%s not installed: error %v, want ErrUnsupported", tool, err)
		}
	}
}

func TestZFSSnapshotsReadsTheExitStatusOfSanoid(t *testing.T) {
	for code, want := range map[int]string{1: "warning", 2: "critical"} {
		stubTools(t, answer{out: "CRIT: tank/vm-100-disk-0 newest hourly snapshot is 3h old\n", err: toolExit(t, code, "")})
		got, err := zfsSnapshots(context.Background(), Target{})
		if err != nil {
			t.Fatal(err)
		}
		if !reflect.DeepEqual(got, map[string]any{"status": want}) {
			t.Errorf("exit %d: zfs_snapshots %v, want status %s", code, got, want)
		}
	}
	calls := stubTools(t, answer{out: "OK: all monitored datasets are fresh\n"})
	got, err := zfsSnapshots(context.Background(), Target{Kind: kindUnit, Name: "sanoid.timer"})
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(got, map[string]any{"status": "ok"}) {
		t.Errorf("zfs_snapshots %v, want status ok", got)
	}
	if !reflect.DeepEqual(*calls, [][]string{{"sanoid", "--monitor-snapshots"}}) {
		t.Errorf("calls %q", *calls)
	}
	// Any other status is no rating of sanoid's: an error, never a made-up state.
	stubTools(t, answer{err: toolExit(t, 3, "UNKNOWN\n")})
	if _, err := zfsSnapshots(context.Background(), Target{}); err == nil {
		t.Error("exit 3: no error")
	}
}

func TestThePBSCephAndSanoidViewsAreViewsOfUnits(t *testing.T) {
	for _, view := range []string{"pbs_status", "ceph_health", "zfs_snapshots"} {
		if v, ok := appViews[view]; !ok || !unitView(v) {
			t.Errorf("view %s: %v, want a view of a unit", view, v)
		}
	}
}
