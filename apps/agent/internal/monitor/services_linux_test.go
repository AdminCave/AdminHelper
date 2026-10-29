// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package monitor

import (
	"context"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"syscall"
	"testing"
	"time"
)

func TestParseWatchedServices(t *testing.T) {
	// 5.7: parse the batched `systemctl show` output. Keyed by Id so it's independent of block order
	// (the requested names below are in a different order than the blocks), matching a bare name
	// against its .service Id, and marking a name with no block as not-running.
	out := []byte("Id=nginx.service\nActiveState=active\nMainPID=1234\n\n" +
		"Id=sshd.service\nActiveState=inactive\nMainPID=0\n\n" +
		"Id=postgres.service\nActiveState=active\nMainPID=9999\n\n" +
		"Id=redis.service\nActiveState=active\nMainPID=5678")
	got := parseWatchedServices(out, []string{"redis", "missing", "nginx", "sshd.service", "postgres.service"})

	if len(got) != 5 {
		t.Fatalf("want 5 entries, got %d", len(got))
	}
	// redis (bare name matched to redis.service): active, pid 5678
	if got[0]["running"] != true || got[0]["pid"] != "5678" {
		t.Errorf("redis: want running=true pid=5678, got %v", got[0])
	}
	// missing: no block -> not running, no pid
	if got[1]["running"] != false || got[1]["pid"] != nil {
		t.Errorf("missing: want running=false pid=nil, got %v", got[1])
	}
	// nginx (bare name matched to nginx.service): active, pid 1234
	if got[2]["running"] != true || got[2]["pid"] != "1234" {
		t.Errorf("nginx: want running=true pid=1234, got %v", got[2])
	}
	// sshd.service: inactive -> not running (MainPID 0 ignored)
	if got[3]["running"] != false || got[3]["pid"] != nil {
		t.Errorf("sshd: want running=false pid=nil, got %v", got[3])
	}
	// postgres.service: direct .service Id match, active -> running, pid 9999
	if got[4]["running"] != true || got[4]["pid"] != "9999" {
		t.Errorf("postgres: want running=true pid=9999, got %v", got[4])
	}
}

func TestParseSystemctlColumnsOutput(t *testing.T) {
	// list-units: UNIT LOAD ACTIVE SUB ... -> col 2 = ACTIVE.
	units := parseSystemctlColumnsOutput(
		"nginx.service loaded active running\nredis.service loaded inactive dead\n", 2)
	if units["nginx.service"] != "active" || units["redis.service"] != "inactive" {
		t.Errorf("list-units col 2: %v", units)
	}
	// list-unit-files: UNIT STATE -> col 1 = STATE.
	files := parseSystemctlColumnsOutput("nginx.service enabled\nredis.service disabled\n", 1)
	if files["nginx.service"] != "enabled" || files["redis.service"] != "disabled" {
		t.Errorf("list-unit-files col 1: %v", files)
	}
	// A line too short to hold the column is skipped, not indexed out of range.
	if short := parseSystemctlColumnsOutput("only-one-field\n", 2); len(short) != 0 {
		t.Errorf("short line should be skipped: %v", short)
	}
}

func TestAssembleServiceHealthEnabledInactive(t *testing.T) {
	got := assembleServiceHealth(
		map[string]string{"a.service": "inactive", "b.service": "active"},
		map[string]string{"a.service": "enabled", "b.service": "enabled"},
		[]string{"c.service"},
	)
	// enabled_inactive: only a (inactive AND enabled); b is active, so excluded.
	if !reflect.DeepEqual(got["enabled_inactive"], []string{"a.service"}) {
		t.Errorf("enabled_inactive = %v, want [a.service]", got["enabled_inactive"])
	}
	if !reflect.DeepEqual(got["failed"], []string{"c.service"}) {
		t.Errorf("failed = %v, want [c.service]", got["failed"])
	}
	if all := got["all_services"].([]ServiceEntry); len(all) != 2 {
		t.Errorf("all_services should be the union (2 entries): %v", all)
	}
}

func TestAssembleServiceHealthUnknownFallback(t *testing.T) {
	// A unit present in only one map gets "unknown" for the missing side.
	got := assembleServiceHealth(
		map[string]string{"only-active.service": "active"},
		map[string]string{"only-enabled.service": "enabled"},
		nil,
	)
	byUnit := map[string]ServiceEntry{}
	for _, e := range got["all_services"].([]ServiceEntry) {
		byUnit[e["unit"]] = e
	}
	if byUnit["only-active.service"]["enabled_state"] != "unknown" {
		t.Errorf("only-active enabled_state = %q, want unknown", byUnit["only-active.service"]["enabled_state"])
	}
	if byUnit["only-enabled.service"]["active_state"] != "unknown" {
		t.Errorf("only-enabled active_state = %q, want unknown", byUnit["only-enabled.service"]["active_state"])
	}
	// nil failed normalizes to an empty slice, not null.
	if !reflect.DeepEqual(got["failed"], []string{}) {
		t.Errorf("failed = %v, want []", got["failed"])
	}
}

// showBlocks257 is real `systemctl show -p Id,Names,Type,Result,ConditionResult,TriggeredBy,
// ConditionTimestampMonotonic` output of systemd 257 (Debian 13) for units list-units reports as
// enabled yet inactive, in that order: e2scrub_reap and grub-common (oneshot, finished),
// systemd-pstore and sshd-keygen (oneshot, condition failed), smartmontools (no oneshot, condition
// failed; alias smartd), anacron (started by its timer), cron (a long-running service someone
// stopped). systemd tried to start every one of them (ConditionTimestampMonotonic != 0).
const showBlocks257 = `Type=oneshot
Result=success
Id=e2scrub_reap.service
Names=e2scrub_reap.service
TriggeredBy=
ConditionResult=yes
ConditionTimestampMonotonic=30030294

Type=oneshot
Result=success
Id=grub-common.service
Names=grub-common.service
TriggeredBy=
ConditionResult=yes
ConditionTimestampMonotonic=30066583

Type=oneshot
Result=success
Id=systemd-pstore.service
Names=systemd-pstore.service
TriggeredBy=
ConditionResult=no
ConditionTimestampMonotonic=25034754

Type=oneshot
Result=success
Id=sshd-keygen.service
Names=sshd-keygen.service
TriggeredBy=
ConditionResult=no
ConditionTimestampMonotonic=30084653

Type=notify
Result=success
Id=smartmontools.service
Names=smartmontools.service smartd.service
TriggeredBy=
ConditionResult=no
ConditionTimestampMonotonic=30084589

Type=simple
Result=success
Id=anacron.service
Names=anacron.service
TriggeredBy=anacron.timer
ConditionResult=yes
ConditionTimestampMonotonic=2004888271709

Type=simple
Result=success
Id=cron.service
Names=cron.service
TriggeredBy=
ConditionResult=yes
ConditionTimestampMonotonic=30011355
`

