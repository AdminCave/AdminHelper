// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"reflect"
	"runtime"
	"strconv"
	"strings"
	"testing"
	"time"
	"unicode/utf8"

	"adminhelper-agent/internal/execx"
)

// toolHelperEnv tells TestHelperToolProcess, run as a child process, which status to exit with and what
// to write to stderr: "<status>:<stderr>".
const toolHelperEnv = "AH_PROBE_TOOL_HELPER"

// TestHelperToolProcess is no test of its own: toolExit starts the test binary as its child process,
// which writes to stderr and exits as toolHelperEnv says. Without it, it returns at once.
func TestHelperToolProcess(t *testing.T) {
	code, stderr, ok := strings.Cut(os.Getenv(toolHelperEnv), ":")
	n, err := strconv.Atoi(code)
	if !ok || err != nil {
		return
	}
	fmt.Fprint(os.Stderr, stderr)
	os.Exit(n)
}

// toolExit returns what runTool reports for a tool that writes stderr and exits with code: the real
// *exec.ExitError of a child process, on every platform.
func toolExit(t *testing.T, code int, stderr string) error {
	t.Helper()
	t.Setenv(toolHelperEnv, strconv.Itoa(code)+":"+stderr)
	_, err := execx.Run(context.Background(), time.Minute, os.Args[0], "-test.run=^TestHelperToolProcess$")
	var exitErr *exec.ExitError
	if !errors.As(err, &exitErr) || exitErr.ExitCode() != code {
		t.Fatalf("helper process: err = %v, want an ExitError with status %d", err, code)
	}
	return err
}

// notInstalled is what runTool reports for a tool name that is not on the PATH.
func notInstalled(name string) error {
	return &exec.Error{Name: name, Err: exec.ErrNotFound}
}

// answer is what a call of runTool returns.
type answer struct {
	out string
	err error
}

// stubTools puts in a runTool that answers its calls in turn and records each one's name and arguments;
// a call past the answers fails the test.
func stubTools(t *testing.T, answers ...answer) *[][]string {
	t.Helper()
	var calls [][]string
	old := runTool
	runTool = func(_ context.Context, _ time.Duration, name string, args ...string) ([]byte, error) {
		calls = append(calls, append([]string{name}, args...))
		checkAllowed(t, name, args)
		if len(calls) > len(answers) {
			t.Errorf("call %q past the %d answers", calls[len(calls)-1], len(answers))
			return nil, errors.New("no answer")
		}
		a := answers[len(calls)-1]
		return []byte(a.out), a.err
	}
	t.Cleanup(func() { runTool = old })
	return &calls
}

// stubJournalHere makes this host one with a journal (err nil) or one without.
func stubJournalHere(t *testing.T, err error) {
	t.Helper()
	old := journalHere
	journalHere = func() error { return err }
	t.Cleanup(func() { journalHere = old })
}

// journalArgs are the arguments every call of journalctl starts with, at priority.
func journalArgs(priority int, more ...string) []string {
	return append([]string{"journalctl", "--no-pager", "--quiet", "--output=cat", "--output-fields=PRIORITY",
		"--show-cursor", "--priority=" + strconv.Itoa(priority)}, more...)
}

func logProbe(params map[string]any) Probe {
	return Probe{ID: "chk-log", Sensor: "log", IntervalS: 300, TimeoutS: 5, Params: params, Fields: []string{"count"}}
}

func TestTheSqlAndLogSensorsAreRegistered(t *testing.T) {
	if sensors["sql"] == nil {
		t.Error("sensor sql is not registered")
	}
	if cursorSensors["log"] == nil || sensors["log"] != nil {
		t.Error("sensor log is not registered as a counting sensor alone")
	}
}

