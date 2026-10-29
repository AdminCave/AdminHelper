// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package monitor

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strconv"
	"strings"
	"testing"
	"time"
)

// stubVMStat points vmstatPath at a file holding content for the duration of the test, on a host
// outside a container, where the agent reads its OOM counter from /proc/vmstat.
func stubVMStat(t *testing.T, content string) {
	t.Helper()
	stubVirtualization(t, "kvm", "host")
	path := filepath.Join(t.TempDir(), "vmstat")
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
	old := vmstatPath
	vmstatPath = path
	t.Cleanup(func() { vmstatPath = old })
}

// vmstatWithOOMKill is /proc/vmstat cut down to the counter and two neighbours.
func vmstatWithOOMKill(n uint64) string {
	return fmt.Sprintf("pgmajfault 1042\noom_kill %d\nnuma_hit 77\n", n)
}

// stubVirtualization makes the host facts report system and role as the virtualization, which tells
// the agent whether it runs in a container.
func stubVirtualization(t *testing.T, system, role string) {
	t.Helper()
	old := hostFactsCalls.virtualization
	hostFactsCalls.virtualization = func() (string, string, error) { return system, role, nil }
	t.Cleanup(func() { hostFactsCalls.virtualization = old })
}

// stubMemoryEventsPath points memoryEventsPath at path for the duration of the test.
func stubMemoryEventsPath(t *testing.T, path string) {
	t.Helper()
	old := memoryEventsPath
	memoryEventsPath = path
	t.Cleanup(func() { memoryEventsPath = old })
}

// stubMemoryEvents points memoryEventsPath at a file holding content.
func stubMemoryEvents(t *testing.T, content string) {
	t.Helper()
	path := filepath.Join(t.TempDir(), "memory.events")
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
	stubMemoryEventsPath(t, path)
}

// memoryEventsWithOOMKill is /sys/fs/cgroup/memory.events in a Docker container (cgroup v2) with the
// counter n.
func memoryEventsWithOOMKill(n uint64) string {
	return fmt.Sprintf("low 0\nhigh 0\nmax 12\noom 2\noom_kill %d\noom_group_kill 0\n", n)
}

// stubSystemCLI swaps systemCLI for fake system state tools: on the path are only the tools in
// replies, and each call answers with its tool's reply (like stubDocker). It returns the recorded
// calls, each led by the tool's name; a call of a tool without a reply fails the test. With no
// replies the OOM tests see a block without the fields of the host's own tools.
func stubSystemCLI(t *testing.T, replies map[string]dockerReply) *[][]string {
	t.Helper()
	old := systemCLI
	t.Cleanup(func() { systemCLI = old })
	var calls [][]string
	systemCLI.lookPath = func(file string) (string, error) {
		if _, ok := replies[file]; ok {
			return "/usr/bin/" + file, nil
		}
		return "", exec.ErrNotFound
	}
	systemCLI.run = func(_ context.Context, name string, args ...string) ([]byte, error) {
		calls = append(calls, append([]string{name}, args...))
		reply, ok := replies[name]
		if !ok {
			t.Errorf("unexpected call %s %v", name, args)
			return nil, errors.New("unexpected call")
		}
		return []byte(reply.out), reply.err
	}
	return &calls
}