// neverStartedBlocks257 is real systemd 257 output for loaded units systemd never tried to start
// (ConditionTimestampMonotonic=0): Result=success and ConditionResult=no are mere defaults here,
// as for an enabled service whose start job failed on a dependency.
const neverStartedBlocks257 = `Type=oneshot
Result=success
Id=alsa-restore.service
Names=alsa-restore.service
TriggeredBy=
ConditionResult=no
ConditionTimestampMonotonic=0

Type=simple
Result=success
Id=alsa-state.service
Names=alsa-state.service
TriggeredBy=
ConditionResult=no
ConditionTimestampMonotonic=0
`

// showBlockFor returns the real block of unit from showBlocks257 (empty if absent).
func showBlockFor(unit string) []byte {
	for _, block := range strings.Split(showBlocks257, "\n\n") {
		if strings.Contains(block, "Id="+unit+"\n") {
			return []byte(block + "\n")
		}
	}
	return nil
}

// stubSystemctl is stubShow for the enabled-inactive re-check.
func stubSystemctl(t *testing.T, fn func(units []string) ([]byte, error)) *[][]string {
	t.Helper()
	return stubShow(t, "Id,Names,Type,Result,ConditionResult,TriggeredBy,ConditionTimestampMonotonic", fn)
}

// stubShow swaps runSystemctl for fn and records the unit operands of every call; it fails the test
// on any call that is not `systemctl show -p <props> -- <units>`.
func stubShow(t *testing.T, props string, fn func(units []string) ([]byte, error)) *[][]string {
	t.Helper()
	old := runSystemctl
	t.Cleanup(func() { runSystemctl = old })
	calls := &[][]string{}
	prefix := []string{"show", "-p", props, "--"}
	runSystemctl = func(_ context.Context, args ...string) ([]byte, error) {
		if len(args) <= len(prefix) || !reflect.DeepEqual(args[:len(prefix)], prefix) {
			t.Fatalf("unexpected systemctl call %q", args)
		}
		units := append([]string(nil), args[len(prefix):]...)
		*calls = append(*calls, units)
		return fn(units)
	}
	return calls
}

// exitError runs a shell snippet and returns the real *exec.ExitError it ends with: the shape of a
// systemctl call that answered with a non-zero exit (or was killed).
func exitError(t *testing.T, script string) error {
	t.Helper()
	err := exec.Command("sh", "-c", script).Run()
	var exitErr *exec.ExitError
	if !errors.As(err, &exitErr) {
		t.Fatalf("sh -c %q: want *exec.ExitError, got %v", script, err)
	}
	return err
}

func TestFilterEnabledInactiveRealBlocks(t *testing.T) {
	// Spec (b): oneshot+success, ConditionResult=no and a non-empty TriggeredBy are inactive by
	// design; a plain stopped service stays. Candidates are in a different order than the blocks.
	candidates := []string{"cron.service", "anacron.service", "smartmontools.service", "sshd-keygen.service",
		"systemd-pstore.service", "grub-common.service", "e2scrub_reap.service"}
	got := parseEnabledInactive([]byte(showBlocks257), candidates)
	if !reflect.DeepEqual(got, []string{"cron.service"}) {
		t.Errorf("kept = %q, want [cron.service]", got)
	}
	// A block is found under every name in Names, not only under its Id.
	if got := parseEnabledInactive([]byte(showBlocks257), []string{"smartd.service"}); len(got) != 0 {
		t.Errorf("alias smartd.service: kept = %q, want it matched via Names and dropped", got)
	}
}

func TestFilterEnabledInactiveNeverStartedKeeps(t *testing.T) {
	// A unit systemd never tried to start only looks like a finished oneshot or a failed condition:
	// both stay candidates, as an enabled service blocked by a failed dependency must.
	candidates := []string{"alsa-restore.service", "alsa-state.service"}
	got := parseEnabledInactive([]byte(neverStartedBlocks257), candidates)
	if !reflect.DeepEqual(got, candidates) {
		t.Errorf("kept = %q, want all %q", got, candidates)
	}
	// TriggeredBy needs no start attempt: a socket-activated unit that never ran is still dropped.
	out := []byte("Type=simple\nResult=success\nId=socket-activated.service\nNames=socket-activated.service\n" +
		"TriggeredBy=socket-activated.socket\nConditionResult=no\nConditionTimestampMonotonic=0\n")
	if got := parseEnabledInactive(out, []string{"socket-activated.service"}); len(got) != 0 {
		t.Errorf("socket-activated: kept = %q, want it dropped", got)
	}
}

func TestFilterEnabledInactiveMissingPropertyKeeps(t *testing.T) {
	// A property that is absent (older systemd) or empty never drops a unit, and neither does a
	// candidate without any block. A oneshot that did not succeed stays, too.
	out := []byte("Type=simple\nResult=success\nId=no-triggeredby.service\nNames=no-triggeredby.service\n" +
		"ConditionResult=yes\n\n" +
		"Type=\nResult=\nId=empty-props.service\nNames=empty-props.service\nTriggeredBy=\nConditionResult=\n\n" +
		"Type=oneshot\nId=oneshot-no-result.service\n\n" +
		"Type=oneshot\nResult=exit-code\nId=oneshot-failed.service\nTriggeredBy=\nConditionResult=yes\n" +
		"ConditionTimestampMonotonic=30030294\n\n" +
		"Type=oneshot\nResult=success\nId=no-timestamp.service\nTriggeredBy=\nConditionResult=no\n\n" +
		"Type=oneshot\nResult=success\nId=empty-timestamp.service\nTriggeredBy=\nConditionResult=no\n" +
		"ConditionTimestampMonotonic=\n")
	candidates := []string{"no-triggeredby.service", "empty-props.service", "oneshot-no-result.service",
		"oneshot-failed.service", "no-timestamp.service", "empty-timestamp.service", "no-block.service"}
	if got := parseEnabledInactive(out, candidates); !reflect.DeepEqual(got, candidates) {
		t.Errorf("kept = %q, want all %q", got, candidates)
	}
	// Empty output (systemctl printed nothing) keeps everything as well.
	if got := parseEnabledInactive(nil, candidates); !reflect.DeepEqual(got, candidates) {
		t.Errorf("empty output: kept = %q, want all", got)
	}
}