func TestTheLogSensorCountsTheEntriesAfterItsCursor(t *testing.T) {
	stubJournalHere(t, nil)
	calls := stubTools(t, answer{out: "4\n3\n\n4\n-- cursor: s=abc;i=2\n"})
	p := logProbe(map[string]any{"unit": "nginx.service", "priority": float64(4), "match": "SYSLOG_IDENTIFIER=nginx"})

	values, next, err := logSensor(context.Background(), p, "s=old;i=1")

	if err != nil {
		t.Fatal(err)
	}
	want := journalArgs(4, "--unit=nginx.service", "--after-cursor=s=old;i=1", "--", "SYSLOG_IDENTIFIER=nginx")
	if !reflect.DeepEqual(*calls, [][]string{want}) {
		t.Fatalf("calls = %q, want %q", *calls, want)
	}
	if !reflect.DeepEqual(values, map[string]any{"count": 3}) || next != "s=abc;i=2" {
		t.Errorf("values = %v, cursor %q; want 3 entries (an entry without priority is none) and the last cursor",
			values, next)
	}
}

func TestTheLogSensorWithoutACursorCountsTheProbesInterval(t *testing.T) {
	stubJournalHere(t, nil)
	calls := stubTools(t, answer{out: "3\n-- cursor: s=new\n"})

	values, next, err := logSensor(context.Background(), logProbe(nil), "")

	if err != nil {
		t.Fatal(err)
	}
	if want := journalArgs(3, "--since=-300s"); !reflect.DeepEqual(*calls, [][]string{want}) {
		t.Fatalf("calls = %q, want %q (err and worse, all units)", *calls, want)
	}
	if values["count"] != 1 || next != "s=new" {
		t.Errorf("values = %v, cursor %q; want 1 and s=new", values, next)
	}
}

func TestTheLogSensorWithoutNewEntriesKeepsItsCursor(t *testing.T) {
	stubJournalHere(t, nil)
	stubTools(t, answer{}, answer{})

	values, next, err := logSensor(context.Background(), logProbe(nil), "s=old")
	_, none, errNone := logSensor(context.Background(), logProbe(nil), "")

	if err != nil || errNone != nil {
		t.Fatal(err, errNone)
	}
	if values["count"] != 0 || next != "s=old" || none != "" {
		t.Errorf("values = %v, cursors %q and %q; want 0, the old cursor and still none", values, next, none)
	}
}

func TestTheLogSensorTakesTheCursorFromTheLastLineAlone(t *testing.T) {
	stubJournalHere(t, nil)
	long := cursorLine + strings.Repeat("x", maxCursorBytes+1)
	cases := []struct {
		name, out, wantNext string
		wantCount           int
	}{
		{"a line like a cursor before it", "-- cursor: s=fake\n3\n-- cursor: s=real\n", "s=real", 2},
		{"no cursor last", "3\n-- cursor: s=fake\n3\n", "s=old", 3},
		{"a cursor past its size", "3\n" + long + "\n", "s=old", 1},
		{"a cursor with a space", "3\n-- cursor: s=a b\n", "s=old", 1},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			stubTools(t, answer{out: c.out})

			values, next, err := logSensor(context.Background(), logProbe(nil), "s=old")

			if err != nil {
				t.Fatal(err)
			}
			if values["count"] != c.wantCount || next != c.wantNext {
				t.Errorf("values = %v, cursor %q; want %d and %q", values, next, c.wantCount, c.wantNext)
			}
		})
	}
}

func TestTheLogSensorCountsTheIntervalWhenItsCursorFails(t *testing.T) {
	stubJournalHere(t, nil)
	calls := stubTools(t,
		answer{err: toolExit(t, 1, "Failed to seek to cursor: Invalid argument")},
		answer{out: "3\n-- cursor: s=new\n"})

	values, next, err := logSensor(context.Background(), logProbe(nil), "s=gone")

	if err != nil {
		t.Fatal(err)
	}
	want := [][]string{journalArgs(3, "--after-cursor=s=gone"), journalArgs(3, "--since=-300s")}
	if !reflect.DeepEqual(*calls, want) {
		t.Fatalf("calls = %q, want %q", *calls, want)
	}
	if values["count"] != 1 || next != "s=new" {
		t.Errorf("values = %v, cursor %q; want 1 and s=new", values, next)
	}
}