// stubRebootFlag points rebootRequiredPath into a fresh directory and creates the flag there when
// present is set.
func stubRebootFlag(t *testing.T, present bool) {
	t.Helper()
	path := filepath.Join(t.TempDir(), "reboot-required")
	if present {
		if err := os.WriteFile(path, []byte("*** System restart required ***\n"), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	old := rebootRequiredPath
	rebootRequiredPath = path
	t.Cleanup(func() { rebootRequiredPath = old })
}

// systemStateHelperEnv tells TestHelperSystemStateProcess, run as a child process, which status to
// exit with.
const systemStateHelperEnv = "AH_SYSTEM_STATE_HELPER_EXIT"

// helperStderr is what the helper process writes to stderr before it exits; no warning may carry it.
const helperStderr = "helper stderr line"

// TestHelperSystemStateProcess is no test of its own: exitStatus starts the test binary as its child
// process, which writes helperStderr and exits with the status systemStateHelperEnv names. Without
// it, it returns at once.
func TestHelperSystemStateProcess(t *testing.T) {
	code, err := strconv.Atoi(os.Getenv(systemStateHelperEnv))
	if err != nil {
		return
	}
	fmt.Fprintln(os.Stderr, helperStderr)
	os.Exit(code)
}

// exitStatus is the error runTimed returns for a real child process that exits with code: the
// ExitError exec builds, holding the child's stderr, which the warnings must leave out.
func exitStatus(t *testing.T, code int) error {
	t.Helper()
	t.Setenv(systemStateHelperEnv, strconv.Itoa(code))
	_, err := runTimed(context.Background(), time.Minute, os.Args[0], "-test.run=^TestHelperSystemStateProcess$")
	var exitErr *exec.ExitError
	if !errors.As(err, &exitErr) || exitErr.ExitCode() != code ||
		!strings.Contains(string(exitErr.Stderr), helperStderr) {
		t.Fatalf("helper err = %v, want the ExitError with status %d and its stderr", err, code)
	}
	return err
}

// timedatectlShow is `timedatectl show` on Debian 13 (systemd 257) with the clock synchronized.
const timedatectlShow = `Timezone=Europe/Berlin
LocalRTC=no
CanNTP=yes
NTP=yes
NTPSynchronized=yes
TimeUSec=Tue 2026-10-20 06:47:57 CEST
RTCTimeUSec=Tue 2026-10-20 06:47:57 CEST
`

// assertSystemStateLog checks that the warnings name want (none when want is empty) and carry neither
// the tool's stderr nor a path.
func assertSystemStateLog(t *testing.T, logs, want string) {
	t.Helper()
	if want == "" && logs != "" {
		t.Errorf("log = %q, want no warning", logs)
	}
	if !strings.Contains(logs, want) {
		t.Errorf("log = %q, want it to name %q", logs, want)
	}
	if strings.Contains(logs, helperStderr) || strings.Contains(logs, "/usr/bin") {
		t.Errorf("log = %q, want it without stderr and paths", logs)
	}
}

func TestSystemStateParseOOMKill(t *testing.T) {
	cases := []struct {
		name   string
		vmstat string
		want   uint64
		ok     bool
	}{
		{"among other counters", vmstatWithOOMKill(3), 3, true},
		{"zero", "oom_kill 0\n", 0, true},
		{"no oom_kill line (kernel before 4.13)", "pgmajfault 1042\nnuma_hit 77\n", 0, false},
		{"empty", "", 0, false},
		{"not a number", "oom_kill many\n", 0, false},
		{"negative", "oom_kill -1\n", 0, false},
		{"no value", "oom_kill\n", 0, false},
		{"only a similar name", "oom_kill_total 7\n", 0, false},
	}
	for _, c := range cases {
		got, ok := parseOOMKill([]byte(c.vmstat))
		if got != c.want || ok != c.ok {
			t.Errorf("%s: parseOOMKill = %d, %v; want %d, %v", c.name, got, ok, c.want, c.ok)
		}
	}
}

func TestSystemStateOOMFirstRun(t *testing.T) {
	// The first run has no counter to count from: no field, but the counter goes into the state, also a
	// 0 through the state file, so the second run reports the kills since the first.
	stubSystemCLI(t, nil)
	stubVMStat(t, vmstatWithOOMKill(0))
	block, next := collectSystemState(context.Background(), reportState{})
	if len(block) != 0 {
		t.Errorf("first run block = %v, want no field", block)
	}
	if next.OOMKill == nil || *next.OOMKill != 0 {
		t.Fatalf("first run state oom_kill = %v, want the counter 0", next.OOMKill)
	}

	path := filepath.Join(t.TempDir(), ".report-state.json")
	if err := saveReportState(path, next); err != nil {
		t.Fatal(err)
	}
	stubVMStat(t, vmstatWithOOMKill(2))
	block, next = collectSystemState(context.Background(), loadReportState(path))
	if got, want := dockerWire(t, block), map[string]any{"oom_kills": 2.0}; !reflect.DeepEqual(got, want) {
		t.Errorf("second run block = %v, want %v", got, want)
	}
	if next.OOMKill == nil || *next.OOMKill != 2 {
		t.Errorf("second run state oom_kill = %v, want 2", next.OOMKill)
	}
}

func TestSystemStateOOMKills(t *testing.T) {
	cases := []struct {
		name         string
		saved, count uint64
		want         uint64
	}{
		{"growth", 5, 7, 2},
		{"no new kills", 7, 7, 0},
		{"smaller counter after a reboot", 10, 3, 3},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			stubSystemCLI(t, nil)
			stubVMStat(t, vmstatWithOOMKill(c.count))
			cpu := &cpuSample{Unix: 1_700_000_000, Total: 1000, Busy: 200}
			saved := c.saved
			block, next := collectSystemState(context.Background(), reportState{CPU: cpu, OOMKill: &saved})
			if want := map[string]any{"oom_kills": c.want}; !reflect.DeepEqual(block, want) {
				t.Errorf("block = %v, want %v", block, want)
			}
			if next.OOMKill == nil || *next.OOMKill != c.count {
				t.Errorf("state oom_kill = %v, want the counter %d", next.OOMKill, c.count)
			}
			if next.CPU != cpu {
				t.Errorf("state cpu = %+v, want it handed on unchanged", next.CPU)
			}
		})
	}
}