func TestFilterEnabledInactiveBatch(t *testing.T) {
	// One batched call for all candidates; its blocks decide.
	calls := stubSystemctl(t, func(units []string) ([]byte, error) { return []byte(showBlocks257), nil })
	candidates := []string{"anacron.service", "cron.service", "e2scrub_reap.service"}
	got := filterEnabledInactive(context.Background(), candidates)
	if !reflect.DeepEqual(got, []string{"cron.service"}) {
		t.Errorf("kept = %q, want [cron.service]", got)
	}
	if !reflect.DeepEqual(*calls, [][]string{candidates}) {
		t.Errorf("calls = %q, want one batched call", *calls)
	}
}

func TestFilterEnabledInactiveNoCandidates(t *testing.T) {
	calls := stubSystemctl(t, func(units []string) ([]byte, error) { return nil, nil })
	got := filterEnabledInactive(context.Background(), []string{})
	if got == nil || len(got) != 0 {
		t.Errorf("want an empty, non-nil list (JSON []), got %#v", got)
	}
	if len(*calls) != 0 {
		t.Errorf("no candidates must not call systemctl, got %q", *calls)
	}
}

func TestFilterEnabledInactiveBatchErrorQueriesSingly(t *testing.T) {
	// systemctl answers the batch with exit 1 (e.g. one invalid name): every candidate is asked on
	// its own; a failed single query leaves its unit a candidate.
	batchErr := exitError(t, "exit 1")
	singleErr := exitError(t, "exit 1")
	calls := stubSystemctl(t, func(units []string) ([]byte, error) {
		if len(units) > 1 {
			return []byte(showBlockFor("e2scrub_reap.service")), batchErr
		}
		if units[0] == "broken.service" {
			return nil, singleErr
		}
		return showBlockFor(units[0]), nil
	})
	candidates := []string{"broken.service", "cron.service", "e2scrub_reap.service", "systemd-pstore.service"}
	got := filterEnabledInactive(context.Background(), candidates)
	if !reflect.DeepEqual(got, []string{"broken.service", "cron.service"}) {
		t.Errorf("kept = %q, want [broken.service cron.service]", got)
	}
	want := [][]string{candidates, {"broken.service"}, {"cron.service"}, {"e2scrub_reap.service"},
		{"systemd-pstore.service"}}
	if !reflect.DeepEqual(*calls, want) {
		t.Errorf("calls = %q, want batch then one call per candidate", *calls)
	}
}

func TestFilterEnabledInactiveSingleQueryCap(t *testing.T) {
	// After a failed batch at most 50 candidates are asked singly (Kevin 2026-10-16); the rest stays
	// unchecked, i.e. a candidate, as before the re-check existed.
	batchErr := exitError(t, "exit 1")
	singles := 0
	stubSystemctl(t, func(units []string) ([]byte, error) {
		if len(units) > 1 {
			return nil, batchErr
		}
		singles++
		return []byte("Type=oneshot\nResult=success\nId=" + units[0] + "\nNames=" + units[0] +
			"\nTriggeredBy=\nConditionResult=yes\nConditionTimestampMonotonic=30030294\n"), nil
	})
	candidates := make([]string, 60)
	for i := range candidates {
		candidates[i] = fmt.Sprintf("unit-%02d.service", i)
	}
	got := filterEnabledInactive(context.Background(), candidates)
	if singles != 50 {
		t.Errorf("single queries = %d, want 50", singles)
	}
	if !reflect.DeepEqual(got, candidates[50:]) {
		t.Errorf("kept = %q, want the unchecked last 10 %q", got, candidates[50:])
	}
}

func TestFilterEnabledInactiveSingleKilledStops(t *testing.T) {
	// A single query killed by the timeout ends the fallback: systemctl hangs, and waiting out up to
	// 49 more timeouts would cost the report. The killed unit and all later ones stay candidates.
	batchErr := exitError(t, "exit 1")
	killed := exitError(t, "kill -9 $$")
	calls := stubSystemctl(t, func(units []string) ([]byte, error) {
		if len(units) > 1 {
			return nil, batchErr
		}
		if units[0] == "cron.service" {
			return nil, killed
		}
		return showBlockFor(units[0]), nil
	})
	candidates := []string{"e2scrub_reap.service", "cron.service", "grub-common.service",
		"systemd-pstore.service"}
	got := filterEnabledInactive(context.Background(), candidates)
	if !reflect.DeepEqual(got, candidates[1:]) {
		t.Errorf("kept = %q, want %q", got, candidates[1:])
	}
	want := [][]string{candidates, {"e2scrub_reap.service"}, {"cron.service"}}
	if !reflect.DeepEqual(*calls, want) {
		t.Errorf("calls = %q, want no query after the killed one", *calls)
	}
}

func TestFilterEnabledInactiveBatchKilledKeepsAll(t *testing.T) {
	// A batch that did not answer — ended by the timeout, killed or not started at all — gets no
	// per-unit fallback: 50 more timeouts would outlast the agent unit's TimeoutStartSec. All stay
	// candidates.
	for name, batchErr := range map[string]error{
		"timed out":   context.DeadlineExceeded,
		"killed":      exitError(t, "kill -9 $$"),
		"not started": errors.New("exec: \"systemctl\": executable file not found in $PATH"),
	} {
		t.Run(name, func(t *testing.T) {
			calls := stubSystemctl(t, func(units []string) ([]byte, error) { return nil, batchErr })
			candidates := []string{"cron.service", "e2scrub_reap.service"}
			if got := filterEnabledInactive(context.Background(), candidates); !reflect.DeepEqual(got, candidates) {
				t.Errorf("kept = %q, want all %q", got, candidates)
			}
			if len(*calls) != 1 {
				t.Errorf("calls = %q, want only the batch", *calls)
			}
		})
	}
}

