// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

// timerListArgs list the timer units systemd has loaded, one per line: unit, load, active, sub,
// description. --full keeps a long unit name whole; list-timers is not used, its columns are dates
// with spaces in them.
var timerListArgs = []string{"list-units", "--type=timer", "--all", "--full", "--no-legend", "--plain", "--no-pager"}

// systemdTimers counts the active timers of this host and the units they trigger whose last run
// failed (Result is not "success", org.freedesktop.systemd1(5)). A unit that never ran has
// Result=success, and one whose ExecCondition= told it to skip has Result=exec-condition, which
// systemd.service(5) does not count as failed: both are fine. No unit name leaves it.
func systemdTimers(ctx context.Context) (map[string]any, error) {
	out, err := runTool(ctx, toolTimeout, "systemctl", timerListArgs...)
	switch {
	case errors.Is(err, exec.ErrNotFound):
		return nil, fmt.Errorf("%w: systemctl is not installed", ErrUnsupported)
	case err != nil:
		return nil, toolError("systemctl", err)
	}
	var timers []string
	for _, line := range strings.Split(string(out), "\n") {
		f := strings.Fields(line)
		// A timer named by another unit but without a unit file is listed "not-found"; a stopped one
		// "inactive": neither runs anything.
		if len(f) >= 3 && strings.HasSuffix(f[0], ".timer") && f[1] == "loaded" && f[2] == "active" {
			timers = append(timers, f[0])
		}
	}
	failed := 0
	if len(timers) > 0 {
		out, err := runTool(ctx, toolTimeout, "systemctl", append([]string{"show", "-p", "Id,Triggers", "--"}, timers...)...)
		if err != nil {
			return nil, toolError("systemctl", err)
		}
		seen := map[string]bool{}
		var triggered []string
		for _, props := range showBlocks(out) {
			for _, unit := range strings.Fields(props["Triggers"]) {
				if !seen[unit] {
					seen[unit] = true
					triggered = append(triggered, unit)
				}
			}
		}
		if len(triggered) > 0 {
			out, err := runTool(ctx, toolTimeout, "systemctl", append([]string{"show", "-p", "Id,Result", "--"}, triggered...)...)
			if err != nil {
				return nil, toolError("systemctl", err)
			}
			for _, props := range showBlocks(out) {
				if r := props["Result"]; r != "" && r != "success" && r != "exec-condition" {
					failed++
				}
			}
		}
	}
	return map[string]any{"timers": len(timers), "failed": failed}, nil
}

// showBlocks splits the output of `systemctl show` into its blank-line-separated blocks, one per
// unit, each as its properties.
func showBlocks(out []byte) []map[string]string {
	var blocks []map[string]string
	for _, block := range strings.Split(strings.TrimSpace(string(out)), "\n\n") {
		props := map[string]string{}
		for _, line := range strings.Split(block, "\n") {
			if k, v, ok := strings.Cut(strings.TrimSpace(line), "="); ok {
				props[k] = v
			}
		}
		if len(props) > 0 {
			blocks = append(blocks, props)
		}
	}
	return blocks
}

// procTainted and sysLivepatch are where the kernel reports its taint and its live patches; tests
// point them at files of their own.
var (
	procTainted  = "/proc/sys/kernel/tainted"
	sysLivepatch = "/sys/kernel/livepatch"
)

// Taint bits (docs.kernel.org admin-guide/tainted-kernels): D the kernel died (OOPS or BUG), M a
// machine check exception, B a bad page.
const (
	taintMCE     = 1 << 4
	taintBadPage = 1 << 5
	taintOops    = 1 << 7
)

// kernelTaint reads the taint of the running kernel and how many live patches are in transition
// (livepatch.rst: the patch's transition file shows 1 while tasks still wait for it). Both are only
// opened for reading. tainted is the raw bit field (sticky until the next boot); oops, mce and
// bad_page are its bits that point at failing hardware or a crashed kernel. A host without the proc
// file (no Linux) is unsupported, one without live patching reports zero.
func kernelTaint(_ context.Context) (map[string]any, error) {
	raw, err := os.ReadFile(procTainted)
	if errors.Is(err, fs.ErrNotExist) {
		return nil, fmt.Errorf("%w: this host has no kernel taint file", ErrUnsupported)
	}
	if err != nil {
		return nil, errors.New("kernel: the taint cannot be read")
	}
	taint, err := strconv.ParseUint(strings.TrimSpace(string(raw)), 10, 64)
	if err != nil {
		return nil, errors.New("kernel: a taint of another form")
	}
	files, err := filepath.Glob(filepath.Join(sysLivepatch, "*", "transition"))
	if err != nil {
		return nil, err
	}
	transition := 0
	for _, file := range files {
		state, err := os.ReadFile(file)
		if errors.Is(err, fs.ErrNotExist) {
			continue // the patch was disabled since the glob, its directory is gone
		}
		if err != nil {
			return nil, errors.New("kernel: a livepatch state cannot be read")
		}
		if strings.TrimSpace(string(state)) == "1" {
			transition++
		}
	}
	return map[string]any{
		"tainted":              taint,
		"oops":                 taint&taintOops != 0,
		"mce":                  taint&taintMCE != 0,
		"bad_page":             taint&taintBadPage != 0,
		"livepatch_transition": transition,
	}, nil
}

// needrestartTimeout caps `needrestart -b`, which reads the maps of every process in /proc and so
// takes longer than the other tools on a busy host: the 30 s a probe may take at most (catalog
// timeout_s), which its check sets.
const needrestartTimeout = 30 * time.Second

