// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"adminhelper-agent/internal/config"
)

// hwSlot lets one hardware view at a time talk to a controller or the BMC: two controller CLIs, or a
// CLI and an SDR dump, at once queue in the firmware and slow the host's own I/O.
var hwSlot = make(chan struct{}, 1)

// takeHwSlot waits for hwSlot or the end of ctx; the returned func gives it back.
func takeHwSlot(ctx context.Context) (func(), error) {
	select {
	case hwSlot <- struct{}{}:
		return func() { <-hwSlot }, nil
	case <-ctx.Done():
		return nil, ctx.Err()
	}
}

// The controller CLIs the raid view knows, at the paths their vendor packages install them to (perccli:
// Dell kbdoc 000217748, "cd /opt/MegaRAID/perccli" after the rpm or deb install,
// https://www.dell.com/support/kbdoc/en-us/000217748). perccli is Dell's build of storcli and sees the same controllers, so it runs only without storcli.
// storcli2 (Broadcom 9600 series) stays out: neither its argument syntax nor its JSON is verified.
var (
	storcliPath = "/opt/MegaRAID/storcli/storcli64"
	perccliPath = "/opt/MegaRAID/perccli/perccli64"
	ssacliPath  = "/usr/sbin/ssacli"
)

// storcliArgs: every controller with all its details as JSON; nolog keeps storcli from writing its log
// file into the working directory.
var storcliArgs = []string{"/call", "show", "all", "J", "nolog"}

// hwTimeout caps one controller CLI call; a controller under a rebuild answers slowly. Two calls (ssacli)
// fit the 30 s a probe may take at most (catalog timeout_s).
const hwTimeout = 14 * time.Second

// raidCtrl counts this host's hardware RAID controllers and what they report unhealthy: controllers
// whose own status is not optimal, virtual drives (logical drives) that are not optimal, physical
// drives in a failed, offline, rebuilding or unconfigured-bad state, and batteries or cache vaults
// that are not optimal. No model, serial, slot or drive name leaves it. A host without any of the
// CLIs is unsupported.
func raidCtrl(ctx context.Context) (map[string]any, error) {
	var tools []string
	for _, path := range []string{storcliPath, perccliPath, ssacliPath} {
		if path == perccliPath && len(tools) > 0 {
			continue
		}
		if _, err := statPath(path); err == nil {
			tools = append(tools, path)
		}
	}
	if len(tools) == 0 {
		return nil, fmt.Errorf("%w: no RAID controller CLI is installed", ErrUnsupported)
	}
	release, err := takeHwSlot(ctx)
	if err != nil {
		return nil, err
	}
	defer release()
	var sum raidCounts
	for _, path := range tools {
		var c raidCounts
		if path == ssacliPath {
			c, err = ssacliCounts(ctx)
		} else {
			c, err = storcliCounts(ctx, path)
		}
		if err != nil {
			return nil, err
		}
		sum.add(c)
	}
	return map[string]any{
		"controllers": sum.controllers, "ctrl_bad": sum.ctrlBad, "vd_not_optimal": sum.vdNotOptimal,
		"pd_failed": sum.pdFailed, "bbu_bad": sum.bbuBad,
	}, nil
}

type raidCounts struct{ controllers, ctrlBad, vdNotOptimal, pdFailed, bbuBad int }

func (r *raidCounts) add(o raidCounts) {
	r.controllers += o.controllers
	r.ctrlBad += o.ctrlBad
	r.vdNotOptimal += o.vdNotOptimal
	r.pdFailed += o.pdFailed
	r.bbuBad += o.bbuBad
}

// hwRun runs one call of a hardware CLI; the error carries no line the tool wrote (it may name a
// serial or a drive).
func hwRun(ctx context.Context, timeout time.Duration, path string, args ...string) ([]byte, error) {
	name := filepath.Base(path)
	out, err := runTool(ctx, timeout, path, args...)
	switch {
	case errors.Is(err, exec.ErrNotFound):
		return nil, fmt.Errorf("%w: %s is not installed", ErrUnsupported, name)
	case ctx.Err() != nil:
		return nil, ctx.Err()
	case err != nil:
		var exitErr *exec.ExitError
		if errors.As(err, &exitErr) {
			return nil, fmt.Errorf("%s: exit status %d", name, exitErr.ExitCode())
		}
		return nil, fmt.Errorf("%s: %w", name, err)
	}
	return out, nil
}