func TestFilterEnabledInactiveCandidatesSorted(t *testing.T) {
	// assembleServiceHealth hands the candidates over sorted, so the 50-unit cap always checks the
	// same units instead of a random map-order subset. Twelve units: map order is then never sorted
	// by chance.
	unitStates := map[string]string{"active.service": "active"}
	enabledStates := map[string]string{"active.service": "enabled"}
	want := []string{}
	for i := range 12 {
		unit := fmt.Sprintf("unit-%02d.service", i)
		unitStates[unit] = "inactive"
		enabledStates[unit] = "enabled"
		want = append(want, unit)
	}
	got := assembleServiceHealth(unitStates, enabledStates, nil)
	if !reflect.DeepEqual(got["enabled_inactive"], want) {
		t.Errorf("enabled_inactive = %q, want sorted %q", got["enabled_inactive"], want)
	}
}

// The exact argument lists collectServiceHealth hands runSystemctl; the show calls without their
// units, as stubCollector keys them.
const (
	listUnitsArgs     = "list-units --type=service --all --no-legend --plain --no-pager"
	listUnitFilesArgs = "list-unit-files --type=service --no-legend --no-pager"
	listFailedArgs    = "list-units --state=failed --no-legend --plain"
	recheckShow       = "show -p Id,Names,Type,Result,ConditionResult,TriggeredBy,ConditionTimestampMonotonic"
	aliasShow         = "show -p Id,Names"
)

// aliasBlocks is real systemd 257 `systemctl show -p Id,Names -- smartd.service sshd.service`
// output for the aliases of collectorListUnitFiles: the alias stands in Names, the target in Id.
const aliasBlocks = `Id=smartmontools.service
Names=smartmontools.service smartd.service

Id=ssh.service
Names=ssh.service sshd.service
`

// collectorListUnits is real systemd 257 `list-units` output (cron stopped by hand, smartmontools
// failed); collectorListUnitFiles the matching `list-unit-files` lines, with the template getty@
// and the aliases smartd and sshd that list-units never shows.
const collectorListUnits = `anacron.service          loaded    inactive dead    Run anacron jobs
cron.service             loaded    inactive dead    Regular background program processing daemon
e2scrub_reap.service     loaded    inactive dead    Remove Stale Online ext4 Metadata Check Snapshots
getty@tty1.service       loaded    active   running Getty on tty1
smartmontools.service    loaded    failed   failed  Self Monitoring and Reporting Technology (SMART) Daemon
ssh.service              loaded    active   running OpenBSD Secure Shell server
systemd-pstore.service   loaded    inactive dead    Platform Persistent Storage Archival
`

const collectorListUnitFiles = `anacron.service              enabled         enabled
cron.service                 enabled         enabled
e2scrub_reap.service         enabled         enabled
getty@.service               enabled         enabled
smartd.service               alias           -
smartmontools.service        enabled         enabled
ssh.service                  enabled         enabled
sshd.service                 alias           -
systemd-pstore.service       enabled         enabled
`

type systemctlReply struct {
	out string
	err error
}

// stubCollector swaps runSystemctl for a fake systemctl that answers every call from replies, keyed
// by its space-joined arguments (a `show` by "show -p <props>", without its units), and records the
// calls; a call without a reply fails the test.
func stubCollector(t *testing.T, replies map[string]systemctlReply) *[]string {
	t.Helper()
	old := runSystemctl
	t.Cleanup(func() { runSystemctl = old })
	calls := &[]string{}
	runSystemctl = func(_ context.Context, args ...string) ([]byte, error) {
		call := strings.Join(args, " ")
		*calls = append(*calls, call)
		key := call
		if args[0] == "show" && len(args) > 2 {
			key = strings.Join(args[:3], " ")
		}
		reply, ok := replies[key]
		if !ok {
			t.Fatalf("unexpected systemctl call %q", call)
		}
		return []byte(reply.out), reply.err
	}
	return calls
}

// units lists the unit names of an all_services inventory in its order.
func units(entries []ServiceEntry) []string {
	names := make([]string, 0, len(entries))
	for _, e := range entries {
		names = append(names, e["unit"])
	}
	return names
}

func TestServiceHealthCollector(t *testing.T) {
	// The collector end to end against a fake systemctl: list-units, list-unit-files and the failed
	// list feed the report, the sorted enabled-inactive candidates reach the show re-check, and the
	// counts cover the seven loaded units of list-units, not the template and the aliases only
	// list-unit-files knows.
	calls := stubCollector(t, map[string]systemctlReply{
		listUnitsArgs:     {out: collectorListUnits},
		listUnitFilesArgs: {out: collectorListUnitFiles},
		listFailedArgs:    {out: "smartmontools.service loaded failed failed Self Monitoring and Reporting Technology (SMART) Daemon\n"},
		recheckShow:       {out: showBlocks257},
		aliasShow:         {out: aliasBlocks},
	})
	got := collectServiceHealth(context.Background())

	wantUnits := []string{"anacron.service", "cron.service", "e2scrub_reap.service", "getty@.service",
		"getty@tty1.service", "smartd.service", "smartmontools.service", "ssh.service", "sshd.service",
		"systemd-pstore.service"}
	if all := units(got["all_services"].([]ServiceEntry)); !reflect.DeepEqual(all, wantUnits) {
		t.Errorf("all_services = %q, want sorted %q", all, wantUnits)
	}
	if !reflect.DeepEqual(got["enabled_inactive"], []string{"cron.service"}) {
		t.Errorf("enabled_inactive = %q, want [cron.service] after the re-check", got["enabled_inactive"])
	}
	if !reflect.DeepEqual(got["failed"], []string{"smartmontools.service"}) {
		t.Errorf("failed = %q, want [smartmontools.service]", got["failed"])
	}
	if !reflect.DeepEqual(got["counts"], map[string]int{"active": 2, "total": 7}) {
		t.Errorf("counts = %v, want active 2 of 7 loaded units", got["counts"])
	}
	if e, ok := got["error"]; ok {
		t.Errorf("error = %q, want none when systemctl answered", e)
	}
	wantCalls := []string{listUnitsArgs, listUnitFilesArgs, listFailedArgs,
		"show -p " + enabledInactiveProps + " -- anacron.service cron.service e2scrub_reap.service systemd-pstore.service",
		aliasShow + " -- smartd.service sshd.service"}
	if !reflect.DeepEqual(*calls, wantCalls) {
		t.Errorf("calls = %q, want %q", *calls, wantCalls)
	}
}