// needrestartStatus asks needrestart in batch mode (README.batch: it never shows a dialog nor
// restarts anything) whether the running kernel and microcode are current and how many services
// still run with replaced libraries. kernel_status is NEEDRESTART-KSTA (0 unknown, 1 current, 2 an
// ABI-compatible upgrade pending, 3 a version upgrade pending), microcode_status NEEDRESTART-UCSTA
// (0 unknown, 1 current, 2 obsolete), services the count of NEEDRESTART-SVC lines. In a container
// needrestart skips the kernel check, in a container or VM the microcode check, and prints no
// status line then: a missing one is its own 0, unknown. Every batch answer begins with
// NEEDRESTART-VER, one without it is of another form. No unit name leaves it.
func needrestartStatus(ctx context.Context) (map[string]any, error) {
	out, err := runToolEnv(ctx, needrestartTimeout, []string{"LC_ALL=C"}, "needrestart", "-b")
	switch {
	case errors.Is(err, exec.ErrNotFound):
		return nil, fmt.Errorf("%w: needrestart is not installed", ErrUnsupported)
	case err != nil:
		return nil, toolError("needrestart", err)
	}
	fields := map[string]string{"NEEDRESTART-KSTA": "kernel_status", "NEEDRESTART-UCSTA": "microcode_status"}
	values := map[string]any{"kernel_status": 0, "microcode_status": 0}
	services, batch := 0, false
	for _, line := range strings.Split(string(out), "\n") {
		key, value, ok := strings.Cut(strings.TrimSpace(line), ": ")
		if !ok {
			continue
		}
		if key == "NEEDRESTART-VER" {
			batch = true
		} else if key == "NEEDRESTART-SVC" {
			services++
		} else if field, ok := fields[key]; ok {
			n, err := strconv.Atoi(strings.TrimSpace(value))
			if err != nil {
				return nil, errors.New("needrestart: a status of another form")
			}
			values[field] = n
		}
	}
	if !batch {
		return nil, errors.New("needrestart: an answer of another form")
	}
	values["services"] = services
	return values, nil
}

// uuLog is the log of unattended-upgrades (its _setup_logging: Unattended-Upgrade::LogDir and
// ::LogFile, Debian's defaults); tests point it at a file of their own.
var uuLog = "/var/log/unattended-upgrades/unattended-upgrades.log"

const (
	// uuLogTail caps what is read from the end of the log: a run writes a few dozen lines.
	uuLogTail = 64 << 10
	// uuRunGap separates two runs in the log: its start line is translated, so a run is told by the
	// pause before it. The timer runs it once a day, a run itself logs at least every few minutes.
	uuRunGap = time.Hour
	// uuTimeLayout is logging's asctime (basicConfig with format '%(asctime)s %(levelname)s
	// %(message)s', the default date format), in local time.
	uuTimeLayout = "2006-01-02 15:04:05,000"
)

// aptState counts the packages dpkg finds broken (`dpkg --audit`: a package line begins with one
// space, the headings and blank lines do not; it exits 0 either way) and the packages held back
// (`apt-mark showhold`, one per line), and reads from the end of unattended-upgrades' log how long ago
// it last ran and how many errors its last run logged. Never `apt-get check`, which rebuilds the
// package cache. A host without dpkg is unsupported; one without the log has no uu_ fields.
func aptState(ctx context.Context) (map[string]any, error) {
	out, err := runToolEnv(ctx, toolTimeout, []string{"LC_ALL=C"}, "dpkg", "--audit")
	switch {
	case errors.Is(err, exec.ErrNotFound):
		return nil, fmt.Errorf("%w: dpkg is not installed", ErrUnsupported)
	case err != nil:
		return nil, toolError("dpkg", err)
	}
	audit := 0
	for _, line := range strings.Split(string(out), "\n") {
		if len(line) > 1 && line[0] == ' ' && line[1] != ' ' {
			audit++
		}
	}
	out, err = runToolEnv(ctx, toolTimeout, []string{"LC_ALL=C"}, "apt-mark", "showhold")
	if err != nil {
		return nil, toolError("apt-mark", err)
	}
	held := 0
	for _, line := range strings.Split(string(out), "\n") {
		if strings.TrimSpace(line) != "" {
			held++
		}
	}
	values := map[string]any{"audit": audit, "held": held}
	tail, err := readTail(uuLog, uuLogTail)
	if errors.Is(err, fs.ErrNotExist) {
		return values, nil
	}
	if err != nil {
		return nil, errors.New("unattended-upgrades: its log cannot be read")
	}
	last, errs := uuLastRun(tail)
	if last.IsZero() {
		// No line of the known form: the file's time stands for the last run, no error is counted.
		fi, err := statPath(uuLog)
		if err != nil {
			return nil, errors.New("unattended-upgrades: its log cannot be read")
		}
		last = fi.ModTime()
	}
	values["uu_last_run_age_s"] = ageSeconds(last)
	values["uu_errors"] = errs
	return values, nil
}

// uuLastRun reads the time of the log's last line and the ERROR lines of the last run, the lines after
// the last pause of more than uuRunGap. Lines of another form (a traceback, a wrapped message) count
// for neither.
func uuLastRun(log []byte) (time.Time, int) {
	var last time.Time
	errs := 0
	for line := range strings.Lines(string(log)) {
		if len(line) < len(uuTimeLayout)+1 {
			continue
		}
		at, err := time.ParseInLocation(uuTimeLayout, line[:len(uuTimeLayout)], time.Local)
		if err != nil {
			continue
		}
		if !last.IsZero() && at.Sub(last) > uuRunGap {
			errs = 0
		}
		last = at
		if level, _, _ := strings.Cut(line[len(uuTimeLayout)+1:], " "); level == "ERROR" {
			errs++
		}
	}
	return last, errs
}
