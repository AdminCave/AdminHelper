// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"
)

// stubSystemctl answers each systemctl call by its first arguments (list-units, or show with its
// property list), checks it against the allowlist and records it.
func stubSystemctl(t *testing.T, answers map[string]string, calls *[][]string) {
	t.Helper()
	old := runTool
	runTool = func(_ context.Context, _ time.Duration, name string, args ...string) ([]byte, error) {
		checkAllowed(t, name, args)
		*calls = append(*calls, append([]string{name}, args...))
		key := args[0]
		if key == "show" {
			key += " " + args[2]
		}
		out, ok := answers[key]
		if !ok {
			t.Fatalf("unexpected call %v", args)
		}
		return []byte(out), nil
	}
	t.Cleanup(func() { runTool = old })
}

func TestSystemdTimersCountsActiveTimersAndFailedRuns(t *testing.T) {
	var calls [][]string
	stubSystemctl(t, map[string]string{
		"list-units": "apt-daily.timer loaded active waiting Daily apt download activities\n" +
			"backup.timer loaded active waiting Nightly backup\n" +
			"fstrim.timer loaded active waiting Discard unused filesystem blocks once a week\n" +
			"skip.timer loaded active waiting Runs only on AC power\n" +
			"old.timer not-found inactive dead old.timer\n" +
			"manual.timer loaded inactive dead Manual job\n",
		"show Id,Triggers": "Id=apt-daily.timer\nTriggers=apt-daily.service\n\n" +
			"Id=backup.timer\nTriggers=backup.service\n\n" +
			"Id=fstrim.timer\nTriggers=fstrim.service\n\n" +
			"Id=skip.timer\nTriggers=skip.service\n",
		"show Id,Result": "Result=success\nId=apt-daily.service\n\n" +
			"Result=exit-code\nId=backup.service\n\n" +
			"Result=timeout\nId=fstrim.service\n\n" +
			"Result=exec-condition\nId=skip.service\n",
	}, &calls)
	got, err := systemdTimers(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if want := map[string]any{"timers": 4, "failed": 2}; !reflect.DeepEqual(got, want) {
		t.Errorf("timers %v, want %v", got, want)
	}
	if last := calls[len(calls)-1]; !reflect.DeepEqual(last[5:], []string{"apt-daily.service", "backup.service", "fstrim.service", "skip.service"}) {
		t.Errorf("asked %v, want the triggered services", last)
	}
}

func TestSystemdTimersWithoutTimersAsksNothingMore(t *testing.T) {
	var calls [][]string
	stubSystemctl(t, map[string]string{"list-units": ""}, &calls)
	got, err := systemdTimers(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if got["timers"] != 0 || got["failed"] != 0 || len(calls) != 1 {
		t.Errorf("timers %v after %d calls, want zero after one", got, len(calls))
	}
}

func TestSystemdTimersWithoutSystemctlIsUnsupported(t *testing.T) {
	old := runTool
	runTool = func(context.Context, time.Duration, string, ...string) ([]byte, error) {
		return nil, exec.ErrNotFound
	}
	t.Cleanup(func() { runTool = old })
	if _, err := systemdTimers(context.Background()); !errors.Is(err, ErrUnsupported) {
		t.Errorf("err %v, want ErrUnsupported", err)
	}
}

// stubKernel points the taint file and the livepatch tree at fresh files (path below the temp root
// → content); a taint of "" leaves the taint file out.
func stubKernel(t *testing.T, taint string, patches map[string]string) {
	t.Helper()
	root := t.TempDir()
	oldTaint, oldPatch := procTainted, sysLivepatch
	procTainted = filepath.Join(root, "tainted")
	sysLivepatch = filepath.Join(root, "livepatch")
	t.Cleanup(func() { procTainted, sysLivepatch = oldTaint, oldPatch })
	if taint != "" {
		if err := os.WriteFile(procTainted, []byte(taint+"\n"), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	for name, state := range patches {
		dir := filepath.Join(sysLivepatch, name)
		if err := os.MkdirAll(dir, 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(dir, "transition"), []byte(state+"\n"), 0o644); err != nil {
			t.Fatal(err)
		}
	}
}

func TestKernelTaintDecodesTheBitsThatMatter(t *testing.T) {
	// 4609 = P, W, O (the example of tainted-kernels.rst): tainted, but no crash or hardware fault.
	stubKernel(t, "4609", map[string]string{"kpatch_1": "0", "kpatch_2": "1"})
	got, err := kernelTaint(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]any{
		"tainted": uint64(4609), "oops": false, "mce": false, "bad_page": false, "livepatch_transition": 1,
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("kernel %v, want %v", got, want)
	}

	// D (128) + M (16) + B (32).
	stubKernel(t, "176", nil)
	got, err = kernelTaint(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if got["oops"] != true || got["mce"] != true || got["bad_page"] != true || got["livepatch_transition"] != 0 {
		t.Errorf("kernel %v, want oops, mce and bad_page", got)
	}
}

func TestKernelTaintWithoutTheProcFileIsUnsupported(t *testing.T) {
	stubKernel(t, "", nil)
	if _, err := kernelTaint(context.Background()); !errors.Is(err, ErrUnsupported) {
		t.Errorf("err %v, want ErrUnsupported", err)
	}
}

func TestKernelTaintRefusesATaintOfAnotherForm(t *testing.T) {
	stubKernel(t, "-1", nil)
	_, err := kernelTaint(context.Background())
	if err == nil || !strings.Contains(err.Error(), "another form") {
		t.Errorf("err %v, want a taint of another form", err)
	}
}

func TestHostSensorKnowsTheLinuxExtras(t *testing.T) {
	stubKernel(t, "0", nil)
	got, err := hostSensor(context.Background(), Probe{Sensor: "host", Params: map[string]any{"view": "kernel_taint"}}, "")
	if err != nil {
		t.Fatal(err)
	}
	if got["tainted"] != uint64(0) {
		t.Errorf("host kernel_taint %v, want an untainted kernel", got)
	}
}