func TestTheLogSensorDropsItsCursorOnAnError(t *testing.T) {
	stubJournalHere(t, nil)
	failed := toolExit(t, 1, "Failed to open journal: Permission denied\nmore")
	calls := stubTools(t, answer{err: failed}, answer{err: failed}, answer{err: failed})

	values, next, err := logSensor(context.Background(), logProbe(nil), "s=old")
	_, _, errNone := logSensor(context.Background(), logProbe(nil), "")

	if err == nil || values != nil || next != "" {
		t.Fatalf("values = %v, cursor %q, err %v; want an error and no cursor", values, next, err)
	}
	if want := "journalctl: Failed to open journal: Permission denied (exit status 1)"; err.Error() != want {
		t.Errorf("error = %q, want %q", err, want)
	}
	if errors.Is(err, ErrUnsupported) || errNone == nil {
		t.Errorf("errors = %v and %v, want plain errors both", err, errNone)
	}
	if len(*calls) != 3 {
		t.Errorf("calls = %q, want one with the cursor and two without", *calls)
	}
}

func TestTheLogSensorCountsTheIntervalOnlyWhenJournalctlRefusedTheCursor(t *testing.T) {
	stubJournalHere(t, nil)
	ended, cancel := context.WithCancel(context.Background())
	cancel()
	cases := []struct {
		name string
		ctx  context.Context
		err  error
	}{
		{"the run ended", ended, context.Canceled},
		{"journalctl timed out", context.Background(), context.DeadlineExceeded},
		{"journalctl is not installed", context.Background(), notInstalled("journalctl")},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			calls := stubTools(t, answer{err: c.err})

			_, next, err := logSensor(c.ctx, logProbe(nil), "s=old")

			if err == nil || next != "" || len(*calls) != 1 {
				t.Errorf("err = %v, cursor %q after %d calls; want an error and no cursor after one", err, next, len(*calls))
			}
		})
	}
}

func TestTheLogSensorWithoutAJournalIsUnsupported(t *testing.T) {
	cases := []struct {
		name string
		here error
		tool error
		want string
	}{
		{"no journal", fmt.Errorf("%w: systemd does not run this host", ErrUnsupported), nil,
			"systemd does not run this host"},
		{"no journalctl", nil, notInstalled("journalctl"), "journalctl is not installed"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			stubJournalHere(t, c.here)
			stubTools(t, answer{err: c.tool})

			_, _, err := logSensor(context.Background(), logProbe(nil), "s=old")

			if !errors.Is(err, ErrUnsupported) || !strings.Contains(err.Error(), c.want) {
				t.Errorf("err = %v, want unsupported: %s", err, c.want)
			}
		})
	}
}

func TestJournalOfThisHostIsLinuxAlone(t *testing.T) {
	err := journalOfThisHost()
	if err != nil && !errors.Is(err, ErrUnsupported) {
		t.Fatalf("err = %v, want none or unsupported", err)
	}
	if runtime.GOOS != "linux" && err == nil {
		t.Error("a host without Linux has a journal, want unsupported")
	}
}

