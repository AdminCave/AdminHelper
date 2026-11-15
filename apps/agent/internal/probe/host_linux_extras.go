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
