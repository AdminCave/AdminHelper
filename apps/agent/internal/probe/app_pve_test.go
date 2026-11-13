// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"os/exec"
	"reflect"
	"testing"
	"time"
)

// stubNode makes pve1.example.org the host's name.
func stubNode(t *testing.T) {
	t.Helper()
	old := hostName
	hostName = func() (string, error) { return "pve1.example.org", nil }
	t.Cleanup(func() { hostName = old })
}

func pveCall(path string, args ...string) []string {
	return append(append([]string{"pvesh", "get", path}, args...), "--output-format", "json")
}

func TestPVEClusterCountsOfflineNodesHAErrorsAndFailedReplication(t *testing.T) {
	stubNode(t)
	calls := stubTools(t,
		// pvesh prints the booleans as 1/0 or as true/false; both are read.
		answer{out: `[{"type":"cluster","name":"lab","quorate":1,"nodes":3},
			{"type":"node","name":"pve1","online":1,"local":1},
			{"type":"node","name":"pve2","online":0},
			{"type":"node","name":"pve3","online":true}]`},
		answer{out: `[{"type":"quorum","id":"quorum","status":"OK","quorate":1},
			{"type":"service","sid":"vm:100","crm_state":"started","state":"started"},
			{"type":"service","sid":"vm:101","crm_state":"error","state":"error"},
			{"type":"service","sid":"ct:102","crm_state":"fence","state":"fence"},
			{"type":"service","sid":"ct:103","crm_state":"recovery","state":"recovery"},
			{"type":"lrm","id":"lrm:pve2","status":"pve2 (old timestamp - dead?)"}]`},
		answer{out: `[{"id":"100-0","guest":100,"fail_count":0,"last_sync":1700000000},
			{"id":"101-0","guest":101,"fail_count":3,"error":"no space left"},
			{"id":"102-0","guest":102}]`},
	)
	got, err := pveCluster(context.Background(), Target{Kind: kindUnit, Name: "pve-cluster.service"})
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]any{"quorate": true, "nodes_offline": 1, "ha_error": 3, "replication_failed": 1}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("pve_cluster %v, want %v", got, want)
	}
	wantCalls := [][]string{
		pveCall("/cluster/status"), pveCall("/cluster/ha/status/current"), pveCall("/nodes/pve1/replication"),
	}
	if !reflect.DeepEqual(*calls, wantCalls) {
		t.Errorf("calls %q, want %q", *calls, wantCalls)
	}
}

func TestPVEClusterReadsALostQuorumAndANodeOutsideACluster(t *testing.T) {
	stubNode(t)
	stubTools(t, answer{out: `[{"type":"cluster","quorate":false},{"type":"node","online":1}]`},
		answer{out: `[]`}, answer{out: `[]`})
	got, err := pveCluster(context.Background(), Target{})
	if err != nil {
		t.Fatal(err)
	}
	if got["quorate"] != false {
		t.Errorf("pve_cluster %v, want quorate false", got)
	}
	// A node outside a cluster: no cluster entry, quorate on its own.
	stubTools(t, answer{out: `[{"type":"node","name":"pve1","online":1,"nodeid":0}]`},
		answer{out: `[{"type":"quorum","status":"OK","quorate":1}]`}, answer{out: `[]`})
	got, err = pveCluster(context.Background(), Target{})
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]any{"quorate": true, "nodes_offline": 0, "ha_error": 0, "replication_failed": 0}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("pve_cluster %v, want %v", got, want)
	}
}

func TestPVEJobsReadsEnabledJobsTheLastRunAndFailuresInARow(t *testing.T) {
	stubNode(t)
	old := now
	now = func() time.Time { return time.Unix(1_700_010_000, 0) }
	t.Cleanup(func() { now = old })
	calls := stubTools(t,
		answer{out: `[{"id":"backup-a","schedule":"21:00"},{"id":"backup-b","enabled":0},
			{"id":"backup-c","enabled":"1"},{"id":"backup-d","enabled":false}]`},
		// Out of order on purpose: the newest two failed, the one before them had warnings.
		answer{out: `[{"type":"vzdump","status":"WARNINGS: 2","starttime":1699990000,"endtime":1699990600},
			{"type":"vzdump","status":"job errors","starttime":1700006000,"endtime":1700006400},
			{"type":"vzdump","status":"OK","starttime":1699900000,"endtime":1699900500},
			{"type":"vzdump","status":"unexpected status","starttime":1700000000,"endtime":1700000300}]`},
	)
	got, err := pveJobs(context.Background(), Target{})
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]any{"jobs": 2, "jobs_failed": 2, "last_run_age_s": 3600}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("pve_jobs %v, want %v", got, want)
	}
	wantCalls := [][]string{
		pveCall("/cluster/backup"), pveCall("/nodes/pve1/tasks", "--typefilter", "vzdump", "--limit", "50"),
	}
	if !reflect.DeepEqual(*calls, wantCalls) {
		t.Errorf("calls %q, want %q", *calls, wantCalls)
	}
}

