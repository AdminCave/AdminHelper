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

// stubSysBlock points sysBlock at a fresh tree holding files (path below /sys/block → content).
func stubSysBlock(t *testing.T, files map[string]string) {
	t.Helper()
	root := t.TempDir()
	for name, content := range files {
		path := filepath.Join(root, name)
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(content+"\n"), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	old := sysBlock
	sysBlock = root
	t.Cleanup(func() { sysBlock = old })
}

func TestMdArraysCountsStatesFaultsAndChecks(t *testing.T) {
	stubSysBlock(t, map[string]string{
		// A healthy raid1 during a check, with mismatches from the last one.
		"md0/md/array_state":    "clean",
		"md0/md/degraded":       "0",
		"md0/md/sync_action":    "check",
		"md0/md/mismatch_cnt":   "128",
		"md0/md/dev-sda1/state": "in_sync",
		"md0/md/dev-sdb1/state": "in_sync,writemostly",
		// A raid5 that lost a member and recovers onto a spare.
		"md1/md/array_state":    "active",
		"md1/md/degraded":       "1",
		"md1/md/sync_action":    "recover",
		"md1/md/mismatch_cnt":   "0",
		"md1/md/dev-sdc1/state": "faulty,write_error",
		"md1/md/dev-sdd1/state": "spare",
		// A raid0: no degraded, no sync_action, no mismatch_cnt.
		"md2/md/array_state":    "clean",
		"md2/md/dev-sde1/state": "in_sync",
		// Not started at boot: it serves nothing.
		"md3/md/array_state": "inactive",
		// A node without an array, and a device that is no md device.
		"md127/md/array_state": "clear",
		"sda/queue/rotational": "1",
	})
	got, err := mdArrays(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]any{"arrays": 4, "degraded": 2, "faulty_devices": 1, "resyncing": 2, "mismatch_cnt": 128}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("md %v, want %v", got, want)
	}
}

func TestMdArraysReportsZeroWithoutArrays(t *testing.T) {
	stubSysBlock(t, map[string]string{"sda/queue/rotational": "1"})
	got, err := mdArrays(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if got["arrays"] != 0 || got["degraded"] != 0 {
		t.Errorf("md %v, want zero arrays", got)
	}
}

func TestMdArraysIsUnsupportedWithoutSysfs(t *testing.T) {
	old := sysBlock
	sysBlock = filepath.Join(t.TempDir(), "absent")
	t.Cleanup(func() { sysBlock = old })
	if _, err := mdArrays(context.Background()); !errors.Is(err, ErrUnsupported) {
		t.Errorf("err %v, want unsupported", err)
	}
}

func TestMdArraysRejectsACountOfAnotherFormWithoutTheDeviceName(t *testing.T) {
	stubSysBlock(t, map[string]string{"md0/md/array_state": "clean", "md0/md/degraded": "one"})
	_, err := mdArrays(context.Background())
	if err == nil || strings.Contains(err.Error(), "md0") {
		t.Errorf("err %v, want an error that names no device", err)
	}
}

var lvsCall = append([]string{"lvs"}, lvsArgs...)

func TestLvmThinCountsPoolsAndTheirFill(t *testing.T) {
	calls := stubTools(t, answer{out: `{
      "report": [
          {
              "lv": [
                  {"lv_attr":"twi-aotz--", "data_percent":"81.50", "metadata_percent":"12.04"},
                  {"lv_attr":"twi-aotzD-", "data_percent":"100.00", "metadata_percent":"40.00"},
                  {"lv_attr":"twi---tz--", "data_percent":"", "metadata_percent":""},
                  {"lv_attr":"Vwi-aotz--", "data_percent":"55.00", "metadata_percent":""},
                  {"lv_attr":"-wi-ao----", "data_percent":"", "metadata_percent":""}
              ]
          }
      ]
  }`})
	got, err := lvmThin(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]any{"pools": 3, "max_data_pct": 100.0, "max_meta_pct": 40.0, "failed": 1, "busy": false}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("lvm %v, want %v", got, want)
	}
	if !reflect.DeepEqual(*calls, [][]string{lvsCall}) {
		t.Errorf("calls %q, want %q", *calls, lvsCall)
	}
}

func TestLvmThinReadsPercentagesInADecimalCommaLocale(t *testing.T) {
	stubTools(t, answer{out: `{"report":[{"lv":[{"lv_attr":"twi-aotz--","data_percent":"81,50","metadata_percent":"12,04"}]}]}`})
	got, err := lvmThin(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if got["max_data_pct"] != 81.5 || got["max_meta_pct"] != 12.04 {
		t.Errorf("lvm %v, want 81.5 and 12.04 from a de_DE report", got)
	}
}

func TestLvmThinReportsBusyWhenLvsTimesOut(t *testing.T) {
	stubTools(t, answer{err: context.DeadlineExceeded})
	got, err := lvmThin(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(got, map[string]any{"busy": true}) {
		t.Errorf("lvm %v, want busy alone", got)
	}
}

func TestLvmThinGivesUpWhenTheProbeEnds(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	stubTools(t, answer{err: context.Canceled})
	if _, err := lvmThin(ctx); !errors.Is(err, context.Canceled) {
		t.Errorf("err %v, want the probe's own end", err)
	}
}

func TestLvmThinIsUnsupportedWithoutLvs(t *testing.T) {
	stubTools(t, answer{err: exec.ErrNotFound})
	if _, err := lvmThin(context.Background()); !errors.Is(err, ErrUnsupported) {
		t.Errorf("err %v, want unsupported", err)
	}
}

func TestLvmThinRejectsAReportOfAnotherForm(t *testing.T) {
	for name, out := range map[string]string{
		"no json":           "  LV   VG\n",
		"a percent too big": `{"report":[{"lv":[{"lv_attr":"twi-aotz--","data_percent":"101.00","metadata_percent":"1.00"}]}]}`,
		"two commas":        `{"report":[{"lv":[{"lv_attr":"twi-aotz--","data_percent":"1,0,0","metadata_percent":"1.00"}]}]}`,
		"a percent no num":  `{"report":[{"lv":[{"lv_attr":"twi-aotz--","data_percent":"x","metadata_percent":"1.00"}]}]}`,
	} {
		stubTools(t, answer{out: out})
		if _, err := lvmThin(context.Background()); err == nil {
			t.Errorf("%s: no error", name)
		}
	}
}

func TestTheHostSensorRunsLvsUnderItsOwnTimeout(t *testing.T) {
	var got time.Duration
	old := runTool
	runTool = func(_ context.Context, timeout time.Duration, name string, args ...string) ([]byte, error) {
		checkAllowed(t, name, args)
		got = timeout
		return []byte(`{"report":[{"lv":[]}]}`), nil
	}
	t.Cleanup(func() { runTool = old })
	if _, err := lvmThin(context.Background()); err != nil {
		t.Fatal(err)
	}
	if got != lvsTimeout {
		t.Errorf("timeout %s, want %s", got, lvsTimeout)
	}
}
