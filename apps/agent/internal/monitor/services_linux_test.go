// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package monitor

import (
	"errors"
	"fmt"
	"os/exec"
	"reflect"
	"strings"
	"testing"
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

// stubSystemctl swaps runSystemctl for fn and records the unit operands of every call; it fails the
// test on any call that is not the enabled-inactive re-check.
func stubSystemctl(t *testing.T, fn func(units []string) ([]byte, error)) *[][]string {
	t.Helper()
	old := runSystemctl
	t.Cleanup(func() { runSystemctl = old })
	calls := &[][]string{}
	prefix := []string{"show", "-p",
		"Id,Names,Type,Result,ConditionResult,TriggeredBy,ConditionTimestampMonotonic", "--"}
	runSystemctl = func(args ...string) ([]byte, error) {
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
	got := filterEnabledInactive(candidates)
	if !reflect.DeepEqual(got, []string{"cron.service"}) {
		t.Errorf("kept = %q, want [cron.service]", got)
	}
	if !reflect.DeepEqual(*calls, [][]string{candidates}) {
		t.Errorf("calls = %q, want one batched call", *calls)
	}
}

func TestFilterEnabledInactiveNoCandidates(t *testing.T) {
	calls := stubSystemctl(t, func(units []string) ([]byte, error) { return nil, nil })
	got := filterEnabledInactive([]string{})
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
	got := filterEnabledInactive(candidates)
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
	got := filterEnabledInactive(candidates)
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
	got := filterEnabledInactive(candidates)
	if !reflect.DeepEqual(got, candidates[1:]) {
		t.Errorf("kept = %q, want %q", got, candidates[1:])
	}
	want := [][]string{candidates, {"e2scrub_reap.service"}, {"cron.service"}}
	if !reflect.DeepEqual(*calls, want) {
		t.Errorf("calls = %q, want no query after the killed one", *calls)
	}
}

func TestFilterEnabledInactiveBatchKilledKeepsAll(t *testing.T) {
	// A batch that did not answer — killed by the timeout or not started at all — gets no per-unit
	// fallback: 50 more timeouts would outlast the agent unit's TimeoutStartSec. All stay candidates.
	for name, batchErr := range map[string]error{
		"killed":      exitError(t, "kill -9 $$"),
		"not started": errors.New("exec: \"systemctl\": executable file not found in $PATH"),
	} {
		t.Run(name, func(t *testing.T) {
			calls := stubSystemctl(t, func(units []string) ([]byte, error) { return nil, batchErr })
			candidates := []string{"cron.service", "e2scrub_reap.service"}
			if got := filterEnabledInactive(candidates); !reflect.DeepEqual(got, candidates) {
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
