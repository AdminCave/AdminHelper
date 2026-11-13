// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"math"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

// sysBlock is where the kernel lists the block devices; tests point it at a tree of their own.
var sysBlock = "/sys/block"

// mdArrays counts this host's md arrays from sysfs (kernel admin-guide md.rst, "md devices in
// sysfs"), never through mdadm, whose other modes write. degraded counts the arrays that miss a
// device or serve nothing (array_state inactive or broken); faulty_devices the members marked faulty;
// resyncing the arrays a resync, recovery, check, repair or reshape runs on; mismatch_cnt the sum of
// the sectors the last check found differing. A host without sysfs is unsupported, one without
// arrays reports zero.
func mdArrays(_ context.Context) (map[string]any, error) {
	if _, err := os.Stat(sysBlock); err != nil {
		if errors.Is(err, fs.ErrNotExist) {
			return nil, fmt.Errorf("%w: no sysfs, this host has no md arrays", ErrUnsupported)
		}
		return nil, errors.New("md: sysfs cannot be read")
	}
	dirs, err := filepath.Glob(filepath.Join(sysBlock, "md*", "md"))
	if err != nil {
		return nil, err
	}
	var arrays, degraded, faulty, resyncing, mismatches int
	for _, dir := range dirs {
		state, err := mdAttr(dir, "array_state")
		if errors.Is(err, fs.ErrNotExist) {
			continue
		}
		if err != nil {
			return nil, err
		}
		// "clear": the md device exists without an array on it (mdadm --stop, or a node opened before
		// assembly).
		if state == "clear" {
			continue
		}
		arrays++
		// Levels without redundancy (raid0, linear) have no degraded, sync_action or mismatch_cnt.
		missing, err := mdCount(dir, "degraded")
		if err != nil {
			return nil, err
		}
		if missing > 0 || state == "inactive" || state == "broken" {
			degraded++
		}
		switch action, err := mdAttr(dir, "sync_action"); {
		case errors.Is(err, fs.ErrNotExist):
		case err != nil:
			return nil, err
		case action == "resync" || action == "recover" || action == "check" || action == "repair" ||
			action == "reshape":
			resyncing++
		}
		n, err := mdCount(dir, "mismatch_cnt")
		if err != nil {
			return nil, err
		}
		mismatches += n
		members, err := filepath.Glob(filepath.Join(dir, "dev-*", "state"))
		if err != nil {
			return nil, err
		}
		for _, member := range members {
			raw, err := os.ReadFile(member)
			if errors.Is(err, fs.ErrNotExist) {
				continue // the member left the array since the glob
			}
			if err != nil {
				return nil, errors.New("md: a member state cannot be read")
			}
			// A comma-separated list of flags that "may grow" (md.rst).
			for _, flag := range strings.Split(strings.TrimSpace(string(raw)), ",") {
				if flag == "faulty" {
					faulty++
					break
				}
			}
		}
	}
	return map[string]any{
		"arrays": arrays, "degraded": degraded, "faulty_devices": faulty, "resyncing": resyncing,
		"mismatch_cnt": mismatches,
	}, nil
}

// mdAttr is one attribute of the array in dir, trimmed; fs.ErrNotExist when the array has none. The
// error names no device.
func mdAttr(dir, name string) (string, error) {
	raw, err := os.ReadFile(filepath.Join(dir, name))
	if errors.Is(err, fs.ErrNotExist) {
		return "", err
	}
	if err != nil {
		return "", fmt.Errorf("md: %s cannot be read", name)
	}
	return strings.TrimSpace(string(raw)), nil
}

// mdCount is a count attribute of the array in dir, 0 when the array has none.
func mdCount(dir, name string) (int, error) {
	text, err := mdAttr(dir, name)
	if errors.Is(err, fs.ErrNotExist) {
		return 0, nil
	}
	if err != nil {
		return 0, err
	}
	n, err := strconv.Atoi(text)
	if err != nil || n < 0 {
		return 0, fmt.Errorf("md: %s of another form", name)
	}
	return n, nil
}

// lvsTimeout caps lvs: it waits for the LVM lock, which an lvconvert, a pvmove or a hung device can
// hold for long. A call it ends is a value (busy), not an error.
const lvsTimeout = 15 * time.Second

// lvsArgs are the fixed arguments of lvs: the attributes and fill levels of every LV, filtered to the
// thin pools here (lv_attr starts with 't', lvs(8)). segtype is a segment field, so --select
// segtype=thin-pool would ask lvs for segments.
var lvsArgs = []string{"--reportformat", "json", "-o", "lv_attr,data_percent,metadata_percent"}

// lvmThin reads the fill levels and the health of this host's LVM thin pools: how many, the fullest
// data and metadata in percent, how many lvs reports failed, out of data space or with read-only
// metadata (lv_attr position 9: F, D, M), and busy when lvs did not answer within lvsTimeout. No LV
// or VG name leaves it.
func lvmThin(ctx context.Context) (map[string]any, error) {
	out, err := runTool(ctx, lvsTimeout, "lvs", lvsArgs...)
	switch {
	case errors.Is(err, exec.ErrNotFound):
		return nil, fmt.Errorf("%w: lvs is not installed", ErrUnsupported)
	case ctx.Err() != nil:
		return nil, ctx.Err()
	case errors.Is(err, context.DeadlineExceeded):
		return map[string]any{"busy": true}, nil
	case err != nil:
		return nil, toolError("lvs", err)
	}
	// The JSON report (lvmreport(7)): {"report": [{"lv": [{"lv_attr": "...", ...}]}]}, every value a
	// string, a percentage "%.2f" (in the locale's notation) or "" when undefined. Key names not verified against a live lvs
	// beyond the documentation.
	var report struct {
		Report []struct {
			LV []map[string]string `json:"lv"`
		} `json:"report"`
	}
	if err := json.Unmarshal(out, &report); err != nil {
		return nil, errors.New("lvs: a report of another form")
	}
	var pools, failed int
	var maxData, maxMeta float64
	for _, r := range report.Report {
		for _, lv := range r.LV {
			attr := lv["lv_attr"]
			if !strings.HasPrefix(attr, "t") {
				continue
			}
			pools++
			if len(attr) >= 9 && strings.ContainsRune("FDM", rune(attr[8])) {
				failed++
			}
			data, err1 := lvsPercent(lv["data_percent"])
			meta, err2 := lvsPercent(lv["metadata_percent"])
			if err1 != nil || err2 != nil {
				return nil, errors.New("lvs: a percentage of another form")
			}
			maxData, maxMeta = math.Max(maxData, data), math.Max(maxMeta, meta)
		}
	}
	return map[string]any{
		"pools": pools, "max_data_pct": maxData, "max_meta_pct": maxMeta, "failed": failed, "busy": false,
	}, nil
}

// lvsPercent is a percentage as lvs prints it; "" (an inactive pool) counts as 0. lvm formats it with
// printf under the agent's locale (it keeps LC_NUMERIC), so a host with a German locale writes "81,50".
func lvsPercent(text string) (float64, error) {
	if text == "" {
		return 0, nil
	}
	v, err := strconv.ParseFloat(strings.Replace(text, ",", ".", 1), 64)
	if err != nil || math.IsNaN(v) || v < 0 || v > 100 {
		return 0, errors.New("out of range")
	}
	return v, nil
}