func TestSystemStateOOMUnreadable(t *testing.T) {
	// Without a counter there is no field, the saved counter stays the base for the next report, and
	// the log names why.
	cases := []struct {
		name string
		stub func(t *testing.T)
		log  string
	}{
		{"no /proc/vmstat", func(t *testing.T) {
			stubVirtualization(t, "kvm", "host")
			old := vmstatPath
			vmstatPath = filepath.Join(t.TempDir(), "missing")
			t.Cleanup(func() { vmstatPath = old })
		}, "no such file or directory, oom_kills left out"},
		{"no oom_kill line", func(t *testing.T) { stubVMStat(t, "pgmajfault 1042\n") },
			"no readable oom_kill counter in /proc/vmstat, oom_kills left out"},
		{"broken number", func(t *testing.T) { stubVMStat(t, "oom_kill 1x\n") },
			"no readable oom_kill counter in /proc/vmstat, oom_kills left out"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			stubSystemCLI(t, nil)
			c.stub(t)
			logs := captureWarnings(t)
			saved := uint64(4)
			block, next := collectSystemState(context.Background(), reportState{OOMKill: &saved})
			if len(block) != 0 {
				t.Errorf("block = %v, want no field", block)
			}
			if next.OOMKill == nil || *next.OOMKill != 4 {
				t.Errorf("state oom_kill = %v, want the saved 4 kept", next.OOMKill)
			}
			if !strings.Contains(logs.String(), c.log) {
				t.Errorf("log = %q, want it to name %q", logs.String(), c.log)
			}
		})
	}
}

// assertOOMState checks the counter and its source that collectSystemState hands on.
func assertOOMState(t *testing.T, next reportState, count uint64, source string) {
	t.Helper()
	if next.OOMKill == nil || *next.OOMKill != count || next.OOMKillSource != source {
		t.Errorf("state oom_kill = %v from %q, want %d from %q", next.OOMKill, next.OOMKillSource, count, source)
	}
}