func TestServiceHealthSorted(t *testing.T) {
	// all_services is sorted by unit, so the server's 500-entry cap always keeps the same units.
	// Thirty units spread over both maps: map order is never sorted by chance.
	unitStates := map[string]string{}
	enabledStates := map[string]string{}
	want := []string{}
	for i := range 30 {
		unit := fmt.Sprintf("unit-%02d.service", i)
		if i%3 != 0 {
			unitStates[unit] = "active"
		}
		if i%3 != 1 {
			enabledStates[unit] = "enabled"
		}
		want = append(want, unit)
	}
	got := assembleServiceHealth(unitStates, enabledStates, nil)
	if all := units(got["all_services"].([]ServiceEntry)); !reflect.DeepEqual(all, want) {
		t.Errorf("all_services = %q, want sorted %q", all, want)
	}
}

func TestServiceHealthSystemctlError(t *testing.T) {
	// A failed list-units leaves no active state to report: the report says so in a short reason
	// (exit status, timeout or that systemctl did not start, never stderr or a path) and carries no
	// counts, which would claim zero active units. A call killed from outside, not by the timeout,
	// keeps its signal.
	for name, tc := range map[string]struct {
		err  error
		want string
	}{
		"exit status": {exitError(t, "exit 1"), "systemctl list-units failed: exit status 1"},
		"timed out":   {context.DeadlineExceeded, "systemctl list-units failed: timed out after 15s"},
		"killed":      {exitError(t, "kill -9 $$"), "systemctl list-units failed: signal: killed"},
		"not found": {&exec.Error{Name: "systemctl", Err: exec.ErrNotFound},
			"systemctl list-units failed: systemctl did not start"},
		"not executable": {&fs.PathError{Op: "fork/exec", Path: "/usr/bin/systemctl", Err: syscall.EACCES},
			"systemctl list-units failed: systemctl did not start"},
	} {
		t.Run(name, func(t *testing.T) {
			stubCollector(t, map[string]systemctlReply{
				listUnitsArgs:     {err: tc.err},
				listUnitFilesArgs: {out: collectorListUnitFiles},
				listFailedArgs:    {},
				aliasShow:         {out: aliasBlocks},
			})
			got := collectServiceHealth(context.Background())
			if got["error"] != tc.want {
				t.Errorf("error = %q, want %q", got["error"], tc.want)
			}
			if c, ok := got["counts"]; ok {
				t.Errorf("counts = %v, want none without list-units", c)
			}
			if !reflect.DeepEqual(got["enabled_inactive"], []string{}) {
				t.Errorf("enabled_inactive = %q, want []", got["enabled_inactive"])
			}
		})
	}
}

// aliasOf maps every inventory entry that carries alias_of to it.
func aliasOf(entries []ServiceEntry) map[string]string {
	m := map[string]string{}
	for _, e := range entries {
		if a, ok := e["alias_of"]; ok {
			m[e["unit"]] = a
		}
	}
	return m
}

func TestAliasAndWatchAliasOf(t *testing.T) {
	// The aliases list-unit-files reports get alias_of from one batched show, matched through Names.
	// The template alias autovt@ stays out of the batch (systemctl rejects a template name and fails
	// the whole call); an alias whose block has its own name as Id resolves to nothing.
	files := collectorListUnitFiles +
		"autovt@.service              alias           -\n" +
		"ghost.service                alias           -\n"
	calls := stubCollector(t, map[string]systemctlReply{
		listUnitsArgs:     {out: collectorListUnits},
		listUnitFilesArgs: {out: files},
		listFailedArgs:    {},
		recheckShow:       {out: showBlocks257},
		aliasShow:         {out: aliasBlocks + "\nId=ghost.service\nNames=ghost.service\n"},
	})
	got := collectServiceHealth(context.Background())

	want := map[string]string{"smartd.service": "smartmontools.service", "sshd.service": "ssh.service"}
	if a := aliasOf(got["all_services"].([]ServiceEntry)); !reflect.DeepEqual(a, want) {
		t.Errorf("alias_of = %v, want %v", a, want)
	}
	aliasCalls := []string{}
	for _, c := range *calls {
		if strings.HasPrefix(c, aliasShow+" ") {
			aliasCalls = append(aliasCalls, c)
		}
	}
	wantCalls := []string{aliasShow + " -- ghost.service smartd.service sshd.service"}
	if !reflect.DeepEqual(aliasCalls, wantCalls) {
		t.Errorf("alias calls = %q, want one batch without the template %q", aliasCalls, wantCalls)
	}
}

func TestAliasAndWatchAliasShowFails(t *testing.T) {
	// A failed alias lookup resolves nothing, not even from the blocks printed before the failure (a
	// call killed by the timeout can end in a truncated Id); the rest of the report stands.
	partial := "Id=smartmontools.service\nNames=smartmontools.service smartd.service\n\nId=ssh.ser"
	for name, err := range map[string]error{
		"exit status": exitError(t, "exit 1"),
		"killed":      exitError(t, "kill -9 $$"),
	} {
		t.Run(name, func(t *testing.T) {
			stubCollector(t, map[string]systemctlReply{
				listUnitsArgs:     {out: collectorListUnits},
				listUnitFilesArgs: {out: collectorListUnitFiles},
				listFailedArgs:    {},
				recheckShow:       {out: showBlocks257},
				aliasShow:         {out: partial, err: err},
			})
			got := collectServiceHealth(context.Background())
			if a := aliasOf(got["all_services"].([]ServiceEntry)); len(a) != 0 {
				t.Errorf("alias_of = %v, want none after a failed show", a)
			}
			if _, ok := got["error"]; ok {
				t.Errorf("error = %q, want none: list-units answered", got["error"])
			}
			if !reflect.DeepEqual(got["counts"], map[string]int{"active": 2, "total": 7}) {
				t.Errorf("counts = %v, want active 2 of 7", got["counts"])
			}
		})
	}
}