func TestTheLogSensorRefusesParamsOfAnotherForm(t *testing.T) {
	stubJournalHere(t, nil)
	cases := []struct {
		name   string
		params map[string]any
		target *Target
	}{
		{"a target", nil, &Target{Kind: kindLoopback, PortHint: 80}},
		{"an unknown param", map[string]any{"grep": "x"}, nil},
		{"a unit glob", map[string]any{"unit": "nginx*"}, nil},
		{"a unit with a space", map[string]any{"unit": "a b.service"}, nil},
		{"a unit of no text", map[string]any{"unit": 5.0}, nil},
		{"priority 8", map[string]any{"priority": 8.0}, nil},
		{"priority -1", map[string]any{"priority": -1.0}, nil},
		{"priority 2.5", map[string]any{"priority": 2.5}, nil},
		{"priority as text", map[string]any{"priority": "3"}, nil},
		{"a match on what was logged", map[string]any{"match": "MESSAGE=password"}, nil},
		{"a match on another field", map[string]any{"match": "_PID=1"}, nil},
		{"a match with a space", map[string]any{"match": "SYSLOG_IDENTIFIER=a b"}, nil},
		{"a match without value", map[string]any{"match": "_COMM="}, nil},
		{"a match of two", map[string]any{"match": "_COMM=a _COMM=b"}, nil},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			calls := stubTools(t)
			p := logProbe(c.params)
			p.Target = c.target

			_, _, err := logSensor(context.Background(), p, "s=old")

			if !errors.Is(err, ErrInvalid) || len(*calls) != 0 {
				t.Errorf("err = %v after %d calls, want invalid before journalctl", err, len(*calls))
			}
		})
	}
}

func TestTheLogSensorTakesUnitsAndMatchesOfEveryForm(t *testing.T) {
	stubJournalHere(t, nil)
	for _, params := range []map[string]any{
		{"unit": `systemd-fsck@dev-disk-by\x2duuid-1.service`, "priority": 0.0},
		{"unit": "getty@tty1.service", "priority": 7.0},
		{"match": "_COMM=php-fpm8.4"},
		{"match": "CONTAINER_NAME=web_1"},
		{"match": "SYSLOG_IDENTIFIER=postfix/smtpd"},
	} {
		stubTools(t, answer{})
		if _, _, err := logSensor(context.Background(), logProbe(params), ""); err != nil {
			t.Errorf("params %v: %v", params, err)
		}
	}
}

func TestTheLogProbeCountsOnFromRunToRun(t *testing.T) {
	stubJournalHere(t, nil)
	calls := stubTools(t, answer{out: "3\n-- cursor: s=1\n"}, answer{out: "3\n3\n-- cursor: s=2\n"})
	acc := &Access{}
	p := logProbe(nil)

	first := Run(context.Background(), p, start, acc)
	second := Run(context.Background(), p, start, acc)

	if first.Status != StatusOK || first.Values["count"] != 1 || second.Values["count"] != 2 {
		t.Fatalf("results = %+v and %+v, want counts 1 and 2", first, second)
	}
	want := [][]string{journalArgs(3, "--since=-300s"), journalArgs(3, "--after-cursor=s=1")}
	if !reflect.DeepEqual(*calls, want) {
		t.Errorf("calls = %q, want %q", *calls, want)
	}
	if acc.Cursors["chk-log"] != "s=2" {
		t.Errorf("cursors = %v, want chk-log at s=2", acc.Cursors)
	}
}

func TestToolErrorQuotesTheFirstLineOfTheToolsStderr(t *testing.T) {
	long := strings.Repeat("ä", maxToolLineRunes+40)
	cases := []struct {
		name string
		err  error
		want string
	}{
		{"the first line", toolExit(t, 2, "  first\nsecond\n"), "x: first (exit status 2)"},
		{"without the tool's name", toolExit(t, 2, "x: first"), "x: first (exit status 2)"},
		{"no stderr", toolExit(t, 2, ""), "x: exit status 2"},
		{"no value after a =", toolExit(t, 7, "x: unknown variable 'pasword=s3cr=et'\n"),
			"x: unknown variable 'pasword=… (exit status 7)"},
		{"a long line", toolExit(t, 2, long), "x: " + strings.Repeat("ä", maxToolLineRunes) + " (exit status 2)"},
		{"no exit", context.DeadlineExceeded, "x: context deadline exceeded"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			err := toolError("x", c.err)

			if err.Error() != c.want || !errors.Is(err, c.err) {
				t.Errorf("error = %q, want %q wrapping %v", err, c.want, c.err)
			}
			if !utf8.ValidString(err.Error()) {
				t.Errorf("error = %q, want valid UTF-8", err)
			}
		})
	}
}