func TestSystemStateOOMContainer(t *testing.T) {
	// In a container /proc/vmstat counts the OOM kills of the whole host (here 89 since the saved
	// counter); the agent counts those of the container's own cgroup instead, from memory.events.
	for _, system := range []string{"lxc", "docker", "openvz", "rkt"} {
		t.Run(system, func(t *testing.T) {
			stubSystemCLI(t, nil)
			stubVMStat(t, vmstatWithOOMKill(90))
			stubVirtualization(t, system, "guest")
			stubMemoryEvents(t, memoryEventsWithOOMKill(3))
			logs := captureWarnings(t)
			saved := uint64(1)
			block, next := collectSystemState(context.Background(), reportState{OOMKill: &saved, OOMKillSource: oomSourceCgroup})
			if want := map[string]any{"oom_kills": uint64(2)}; !reflect.DeepEqual(block, want) {
				t.Errorf("block = %v, want %v", block, want)
			}
			assertOOMState(t, next, 3, oomSourceCgroup)
			if strings.Contains(logs.String(), "oom_kills") {
				t.Errorf("log = %q, want no warning about oom_kills", logs.String())
			}
		})
	}
}

func TestSystemStateOOMNotContainer(t *testing.T) {
	// A VM, a host and a host that runs containers itself read /proc/vmstat, also where a
	// memory.events lies about, and so does an agent that cannot tell what it runs in.
	cases := []struct {
		name string
		virt func() (string, string, error)
	}{
		{"KVM guest", func() (string, string, error) { return "kvm", "guest", nil }},
		{"Hyper-V guest", func() (string, string, error) { return "hyperv", "guest", nil }},
		{"KVM host", func() (string, string, error) { return "kvm", "host", nil }},
		{"LXC host", func() (string, string, error) { return "lxc", "host", nil }},
		{"nothing detected", func() (string, string, error) { return "", "", nil }},
		// The values beside the error name a container, so only the error makes it none.
		{"detection failed", func() (string, string, error) { return "lxc", "guest", errors.New("open /proc/cpuinfo") }},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			stubSystemCLI(t, nil)
			stubVMStat(t, vmstatWithOOMKill(7))
			hostFactsCalls.virtualization = c.virt // stubVMStat restores it
			stubMemoryEvents(t, memoryEventsWithOOMKill(100))
			saved := uint64(5)
			block, next := collectSystemState(context.Background(), reportState{OOMKill: &saved, OOMKillSource: oomSourceVMStat})
			if want := map[string]any{"oom_kills": uint64(2)}; !reflect.DeepEqual(block, want) {
				t.Errorf("block = %v, want %v", block, want)
			}
			assertOOMState(t, next, 7, oomSourceVMStat)
		})
	}
}

func TestSystemStateOOMContainerUnreadable(t *testing.T) {
	// A container without its own counter (cgroup v1 has no memory.events) has no field rather than
	// the host's kills from /proc/vmstat; the saved counter stays with its source, and the log names
	// why.
	cases := []struct {
		name string
		stub func(t *testing.T)
		log  string
	}{
		{"cgroup v1", func(t *testing.T) { stubMemoryEventsPath(t, filepath.Join(t.TempDir(), "missing")) },
			"container without cgroup v2 memory.events, oom_kills left out"},
		{"unreadable", func(t *testing.T) { stubMemoryEventsPath(t, t.TempDir()) },
			"is a directory, oom_kills left out"},
		{"no oom_kill line", func(t *testing.T) { stubMemoryEvents(t, "low 0\nhigh 0\nmax 0\noom 0\n") },
			"no readable oom_kill counter in memory.events, oom_kills left out"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			stubSystemCLI(t, nil)
			stubVMStat(t, vmstatWithOOMKill(90))
			stubVirtualization(t, "lxc", "guest")
			c.stub(t)
			logs := captureWarnings(t)
			saved := uint64(4)
			block, next := collectSystemState(context.Background(), reportState{OOMKill: &saved, OOMKillSource: oomSourceCgroup})
			if len(block) != 0 {
				t.Errorf("block = %v, want no field", block)
			}
			assertOOMState(t, next, 4, oomSourceCgroup)
			assertSystemStateLog(t, logs.String(), c.log)
		})
	}
}