func TestAliasAndWatchCountsSkipUnloaded(t *testing.T) {
	// list-units --all also lists units without a unit file (not-found, here one still running after
	// its file was removed) and masked units something still references. Neither is a loaded
	// service, so neither counts, in active or in total; the inventory keeps the running and the
	// masked one and leaves the not-found inactive one out (TestServiceHealthNotFoundInactiveDropped).
	unitsOut := collectorListUnits +
		"auditd.service           not-found inactive dead    auditd.service\n" +
		"gone.service             not-found active   running gone.service\n" +
		"hwclock.service          masked    inactive dead    hwclock.service\n"
	stubCollector(t, map[string]systemctlReply{
		listUnitsArgs:     {out: unitsOut},
		listUnitFilesArgs: {out: collectorListUnitFiles + "hwclock.service              masked          enabled\n"},
		listFailedArgs:    {},
		recheckShow:       {out: showBlocks257},
		aliasShow:         {out: aliasBlocks},
	})
	got := collectServiceHealth(context.Background())
	if !reflect.DeepEqual(got["counts"], map[string]int{"active": 2, "total": 7}) {
		t.Errorf("counts = %v, want active 2 of the 7 loaded units", got["counts"])
	}
	all := strings.Join(units(got["all_services"].([]ServiceEntry)), " ")
	for _, u := range []string{"gone.service", "hwclock.service"} {
		if !strings.Contains(all, u) {
			t.Errorf("all_services lacks %s: %s", u, all)
		}
	}
	if strings.Contains(all, "auditd.service") {
		t.Errorf("all_services has the not-found inactive auditd.service: %s", all)
	}
}

// notFoundListUnits are real systemd 257 `list-units` lines (Debian 13): firewalld is not installed,
// but another unit references it, so list-units --all lists it without a unit file; modprobe@fuse is
// a loaded, inactive instance that list-unit-files does not list either.
const notFoundListUnits = `firewalld.service        not-found inactive dead    firewalld.service
modprobe@fuse.service    loaded    inactive dead    Load Kernel Module fuse
`

func TestServiceHealthNotFoundInactiveDropped(t *testing.T) {
	// In the inventory firewalld would be {inactive, unknown}, i.e. down for the list mode instead of
	// nodata like a name that does not exist (spec (c)3): the collector leaves it out. A loaded
	// inactive unit stays, even one list-unit-files does not know; counts, re-check candidates and
	// aliases are those of the report without firewalld.
	calls := stubCollector(t, map[string]systemctlReply{
		listUnitsArgs:     {out: collectorListUnits + notFoundListUnits},
		listUnitFilesArgs: {out: collectorListUnitFiles},
		listFailedArgs:    {},
		recheckShow:       {out: showBlocks257},
		aliasShow:         {out: aliasBlocks},
	})
	got := collectServiceHealth(context.Background())

	all := got["all_services"].([]ServiceEntry)
	wantUnits := []string{"anacron.service", "cron.service", "e2scrub_reap.service", "getty@.service",
		"getty@tty1.service", "modprobe@fuse.service", "smartd.service", "smartmontools.service",
		"ssh.service", "sshd.service", "systemd-pstore.service"}
	if u := units(all); !reflect.DeepEqual(u, wantUnits) {
		t.Errorf("all_services = %q, want %q without firewalld.service", u, wantUnits)
	}
	byUnit := map[string]ServiceEntry{}
	for _, e := range all {
		byUnit[e["unit"]] = e
	}
	for _, want := range []ServiceEntry{
		{"unit": "cron.service", "active_state": "inactive", "enabled_state": "enabled"},
		{"unit": "modprobe@fuse.service", "active_state": "inactive", "enabled_state": "unknown"},
	} {
		if e := byUnit[want["unit"]]; !reflect.DeepEqual(e, want) {
			t.Errorf("%s = %v, want %v", want["unit"], e, want)
		}
	}
	wantAlias := map[string]string{"smartd.service": "smartmontools.service", "sshd.service": "ssh.service"}
	if a := aliasOf(all); !reflect.DeepEqual(a, wantAlias) {
		t.Errorf("alias_of = %v, want %v", a, wantAlias)
	}
	if !reflect.DeepEqual(got["counts"], map[string]int{"active": 2, "total": 8}) {
		t.Errorf("counts = %v, want active 2 of the 8 loaded units", got["counts"])
	}
	if !reflect.DeepEqual(got["enabled_inactive"], []string{"cron.service"}) {
		t.Errorf("enabled_inactive = %q, want [cron.service]", got["enabled_inactive"])
	}
	wantCalls := []string{listUnitsArgs, listUnitFilesArgs, listFailedArgs,
		"show -p " + enabledInactiveProps + " -- anacron.service cron.service e2scrub_reap.service systemd-pstore.service",
		aliasShow + " -- smartd.service sshd.service"}
	if !reflect.DeepEqual(*calls, wantCalls) {
		t.Errorf("calls = %q, want %q", *calls, wantCalls)
	}
}

func TestServiceHealthNotFoundActiveOrFailedKept(t *testing.T) {
	// A not-found unit still running after its unit file was removed, or one that failed, has a state
	// worth reporting: both stay in the inventory with their active state, and neither counts.
	stubCollector(t, map[string]systemctlReply{
		listUnitsArgs: {out: collectorListUnits +
			"gone.service             not-found active   running gone.service\n" +
			"old.service              not-found failed   failed  old.service\n"},
		listUnitFilesArgs: {out: collectorListUnitFiles},
		listFailedArgs:    {out: "old.service not-found failed failed old.service\n"},
		recheckShow:       {out: showBlocks257},
		aliasShow:         {out: aliasBlocks},
	})
	got := collectServiceHealth(context.Background())

	byUnit := map[string]ServiceEntry{}
	for _, e := range got["all_services"].([]ServiceEntry) {
		byUnit[e["unit"]] = e
	}
	for _, want := range []ServiceEntry{
		{"unit": "gone.service", "active_state": "active", "enabled_state": "unknown"},
		{"unit": "old.service", "active_state": "failed", "enabled_state": "unknown"},
	} {
		if e := byUnit[want["unit"]]; !reflect.DeepEqual(e, want) {
			t.Errorf("%s = %v, want %v", want["unit"], e, want)
		}
	}
	if !reflect.DeepEqual(got["failed"], []string{"old.service"}) {
		t.Errorf("failed = %q, want [old.service]", got["failed"])
	}
	if !reflect.DeepEqual(got["counts"], map[string]int{"active": 2, "total": 7}) {
		t.Errorf("counts = %v, want active 2 of the 7 loaded units", got["counts"])
	}
}