// storcliCounts reads `storcli /call show all J nolog`. The key paths are those of the Prometheus
// textfile collector storcli.py (prometheus-community/node-exporter-textfile-collector-scripts):
// Controllers[].Command Status.Status, Response Data with Status.Controller Status, VD LIST[].State,
// PD LIST[].State, Status.BBU Status (a number, healthy 0, 8 or 4096, "NA" without one) and
// Cachevault_Info[].State. The healthy states follow check_lsi_raid (thomas-krenn): a VD Optl, a PD
// Onln, UGood, GHS, DHS or JBOD. Not checked against a controller.
func storcliCounts(ctx context.Context, path string) (raidCounts, error) {
	name := filepath.Base(path)
	out, err := hwRun(ctx, hwTimeout, path, storcliArgs...)
	if err != nil {
		return raidCounts{}, err
	}
	var doc struct {
		Controllers []struct {
			CommandStatus struct {
				Status string `json:"Status"`
			} `json:"Command Status"`
			ResponseData struct {
				Status struct {
					ControllerStatus string          `json:"Controller Status"`
					BBUStatus        json.RawMessage `json:"BBU Status"`
				} `json:"Status"`
				VDs []struct {
					State string `json:"State"`
				} `json:"VD LIST"`
				PDs []struct {
					State string `json:"State"`
				} `json:"PD LIST"`
				Cachevaults []struct {
					State string `json:"State"`
				} `json:"Cachevault_Info"`
			} `json:"Response Data"`
		} `json:"Controllers"`
	}
	if err := json.Unmarshal(out, &doc); err != nil || len(doc.Controllers) == 0 {
		return raidCounts{}, fmt.Errorf("%s: a report of another form", name)
	}
	var c raidCounts
	for _, ctrl := range doc.Controllers {
		if ctrl.CommandStatus.Status != "Success" {
			return raidCounts{}, fmt.Errorf("%s: a controller did not answer", name)
		}
		data := ctrl.ResponseData
		c.controllers++
		// MegaRAID reports Optimal, the SAS HBAs (mpt3sas) OK.
		if s := data.Status.ControllerStatus; s != "" && s != "Optimal" && s != "OK" {
			c.ctrlBad++
		}
		for _, vd := range data.VDs {
			if vd.State != "Optl" {
				c.vdNotOptimal++
			}
		}
		for _, pd := range data.PDs {
			switch pd.State {
			case "Onln", "UGood", "GHS", "DHS", "JBOD":
			default:
				c.pdFailed++
			}
		}
		bad, err := bbuStatusBad(data.Status.BBUStatus)
		if err != nil {
			return raidCounts{}, fmt.Errorf("%s: a battery status of another form", name)
		}
		for _, cv := range data.Cachevaults {
			if cv.State != "Optimal" {
				bad = true
			}
		}
		if bad {
			c.bbuBad++
		}
	}
	return c, nil
}

// bbuStatusBad reads Status.BBU Status: absent or "NA" is no battery, 0, 8 and 4096 are healthy.
func bbuStatusBad(raw json.RawMessage) (bool, error) {
	if len(raw) == 0 || string(raw) == "null" || string(raw) == `"NA"` {
		return false, nil
	}
	var n int
	if err := json.Unmarshal(raw, &n); err != nil {
		var s string
		if err := json.Unmarshal(raw, &s); err != nil {
			return false, err
		}
		if n, err = strconv.Atoi(s); err != nil {
			return false, err
		}
	}
	return n != 0 && n != 8 && n != 4096, nil
}

// ssacliCounts reads `ssacli ctrl all show status` (Controller Status, Cache Status and
// Battery/Capacitor Status per controller) and `ssacli ctrl all show config` (a logicaldrive and a
// physicaldrive line each, their status an item in the parentheses: "logicaldrive 1 (68.3 GB, RAID 1,
// OK)"). The lines follow the check_raid plugin hpacucli.pm (glensc/nagios-plugin-check_raid);
// the physicaldrive line and show config itself are not verified against a controller.
func ssacliCounts(ctx context.Context) (raidCounts, error) {
	out, err := hwRun(ctx, hwTimeout, ssacliPath, "ctrl", "all", "show", "status")
	if err != nil {
		return raidCounts{}, err
	}
	var c raidCounts
	sc := bufio.NewScanner(bytes.NewReader(out))
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		key, value, ok := strings.Cut(line, ":")
		if !ok {
			if strings.Contains(line, " in Slot ") {
				c.controllers++
			}
			continue
		}
		value = strings.TrimSpace(value)
		switch strings.TrimSpace(key) {
		case "Controller Status":
			if value != "OK" {
				c.ctrlBad++
			}
		case "Cache Status", "Battery/Capacitor Status":
			if value != "OK" && value != "Not Configured" {
				c.bbuBad++
			}
		}
	}
	if c.controllers == 0 {
		return raidCounts{}, errors.New("ssacli: a report of another form")
	}
	out, err = hwRun(ctx, hwTimeout, ssacliPath, "ctrl", "all", "show", "config")
	if err != nil {
		return raidCounts{}, err
	}
	sc = bufio.NewScanner(bytes.NewReader(out))
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		kind, _, _ := strings.Cut(line, " ")
		if kind != "logicaldrive" && kind != "physicaldrive" {
			continue
		}
		open, end := strings.Index(line, "("), strings.LastIndex(line, ")")
		if open < 0 || end < open {
			return raidCounts{}, errors.New("ssacli: a drive line of another form")
		}
		// A spare drive may add an item after its status ("OK, spare"): healthy is a line with an OK.
		healthy := false
		for _, item := range strings.Split(line[open+1:end], ",") {
			healthy = healthy || strings.TrimSpace(item) == "OK"
		}
		switch {
		case healthy:
		case kind == "logicaldrive":
			c.vdNotOptimal++
		default:
			c.pdFailed++
		}
	}
	return c, nil
}