func TestSystemStateOOMSourceChange(t *testing.T) {
	// The counters of /proc/vmstat and of a cgroup cannot be subtracted from each other: a run that
	// reads another source than the saved counter came from (an agent update, a container detected
	// anew) has no field and saves its own counter, from which the next run counts. A state file from
	// before the source was saved holds a /proc/vmstat counter.
	cases := []struct {
		name      string
		file      string
		container bool
		count     uint64
		source    string
	}{
		{"host becomes a container", `{"oom_kill":40,"oom_kill_source":"vmstat"}`, true, 3, oomSourceCgroup},
		{"container becomes a host", `{"oom_kill":3,"oom_kill_source":"cgroup"}`, false, 40, oomSourceVMStat},
		{"state file without a source, in a container", `{"oom_kill":40}`, true, 3, oomSourceCgroup},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			stubSystemCLI(t, nil)
			stubVMStat(t, vmstatWithOOMKill(40))
			stubMemoryEvents(t, memoryEventsWithOOMKill(3))
			if c.container {
				stubVirtualization(t, "lxc", "guest")
			}
			path := filepath.Join(t.TempDir(), ".report-state.json")
			if err := os.WriteFile(path, []byte(c.file), 0o600); err != nil {
				t.Fatal(err)
			}
			block, next := collectSystemState(context.Background(), loadReportState(path))
			if len(block) != 0 {
				t.Errorf("first run on the new source: block = %v, want no field", block)
			}
			assertOOMState(t, next, c.count, c.source)

			if err := saveReportState(path, next); err != nil {
				t.Fatal(err)
			}
			stubVMStat(t, vmstatWithOOMKill(42))
			stubMemoryEvents(t, memoryEventsWithOOMKill(5))
			if c.container {
				stubVirtualization(t, "lxc", "guest")
			}
			block, _ = collectSystemState(context.Background(), loadReportState(path))
			if got, want := dockerWire(t, block), map[string]any{"oom_kills": 2.0}; !reflect.DeepEqual(got, want) {
				t.Errorf("next run: block = %v, want %v", got, want)
			}
		})
	}
}

func TestSystemStateOOMStateWithoutSource(t *testing.T) {
	// A state file from before the source was saved holds a /proc/vmstat counter: on a host the next
	// report counts from it as before, and the state then names the source.
	stubSystemCLI(t, nil)
	stubVMStat(t, vmstatWithOOMKill(7))
	path := filepath.Join(t.TempDir(), ".report-state.json")
	if err := os.WriteFile(path, []byte(`{"oom_kill":5}`), 0o600); err != nil {
		t.Fatal(err)
	}
	block, next := collectSystemState(context.Background(), loadReportState(path))
	if got, want := dockerWire(t, block), map[string]any{"oom_kills": 2.0}; !reflect.DeepEqual(got, want) {
		t.Errorf("block = %v, want %v", got, want)
	}
	if err := saveReportState(path, next); err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if want := `"oom_kill":7,"oom_kill_source":"vmstat"`; !strings.Contains(string(raw), want) {
		t.Errorf("state file = %s, want it to hold %s", raw, want)
	}
}

func TestSystemStateRebootDebian(t *testing.T) {
	// The Debian family answers through the flag file alone, also with needs-restarting on the path.
	for _, present := range []bool{true, false} {
		t.Run(fmt.Sprintf("flag present %v", present), func(t *testing.T) {
			calls := stubSystemCLI(t, map[string]dockerReply{"apt-get": {}, "needs-restarting": {}})
			stubRebootFlag(t, present)
			logs := captureWarnings(t)
			if required, ok := rebootRequired(context.Background()); required != present || !ok {
				t.Errorf("rebootRequired() = %v, %v; want %v, true", required, ok, present)
			}
			if len(*calls) != 0 {
				t.Errorf("calls = %v, want none", *calls)
			}
			assertSystemStateLog(t, logs.String(), "")
		})
	}
}