func TestServiceHealthNotFoundListUnitsFails(t *testing.T) {
	// Without list-units there is no load state: nothing is left out, all_services is list-unit-files
	// with every active state unknown, as before.
	stubCollector(t, map[string]systemctlReply{
		listUnitsArgs:     {err: exitError(t, "exit 1")},
		listUnitFilesArgs: {out: collectorListUnitFiles},
		listFailedArgs:    {},
		aliasShow:         {out: aliasBlocks},
	})
	got := collectServiceHealth(context.Background())
	all := got["all_services"].([]ServiceEntry)
	want := []string{"anacron.service", "cron.service", "e2scrub_reap.service", "getty@.service",
		"smartd.service", "smartmontools.service", "ssh.service", "sshd.service", "systemd-pstore.service"}
	if !reflect.DeepEqual(units(all), want) {
		t.Errorf("all_services = %q, want the units of list-unit-files %q", units(all), want)
	}
	for _, e := range all {
		if e["active_state"] != "unknown" {
			t.Errorf("%s: active_state = %q, want unknown", e["unit"], e["active_state"])
		}
	}
}

// watchedBlocks is real systemd 257 `systemctl show -p Id,Names,ActiveState,MainPID -- <name>`
// output: sshd (an alias of ssh.service), cron, and nginx, which is not installed.
var watchedBlocks = map[string]string{
	"sshd":         "MainPID=1022\nId=ssh.service\nNames=ssh.service sshd.service\nActiveState=active\n",
	"cron.service": "MainPID=912\nId=cron.service\nNames=cron.service\nActiveState=active\n",
	"nginx":        "MainPID=0\nId=nginx.service\nNames=nginx.service\nActiveState=inactive\n",
}

func TestAliasAndWatchNames(t *testing.T) {
	// A watched alias finds its unit's block through Names: sshd and sshd.service are ssh.service on
	// Debian and Ubuntu, whose Id alone left them not running.
	got := parseWatchedServices([]byte(watchedBlocks["sshd"]), []string{"sshd", "sshd.service", "ssh"})
	for _, svc := range got {
		if svc["running"] != true || svc["pid"] != "1022" {
			t.Errorf("%s: want running pid 1022, got %v", svc["name"], svc)
		}
	}
}

func TestAliasAndWatchTemplateSingly(t *testing.T) {
	// A template name makes systemctl fail the whole batch (exit 1 after the blocks before it): every
	// name is asked on its own, and only the template stays not running.
	batchErr := exitError(t, "exit 1")
	singleErr := exitError(t, "exit 1")
	names := []string{"sshd", "getty@.service", "nginx", "cron.service"}
	calls := stubShow(t, "Id,Names,ActiveState,MainPID", func(units []string) ([]byte, error) {
		if len(units) > 1 {
			return []byte(watchedBlocks["sshd"]), batchErr
		}
		if units[0] == "getty@.service" {
			return nil, singleErr
		}
		return []byte(watchedBlocks[units[0]]), nil
	})
	got := collectWatchedServices(context.Background(), names)
	want := []map[string]any{
		{"name": "sshd", "running": true, "pid": "1022"},
		{"name": "getty@.service", "running": false, "pid": nil},
		{"name": "nginx", "running": false, "pid": nil},
		{"name": "cron.service", "running": true, "pid": "912"},
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("watched = %v, want %v", got, want)
	}
	wantCalls := [][]string{names, {"sshd"}, {"getty@.service"}, {"nginx"}, {"cron.service"}}
	if !reflect.DeepEqual(*calls, wantCalls) {
		t.Errorf("calls = %q, want the batch, then one call per name", *calls)
	}
}

func TestAliasAndWatchFallbackLimits(t *testing.T) {
	// The per-name fallback keeps the limits of the enabled-inactive re-check: none after a batch
	// that did not answer, none after a single query killed by the timeout, at most 50 queries. A
	// name not asked is reported not running, as every name was before the fallback existed.
	down := func(name string) map[string]any { return map[string]any{"name": name, "running": false, "pid": nil} }
	for name, batchErr := range map[string]error{
		"batch killed":      exitError(t, "kill -9 $$"),
		"batch not started": errors.New("exec: \"systemctl\": executable file not found in $PATH"),
	} {
		t.Run(name, func(t *testing.T) {
			calls := stubShow(t, "Id,Names,ActiveState,MainPID", func(units []string) ([]byte, error) {
				return nil, batchErr
			})
			got := collectWatchedServices(context.Background(), []string{"sshd", "cron.service"})
			if want := []map[string]any{down("sshd"), down("cron.service")}; !reflect.DeepEqual(got, want) {
				t.Errorf("watched = %v, want %v", got, want)
			}
			if len(*calls) != 1 {
				t.Errorf("calls = %q, want only the batch", *calls)
			}
		})
	}
	t.Run("single killed", func(t *testing.T) {
		batchErr := exitError(t, "exit 1")
		killed := exitError(t, "kill -9 $$")
		calls := stubShow(t, "Id,Names,ActiveState,MainPID", func(units []string) ([]byte, error) {
			switch {
			case len(units) > 1:
				return nil, batchErr
			case units[0] == "sshd":
				return nil, killed
			}
			return []byte(watchedBlocks[units[0]]), nil
		})
		got := collectWatchedServices(context.Background(), []string{"cron.service", "sshd", "nginx"})
		want := []map[string]any{{"name": "cron.service", "running": true, "pid": "912"}, down("sshd"), down("nginx")}
		if !reflect.DeepEqual(got, want) {
			t.Errorf("watched = %v, want %v", got, want)
		}
		wantCalls := [][]string{{"cron.service", "sshd", "nginx"}, {"cron.service"}, {"sshd"}}
		if !reflect.DeepEqual(*calls, wantCalls) {
			t.Errorf("calls = %q, want none after the killed one", *calls)
		}
	})
	t.Run("cap", func(t *testing.T) {
		batchErr := exitError(t, "exit 1")
		singles := 0
		stubShow(t, "Id,Names,ActiveState,MainPID", func(units []string) ([]byte, error) {
			if len(units) > 1 {
				return nil, batchErr
			}
			singles++
			return []byte("MainPID=7\nId=" + units[0] + "\nNames=" + units[0] + "\nActiveState=active\n"), nil
		})
		names := make([]string, 60)
		for i := range names {
			names[i] = fmt.Sprintf("unit-%02d.service", i)
		}
		got := collectWatchedServices(context.Background(), names)
		if singles != 50 {
			t.Errorf("single queries = %d, want 50", singles)
		}
		for i, svc := range got {
			if want := i < 50; svc["running"] != want {
				t.Errorf("%s: running = %v, want %v", names[i], svc["running"], want)
			}
		}
	})
}