func TestPVEJobsWithoutARunHasNoAge(t *testing.T) {
	stubNode(t)
	stubTools(t, answer{out: `[]`}, answer{out: `[]`})
	got, err := pveJobs(context.Background(), Target{})
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]any{"jobs": 0, "jobs_failed": 0}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("pve_jobs %v, want %v without last_run_age_s", got, want)
	}
}

func TestPVEUpdatesCountsPackagesAndReadsTheSubscription(t *testing.T) {
	stubNode(t)
	for status, active := range map[string]bool{"active": true, "Active": true, "notfound": false, "expired": false} {
		calls := stubTools(t,
			answer{out: `[{"Package":"pve-manager","Version":"9.1.2"},{"Package":"libc6","Version":"2.41-12"}]`},
			answer{out: `{"status":"` + status + `","key":"pve1c-0000","serverid":"ABCD"}`},
		)
		got, err := pveUpdates(context.Background(), Target{})
		if err != nil {
			t.Fatal(err)
		}
		want := map[string]any{"updates": 2, "subscription_active": active}
		if !reflect.DeepEqual(got, want) {
			t.Errorf("subscription %s: pve_updates %v, want %v", status, got, want)
		}
		wantCalls := [][]string{pveCall("/nodes/pve1/apt/update"), pveCall("/nodes/pve1/subscription")}
		if !reflect.DeepEqual(*calls, wantCalls) {
			t.Errorf("calls %q, want %q", *calls, wantCalls)
		}
	}
}

func TestThePVEViewsFailWhatTheyCannotRead(t *testing.T) {
	stubNode(t)
	views := map[string]func(context.Context, Target) (map[string]any, error){
		"pve_cluster": pveCluster, "pve_jobs": pveJobs, "pve_updates": pveUpdates,
	}
	for name, read := range views {
		t.Run(name+" pvesh fails", func(t *testing.T) {
			stubTools(t, answer{err: &exec.ExitError{Stderr: []byte("ipcc_send_rec[1] failed: Connection refused\n")}})
			if _, err := read(context.Background(), Target{}); err == nil {
				t.Error("no error")
			}
		})
		t.Run(name+" no list", func(t *testing.T) {
			stubTools(t, answer{out: `{"data":null}`})
			if _, err := read(context.Background(), Target{}); err == nil {
				t.Error("no error")
			}
		})
		t.Run(name+" not installed", func(t *testing.T) {
			stubTools(t, answer{err: notInstalled("pvesh")})
			if _, err := read(context.Background(), Target{}); !errors.Is(err, ErrUnsupported) {
				t.Errorf("error %v, want ErrUnsupported", err)
			}
		})
	}
	stubTools(t, answer{out: `[{"type":"cluster","quorate":"yes"}]`})
	if _, err := pveCluster(context.Background(), Target{}); err == nil {
		t.Error("a quorate of another form: no error")
	}
	stubTools(t, answer{out: `[]`}, answer{out: `{"message":"no access"}`})
	if _, err := pveUpdates(context.Background(), Target{}); err == nil {
		t.Error("a subscription without status: no error")
	}
	hostName = func() (string, error) { return "", errors.New("no name") }
	stubTools(t)
	if _, err := pveCluster(context.Background(), Target{}); err == nil {
		t.Error("no host name: no error")
	}
}

func TestThePVEViewsAreViewsOfUnits(t *testing.T) {
	for _, view := range []string{"pve_cluster", "pve_jobs", "pve_updates"} {
		if v, ok := appViews[view]; !ok || !unitView(v) {
			t.Errorf("view %s: %v, want a view of a unit", view, v)
		}
	}
}