func TestSystemStateRebootFlagUnreadable(t *testing.T) {
	// A flag it cannot check is unknown, not "no reboot needed": no field, and the log names why.
	stubSystemCLI(t, map[string]dockerReply{"apt-get": {}})
	file := filepath.Join(t.TempDir(), "file")
	if err := os.WriteFile(file, nil, 0o644); err != nil {
		t.Fatal(err)
	}
	old := rebootRequiredPath
	rebootRequiredPath = filepath.Join(file, "reboot-required")
	t.Cleanup(func() { rebootRequiredPath = old })
	logs := captureWarnings(t)
	if required, ok := rebootRequired(context.Background()); ok {
		t.Errorf("rebootRequired() = %v, true; want no answer", required)
	}
	if !strings.Contains(logs.String(), "not a directory, reboot_required left out") {
		t.Errorf("log = %q, want it to name the stat error", logs.String())
	}
}

func TestSystemStateRebootRPM(t *testing.T) {
	// needs-restarting -r: exit 0 is no reboot, exit 1 a reboot, everything else no answer with the
	// reason in the log, short and without stderr.
	cases := []struct {
		name     string
		err      error
		required bool
		ok       bool
		log      string
	}{
		{"exit 0", nil, false, true, ""},
		{"exit 1", exitStatus(t, 1), true, true, ""},
		{"exit 2", exitStatus(t, 2), false, false,
			"needs-restarting -r failed: exit status 2, reboot_required left out"},
		{"times out", context.DeadlineExceeded, false, false,
			"needs-restarting -r failed: timed out after 15s, reboot_required left out"},
		{"does not start", &exec.Error{Name: "/usr/bin/needs-restarting", Err: exec.ErrNotFound}, false, false,
			"needs-restarting -r failed: needs-restarting did not start, reboot_required left out"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			calls := stubSystemCLI(t, map[string]dockerReply{"needs-restarting": {err: c.err}})
			stubRebootFlag(t, true) // without apt-get the flag file does not count
			logs := captureWarnings(t)
			if required, ok := rebootRequired(context.Background()); required != c.required || ok != c.ok {
				t.Errorf("rebootRequired() = %v, %v; want %v, %v", required, ok, c.required, c.ok)
			}
			if want := [][]string{{"needs-restarting", "-r"}}; !reflect.DeepEqual(*calls, want) {
				t.Errorf("calls = %v, want %v", *calls, want)
			}
			assertSystemStateLog(t, logs.String(), c.log)
		})
	}
}

func TestSystemStateRebootNoTool(t *testing.T) {
	// Neither apt-get nor needs-restarting: no tool to ask, which is no failure. No field, no call,
	// no warning, also with a flag file lying around.
	calls := stubSystemCLI(t, nil)
	stubRebootFlag(t, true)
	logs := captureWarnings(t)
	if required, ok := rebootRequired(context.Background()); ok {
		t.Errorf("rebootRequired() = %v, true; want no answer", required)
	}
	if len(*calls) != 0 {
		t.Errorf("calls = %v, want none", *calls)
	}
	assertSystemStateLog(t, logs.String(), "")
}