// fakeSystemctl puts a systemctl that runs script on the PATH, and nothing else there: no test
// reaches the host's systemd. script calls other programs by absolute path.
func fakeSystemctl(t *testing.T, script string) {
	t.Helper()
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "systemctl"), []byte("#!/bin/sh\n"+script+"\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", dir)
}

// endsWithin runs call and fails the test when it does not return within d.
func endsWithin(t *testing.T, d time.Duration, call func()) {
	t.Helper()
	done := make(chan struct{})
	go func() {
		call()
		close(done)
	}()
	select {
	case <-done:
	case <-time.After(d):
		t.Fatalf("the call did not return within %s", d)
	}
}

// R-0638: a systemctl that does not answer (hung systemd or D-Bus) costs the service collector the
// rest of the run's context, not pluginTimeout per call: once the context has ended, every further
// call returns unstarted. The call the deadline ended reports like the timeout it is.
func TestServiceHealthEndsAtTheEndOfTheContext(t *testing.T) {
	fakeSystemctl(t, "exec /bin/sleep 30")
	ctx, cancel := context.WithTimeout(context.Background(), 300*time.Millisecond)
	defer cancel()
	var got map[string]any
	endsWithin(t, 3*time.Second, func() { got = collectServiceHealth(ctx) })
	if want := "systemctl list-units failed: timed out after 15s"; got["error"] != want {
		t.Errorf("error = %q, want %q", got["error"], want)
	}
}

// R-0638: the per-unit fallbacks end with the context too. systemctl answers the batch with exit 1
// and hangs on the single query, which the context ends: it does not count as answered, and no
// further query starts.
func TestServiceFallbackEndsAtTheEndOfTheContext(t *testing.T) {
	down := func(name string) map[string]any { return map[string]any{"name": name, "running": false, "pid": nil} }
	for name, tc := range map[string]struct {
		collect func(context.Context) any
		want    any
	}{
		"enabled inactive": {
			func(ctx context.Context) any {
				return filterEnabledInactive(ctx, []string{"cron.service", "e2scrub_reap.service", "ssh.service"})
			},
			[]string{"cron.service", "e2scrub_reap.service", "ssh.service"},
		},
		"watched": {
			func(ctx context.Context) any { return collectWatchedServices(ctx, []string{"sshd", "cron.service"}) },
			[]map[string]any{down("sshd"), down("cron.service")},
		},
	} {
		t.Run(name, func(t *testing.T) {
			log := filepath.Join(t.TempDir(), "calls")
			// A single query is `show -p <props> -- <unit>`, five arguments; the batch has more.
			fakeSystemctl(t, "echo \"$*\" >> '"+log+"'\ncase $# in 5) exec /bin/sleep 30;; esac\nexit 1")
			ctx, cancel := context.WithTimeout(context.Background(), 300*time.Millisecond)
			defer cancel()
			var got any
			endsWithin(t, 3*time.Second, func() { got = tc.collect(ctx) })
			if !reflect.DeepEqual(got, tc.want) {
				t.Errorf("got %v, want %v", got, tc.want)
			}
			calls, err := os.ReadFile(log)
			if err != nil {
				t.Fatal(err)
			}
			if n := strings.Count(string(calls), "\n"); n != 2 {
				t.Errorf("systemctl ran %d times, want the batch and one single query:\n%s", n, calls)
			}
		})
	}
}

// Every systemctl call of the service collector runs under the collector's context, the batch, the
// per-unit fallback and the alias lookup included: a call under a fresh context would outlast the end
// of the run (R-0883).
func TestServiceCollectorPassesItsContextToEverySystemctlCall(t *testing.T) {
	type ctxKey struct{}
	ctx := context.WithValue(context.Background(), ctxKey{}, t.Name())
	var calls []string
	old := runSystemctl
	t.Cleanup(func() { runSystemctl = old })
	setup := func(fail error) {
		calls = nil
		runSystemctl = func(c context.Context, args ...string) ([]byte, error) {
			if c.Value(ctxKey{}) != t.Name() {
				t.Errorf("systemctl %v ran without the collector's context", args)
			}
			calls = append(calls, strings.Join(args, " "))
			switch args[0] {
			case "list-units":
				return []byte("cron.service loaded inactive dead Cron\n"), nil
			case "list-unit-files":
				return []byte("cron.service enabled enabled\nsshd.service alias enabled\n"), nil
			case "show":
				return nil, fail
			}
			return nil, nil
		}
	}

	// An enabled-inactive candidate and an alias make the collector itself ask for both show calls.
	setup(nil)
	collectServiceHealth(ctx)
	if len(calls) != 5 {
		t.Errorf("collectServiceHealth ran %v, want the three lists, the candidate batch and the alias lookup", calls)
	}

	setup(exec.Command("false").Run()) // a batch that answers with exit 1 gets the per-unit fallback
	filterEnabledInactive(ctx, []string{"cron.service", "ssh.service"})
	if len(calls) != 3 {
		t.Errorf("filterEnabledInactive ran %v, want the batch and one query per unit", calls)
	}

	setup(nil)
	resolveAliases(ctx, []ServiceEntry{{"unit": "sshd.service", "enabled_state": "alias"}})
	if len(calls) != 1 {
		t.Errorf("resolveAliases ran %v, want one show call", calls)
	}
}

func TestBuildReportPassesItsContextToTheServiceCollectors(t *testing.T) {
	type ctxKey struct{}
	stubReportHost(t)
	var health, watched context.Context
	serviceHealthCollector = func(ctx context.Context) map[string]any {
		health = ctx
		return map[string]any{}
	}
	old := runSystemctl
	t.Cleanup(func() { runSystemctl = old })
	runSystemctl = func(ctx context.Context, _ ...string) ([]byte, error) {
		watched = ctx
		return []byte(watchedBlocks["sshd"]), nil
	}
	ctx := context.WithValue(context.Background(), ctxKey{}, t.Name())
	buildReportWithState(ctx, []string{"sshd"}, reportState{}, time.Now())
	for name, got := range map[string]context.Context{"service health": health, "watched services": watched} {
		if got == nil || got.Value(ctxKey{}) != t.Name() {
			t.Errorf("%s collector got context %v, want the report's", name, got)
		}
	}
}