// The device nodes of the kernel's IPMI driver (ipmi_devintf): without one no ipmitool call, so the
// view never makes the kernel load ipmi_si.
var ipmiDevices = []string{"/dev/ipmi0", "/dev/ipmi/0", "/dev/ipmidev/0"}

// ipmiCacheDir is where the SDR cache lives: the agent's state directory.
var ipmiCacheDir = config.MonitorDir

const (
	sdrCacheName = ".ipmi-sdr.cache"
	// sdrCacheMaxAge: the SDR (which sensors there are, their thresholds) only changes with the
	// hardware or the BMC firmware; the agent runs as a oneshot, so the cache outlives a run.
	sdrCacheMaxAge = 24 * time.Hour
	// ipmiTimeout caps one ipmitool call: elist reads every sensor through the BMC, one at a time. A dump
	// and the elist fit the 30 s a probe may take at most (catalog timeout_s).
	ipmiTimeout = 14 * time.Second
)

// ipmiSensors counts this host's IPMI sensors by their state as `ipmitool sdr elist` prints it
// (ipmitool lib/ipmi_sdr.c, ipmi_sdr_print_sensor_fc and ipmi_sdr_get_thresh_status): sensors with a
// reading, critical (cr, nr and their lower/upper forms lcr, ucr, lnr, unr), noncritical (nc, lnc,
// unc). ns (no reading) counts in none. The SDR comes from a cache in the state directory that `sdr
// dump` writes when it is missing or older than sdrCacheMaxAge, so a run does not walk the
// repository on the BMC. No sensor name leaves it. Not checked against a BMC.
func ipmiSensors(ctx context.Context) (map[string]any, error) {
	found := false
	for _, dev := range ipmiDevices {
		if _, err := statPath(dev); err == nil {
			found = true
			break
		}
	}
	if !found {
		return nil, fmt.Errorf("%w: no IPMI device", ErrUnsupported)
	}
	release, err := takeHwSlot(ctx)
	if err != nil {
		return nil, err
	}
	defer release()
	cache, err := sdrCache(ctx)
	if err != nil {
		return nil, err
	}
	out, err := hwRun(ctx, ipmiTimeout, "ipmitool", "-S", cache, "sdr", "elist")
	if err != nil {
		return nil, err
	}
	var sensors, critical, noncritical int
	sc := bufio.NewScanner(bytes.NewReader(out))
	for sc.Scan() {
		if strings.TrimSpace(sc.Text()) == "" {
			continue
		}
		cols := strings.Split(sc.Text(), "|")
		if len(cols) < 5 {
			return nil, errors.New("ipmitool: a sensor line of another form")
		}
		switch strings.TrimSpace(cols[2]) {
		case "ns":
			continue
		case "ok":
		case "nc", "lnc", "unc":
			noncritical++
		case "cr", "lcr", "ucr", "nr", "lnr", "unr":
			critical++
		default:
			return nil, errors.New("ipmitool: a sensor state of another form")
		}
		sensors++
	}
	return map[string]any{"sensors": sensors, "critical": critical, "noncritical": noncritical}, nil
}

// sdrCache returns the path of a fresh SDR cache, dumping it first when it is missing or stale. The
// dump goes to a file of its own and replaces the cache only once complete.
func sdrCache(ctx context.Context) (string, error) {
	dir := ipmiCacheDir()
	cache := filepath.Join(dir, sdrCacheName)
	fi, err := os.Stat(cache)
	if err == nil && now().Sub(fi.ModTime()) < sdrCacheMaxAge {
		return cache, nil
	}
	if err != nil && !errors.Is(err, fs.ErrNotExist) {
		return "", errors.New("ipmi: the SDR cache cannot be read")
	}
	next := cache + ".new"
	if _, err := hwRun(ctx, ipmiTimeout, "ipmitool", "sdr", "dump", next); err != nil {
		_ = os.Remove(next)
		return "", err
	}
	if err := os.Rename(next, cache); err != nil {
		_ = os.Remove(next)
		return "", errors.New("ipmi: the SDR cache cannot be written")
	}
	return cache, nil
}