func TestSystemStateTimeSync(t *testing.T) {
	const noAnswer = "no NTPSynchronized=yes|no in timedatectl show, time_synchronized left out"
	cases := []struct {
		name   string
		tools  map[string]dockerReply
		synced bool
		ok     bool
		log    string
	}{
		{"synchronized", map[string]dockerReply{"timedatectl": {out: timedatectlShow}}, true, true, ""},
		{"not synchronized", map[string]dockerReply{"timedatectl": {
			out: strings.Replace(timedatectlShow, "NTPSynchronized=yes", "NTPSynchronized=no", 1)}}, false, true, ""},
		// NTP=yes only says the NTP service is enabled.
		{"no NTPSynchronized line", map[string]dockerReply{"timedatectl": {
			out: strings.Replace(timedatectlShow, "NTPSynchronized=yes\n", "", 1)}}, false, false, noAnswer},
		{"another value", map[string]dockerReply{"timedatectl": {
			out: strings.Replace(timedatectlShow, "NTPSynchronized=yes", "NTPSynchronized=maybe", 1)}},
			false, false, noAnswer},
		{"fails", map[string]dockerReply{"timedatectl": {err: exitStatus(t, 1)}}, false, false,
			"timedatectl show failed: exit status 1, time_synchronized left out"},
		{"times out", map[string]dockerReply{"timedatectl": {err: context.DeadlineExceeded}}, false, false,
			"timedatectl show failed: timed out after 15s, time_synchronized left out"},
		{"missing", nil, false, false, "timedatectl not found, time_synchronized left out"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			calls := stubSystemCLI(t, c.tools)
			logs := captureWarnings(t)
			if synced, ok := timeSynchronized(context.Background()); synced != c.synced || ok != c.ok {
				t.Errorf("timeSynchronized() = %v, %v; want %v, %v", synced, ok, c.synced, c.ok)
			}
			want := [][]string{{"timedatectl", "show"}}
			if c.tools == nil {
				want = nil
			}
			if !reflect.DeepEqual(*calls, want) {
				t.Errorf("calls = %v, want %v", *calls, want)
			}
			assertSystemStateLog(t, logs.String(), c.log)
		})
	}
}

func TestSystemStateBlock(t *testing.T) {
	// The answers land in the block next to oom_kills, as JSON booleans and numbers on the wire, and
	// the security update count goes into the state for the hour; with no answer at all the block is
	// empty and stays out of the report.
	t.Run("all measured", func(t *testing.T) {
		stubSystemCLI(t, map[string]dockerReply{"apt-get": {}, "timedatectl": {out: timedatectlShow}})
		stubRebootFlag(t, true)
		stubVMStat(t, vmstatWithOOMKill(5))
		stubUpdates(t, updatesNow, dockerReply{out: aptUbuntuFixture})
		saved := uint64(3)
		block, next := collectSystemState(context.Background(), reportState{OOMKill: &saved})
		want := map[string]any{"oom_kills": 2.0, "reboot_required": true, "time_synchronized": true,
			"security_updates": 2.0}
		if got := dockerWire(t, block); !reflect.DeepEqual(got, want) {
			t.Errorf("block = %v, want %v", got, want)
		}
		if next.Updates == nil || next.Updates.Security == nil || *next.Updates.Security != 2 {
			t.Errorf("state updates = %+v, want the count 2", next.Updates)
		}
	})
	t.Run("security updates from the saved count", func(t *testing.T) {
		stubSystemCLI(t, map[string]dockerReply{"apt-get": {}, "timedatectl": {out: timedatectlShow}})
		stubRebootFlag(t, false)
		stubVMStat(t, "pgmajfault 1042\n")
		calls := stubUpdates(t, updatesNow, dockerReply{out: aptUbuntuFixture})
		five := 5
		saved := &updatesCheck{CheckedUnix: updatesNow.Add(-10 * time.Minute).Unix(), Security: &five}
		block, next := collectSystemState(context.Background(), reportState{Updates: saved})
		want := map[string]any{"reboot_required": false, "time_synchronized": true, "security_updates": 5.0}
		if got := dockerWire(t, block); !reflect.DeepEqual(got, want) || len(*calls) != 0 {
			t.Errorf("block = %v after %d call(s), want %v without one", got, len(*calls), want)
		}
		if next.Updates != saved {
			t.Errorf("state updates = %+v, want the saved count handed on", next.Updates)
		}
	})
	t.Run("nothing measured", func(t *testing.T) {
		stubSystemCLI(t, map[string]dockerReply{"timedatectl": {err: context.DeadlineExceeded}})
		stubVMStat(t, "pgmajfault 1042\n")
		if block, _ := collectSystemState(context.Background(), reportState{}); len(block) != 0 {
			t.Errorf("block = %v, want no field", block)
		}
	})
}

