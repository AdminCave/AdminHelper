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
	"slices"
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

// stubPackageTools answers needrestart, dpkg and apt-mark by their command name, checks each call
// against the allowlist and that it runs with LC_ALL=C; an answer of nil stands for a missing tool.
func stubPackageTools(t *testing.T, answers map[string][]byte) {
	t.Helper()
	old := runToolEnv
	runToolEnv = func(_ context.Context, _ time.Duration, env []string, name string, args ...string) ([]byte, error) {
		checkAllowed(t, name, args)
		if !slices.Equal(env, []string{"LC_ALL=C"}) {
			t.Errorf("%s runs with env %q, want LC_ALL=C", name, env)
		}
		out, ok := answers[name]
		if !ok {
			t.Fatalf("unexpected call %s %v", name, args)
		}
		if out == nil {
			return nil, exec.ErrNotFound
		}
		return out, nil
	}
	t.Cleanup(func() { runToolEnv = old })
}

func TestNeedrestartReadsTheBatchLines(t *testing.T) {
	// The form of needrestart 3.11 -b (README.batch), with one service, a container and a session.
	stubPackageTools(t, map[string][]byte{"needrestart": []byte("NEEDRESTART-VER: 3.11\n" +
		"NEEDRESTART-KCUR: 6.12.48+deb13-amd64\nNEEDRESTART-KEXP: 6.12.57+deb13-amd64\n" +
		"NEEDRESTART-KSTA: 3\nNEEDRESTART-UCSTA: 2\nNEEDRESTART-UCCUR: 0x000000f0\n" +
		"NEEDRESTART-SVC: nginx.service\nNEEDRESTART-SVC: ssh.service\n" +
		"NEEDRESTART-CONT: LXC web\nNEEDRESTART-SESS: kevin @ session #3\n")})
	got, err := needrestartStatus(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if want := map[string]any{"kernel_status": 3, "microcode_status": 2, "services": 2}; !reflect.DeepEqual(got, want) {
		t.Errorf("needrestart %v, want %v", got, want)
	}

	stubPackageTools(t, map[string][]byte{"needrestart": []byte("NEEDRESTART-VER: 3.11\nNEEDRESTART-KCUR: 6.12\n" +
		"NEEDRESTART-KSTA: 1\nNEEDRESTART-UCSTA: 0\n")})
	got, err = needrestartStatus(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if want := map[string]any{"kernel_status": 1, "microcode_status": 0, "services": 0}; !reflect.DeepEqual(got, want) {
		t.Errorf("needrestart %v, want %v", got, want)
	}

	// In a container needrestart 3.11 skips the kernel and the microcode check, in a VM the microcode
	// check, and prints neither status line: both read as its 0, unknown, not as an error.
	for _, out := range []string{"NEEDRESTART-VER: 3.11\n", "NEEDRESTART-VER: 3.11\nNEEDRESTART-KCUR: 6.12\nNEEDRESTART-KSTA: 1\n"} {
		stubPackageTools(t, map[string][]byte{"needrestart": []byte(out)})
		got, err = needrestartStatus(context.Background())
		if err != nil {
			t.Fatal(err)
		}
		kernel := 0
		if strings.Contains(out, "KSTA") {
			kernel = 1
		}
		if want := map[string]any{"kernel_status": kernel, "microcode_status": 0, "services": 0}; !reflect.DeepEqual(got, want) {
			t.Errorf("needrestart on %q: %v, want %v", out, got, want)
		}
	}
}

func TestNeedrestartRefusesAnotherForm(t *testing.T) {
	for _, out := range []string{"", "NEEDRESTART-KSTA: 1\n", "NEEDRESTART-VER: 3.11\nNEEDRESTART-KSTA: high\n"} {
		stubPackageTools(t, map[string][]byte{"needrestart": []byte(out)})
		if _, err := needrestartStatus(context.Background()); err == nil || errors.Is(err, ErrUnsupported) {
			t.Errorf("needrestart on %q: err %v, want an error of form", out, err)
		}
	}
	stubPackageTools(t, map[string][]byte{"needrestart": nil})
	if _, err := needrestartStatus(context.Background()); !errors.Is(err, ErrUnsupported) {
		t.Errorf("err %v, want ErrUnsupported", err)
	}
}

// dpkgAudit is the answer of dpkg 1.22 --audit with one half-configured package (probed on Debian
// trixie): a heading of three lines, the package line indented by one space, a blank line.
const dpkgAudit = "The following packages are only half configured, probably due to problems\n" +
	"configuring them the first time.  The configuration should be retried using\n" +
	"dpkg --configure <package> or the configure menu option in dselect:\n" +
	" ahprobe              probe package for audit\n" +
	"  continued description of it\n\n"

// stubUULog points the unattended-upgrades log at a fresh file with content; nil leaves it out.
func stubUULog(t *testing.T, content []byte) string {
	t.Helper()
	old := uuLog
	uuLog = filepath.Join(t.TempDir(), "unattended-upgrades.log")
	t.Cleanup(func() { uuLog = old })
	if content != nil {
		if err := os.WriteFile(uuLog, content, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	return uuLog
}

func TestAptStateCountsAndReadsTheLastRun(t *testing.T) {
	stubPackageTools(t, map[string][]byte{"dpkg": []byte(dpkgAudit), "apt-mark": []byte("linux-image-amd64\nnginx\n")})
	// The first run failed; the last, two hours later, logged one error of its own.
	stubUULog(t, []byte("2026-11-14 06:10:01,512 INFO Starting unattended upgrades script\n"+
		"2026-11-14 06:12:40,001 ERROR Installing the upgrades failed!\n"+
		"2026-11-14 06:12:40,002 ERROR error message: E:Sub-process returned an error code\n"+
		"Traceback (most recent call last):\n"+
		"2026-11-14 08:15:00,000 INFO Starte das Skript für unbeaufsichtigte Aktualisierungen\n"+
		"2026-11-14 08:15:30,250 WARNING Ein Paket wurde zurückgehalten\n"+
		"2026-11-14 08:16:02,700 ERROR dpkg returned a error!\n"+
		"2026-11-14 08:16:03,000 INFO All upgrades installed\n"))
	stubNow(t, time.Date(2026, 11, 14, 9, 16, 3, 0, time.Local))
	got, err := aptState(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]any{"audit": 1, "held": 2, "uu_last_run_age_s": int64(3600), "uu_errors": 1}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("apt_state %v, want %v", got, want)
	}
}

func TestAptStateWithoutTheLogHasNoRunFields(t *testing.T) {
	stubPackageTools(t, map[string][]byte{"dpkg": []byte(""), "apt-mark": []byte("")})
	stubUULog(t, nil)
	got, err := aptState(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if want := map[string]any{"audit": 0, "held": 0}; !reflect.DeepEqual(got, want) {
		t.Errorf("apt_state %v, want %v", got, want)
	}
}

func TestAptStateFallsBackToTheLogsTime(t *testing.T) {
	stubPackageTools(t, map[string][]byte{"dpkg": []byte(""), "apt-mark": []byte("")})
	log := stubUULog(t, []byte("a line of another form\n"))
	at := time.Date(2026, 11, 10, 6, 0, 0, 0, time.Local)
	if err := os.Chtimes(log, at, at); err != nil {
		t.Fatal(err)
	}
	stubNow(t, at.Add(3*24*time.Hour))
	got, err := aptState(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if got["uu_last_run_age_s"] != int64(3*24*3600) || got["uu_errors"] != 0 {
		t.Errorf("apt_state %v, want the log's age and no error", got)
	}
}

func TestAptStateWithoutDpkgIsUnsupported(t *testing.T) {
	stubPackageTools(t, map[string][]byte{"dpkg": nil})
	if _, err := aptState(context.Background()); !errors.Is(err, ErrUnsupported) {
		t.Errorf("err %v, want ErrUnsupported", err)
	}
}