// fakeTools puts each tool of names on the PATH as a script that runs script, and nothing else there:
// no test reaches the host's tools. script calls other programs by absolute path.
func fakeTools(t *testing.T, script string, names ...string) {
	t.Helper()
	dir := t.TempDir()
	for _, name := range names {
		if err := os.WriteFile(filepath.Join(dir, name), []byte("#!/bin/sh\n"+script+"\n"), 0o755); err != nil {
			t.Fatal(err)
		}
	}
	t.Setenv("PATH", dir)
}

// R-0638: a system state tool that does not answer costs the collector the rest of the run's context,
// not its timeout per call (15 s, apt-get and dnf 30 s): the call the deadline ended reports like the
// timeout it is, and no further call starts. lookPath picks the package family; the calls run for real
// against the hanging tools on the PATH. A field whose call the context ended stays out, and the
// update count is saved as failed, so the next hourly count is the next try.
func TestSystemStateEndsAtTheEndOfTheContext(t *testing.T) {
	for name, tc := range map[string]struct {
		family []string
		want   map[string]any
		logs   []string
	}{
		"Debian": {[]string{"apt-get", "timedatectl"}, map[string]any{"reboot_required": true}, []string{
			"timedatectl show failed: timed out after 15s",
			"apt-get -s dist-upgrade failed: timed out after 30s",
		}},
		// Without timedatectl the update count is the first call, the one the deadline ends.
		"Debian, apt-get first": {[]string{"apt-get"}, map[string]any{"reboot_required": true}, []string{
			"apt-get -s dist-upgrade failed: timed out after 30s",
		}},
		"RPM": {[]string{"needs-restarting", "timedatectl", "dnf"}, map[string]any{}, []string{
			"needs-restarting -r failed: timed out after 15s",
			"timedatectl show failed: timed out after 15s",
			"dnf updateinfo list --security failed: timed out after 30s",
		}},
	} {
		t.Run(name, func(t *testing.T) {
			fakeTools(t, "exec /bin/sleep 30", "timedatectl", "needs-restarting", "apt-get", "dnf")
			onPath := map[string]bool{}
			for _, tool := range tc.family {
				onPath[tool] = true
			}
			old := systemCLI.lookPath
			t.Cleanup(func() { systemCLI.lookPath = old })
			systemCLI.lookPath = func(file string) (string, error) {
				if onPath[file] {
					return "/usr/bin/" + file, nil
				}
				return "", exec.ErrNotFound
			}
			stubRebootFlag(t, true)
			stubVMStat(t, "pgmajfault 1042\n")
			logs := captureWarnings(t)
			ctx, cancel := context.WithTimeout(context.Background(), 300*time.Millisecond)
			defer cancel()
			var block map[string]any
			var next reportState
			endsWithin(t, 3*time.Second, func() { block, next = collectSystemState(ctx, reportState{}) })
			if !reflect.DeepEqual(block, tc.want) {
				t.Errorf("block = %v, want %v", block, tc.want)
			}
			if next.Updates == nil || next.Updates.Security != nil {
				t.Errorf("state updates = %+v, want the count saved as failed", next.Updates)
			}
			for _, want := range tc.logs {
				if !strings.Contains(logs.String(), want) {
					t.Errorf("log = %q, want it to name %q", logs.String(), want)
				}
			}
		})
	}
}
