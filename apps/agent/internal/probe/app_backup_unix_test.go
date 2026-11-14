// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux || freebsd

package probe

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"
)

func stubRsnapshotProcs(t *testing.T, n int) {
	t.Helper()
	old := findProcesses
	findProcesses = func(_ context.Context, name string) ([]proc, error) {
		if name != "rsnapshot" {
			t.Errorf("asked for processes named %q", name)
		}
		return make([]proc, n), nil
	}
	t.Cleanup(func() { findProcesses = old })
}

func logAt(d time.Duration, msg string) string {
	return "[" + backupNow.Add(-d).Format("2006-01-02T15:04:05") + "] /usr/bin/rsnapshot alpha: " + msg + "\n"
}

func TestRsnapshotStatusReadsTheLastRun(t *testing.T) {
	stubNow(t, backupNow)
	ok := logAt(30*time.Hour, "started") + "[" + backupNow.Add(-30*time.Hour).Format("02/Jan/2006:15:04:05") +
		"] /usr/bin/rsnapshot alpha: completed successfully\n"
	for name, c := range map[string]struct {
		log  string
		want map[string]any
	}{
		"ok": {ok + logAt(6*time.Hour, "started") + logAt(6*time.Hour, "echo 1234 > /var/run/rsnapshot.pid") +
			logAt(5*time.Hour, "completed successfully"),
			map[string]any{"last_status": "ok", "last_success_age_s": int64(5 * 3600)}},
		"warning": {ok + logAt(2*time.Hour, "started") + logAt(2*time.Hour, "WARNING: /usr/bin/rsync returned 23 while processing x") +
			"[" + backupNow.Add(-time.Hour).Format("2006-01-02T15:04:05") +
			"] WARNING: /usr/bin/rsnapshot alpha: completed, but with some warnings\n",
			map[string]any{"last_status": "warning", "last_success_age_s": int64(30 * 3600)}},
		"error": {ok + logAt(time.Hour, "ERROR: /etc/rsnapshot.conf on line 12:"),
			map[string]any{"last_status": "error", "last_success_age_s": int64(30 * 3600)}},
		"errors at the end": {ok + logAt(2*time.Hour, "started") +
			logAt(time.Hour, "ERROR: /usr/bin/rsnapshot alpha: completed, but with some errors"),
			map[string]any{"last_status": "error", "last_success_age_s": int64(30 * 3600)}},
		"none": {"[" + backupNow.Format("2006-01-02T15:04:05") + "] /usr/bin/rsnapshot beta: started\n",
			map[string]any{"last_status": "none"}},
	} {
		t.Run(name, func(t *testing.T) {
			dir := rsnapshotHere(t, "logfile\t<dir>/rsnapshot.log", "lockfile\t<dir>/rsnapshot.pid")
			if err := os.WriteFile(filepath.Join(dir, "rsnapshot.log"), []byte(c.log), 0o600); err != nil {
				t.Fatal(err)
			}
			stubRsnapshotProcs(t, 0)
			got, err := rsnapshotStatus(context.Background())
			want := map[string]any{"running": false, "lock_stale": false}
			for k, v := range c.want {
				want[k] = v
			}
			if err != nil || !reflect.DeepEqual(got, want) {
				t.Fatalf("rsnapshot = %v, %v; want %v", got, err, want)
			}
		})
	}
}

func TestRsnapshotStatusTellsARunFromAStaleLock(t *testing.T) {
	stubNow(t, backupNow)
	dir := rsnapshotHere(t, "logfile\t<dir>/rsnapshot.log", "lockfile\t<dir>/rsnapshot.pid")
	for _, f := range []string{"rsnapshot.log", "rsnapshot.pid"} {
		if err := os.WriteFile(filepath.Join(dir, f), []byte(logAt(time.Hour, "started")), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	for procs, want := range map[int][2]bool{0: {false, true}, 1: {true, false}} {
		stubRsnapshotProcs(t, procs)
		got, err := rsnapshotStatus(context.Background())
		if err != nil || got["running"] != want[0] || got["lock_stale"] != want[1] {
			t.Errorf("with %d processes = %v, %v; want running %v, lock_stale %v", procs, got, err, want[0], want[1])
		}
	}
}

func TestRsnapshotStatusReadsOnlyTheEndOfALongLog(t *testing.T) {
	stubNow(t, backupNow)
	dir := rsnapshotHere(t, "logfile\t<dir>/rsnapshot.log")
	old := logAt(10*time.Hour, "completed successfully")
	log := old + strings.Repeat(logAt(9*time.Hour, "/usr/bin/rsync -a --delete /home/ /var/cache/x/"), rsnapshotLogTail/60) +
		logAt(time.Hour, "ERROR: rsync failed")
	if err := os.WriteFile(filepath.Join(dir, "rsnapshot.log"), []byte(log), 0o600); err != nil {
		t.Fatal(err)
	}
	stubRsnapshotProcs(t, 0)
	got, err := rsnapshotStatus(context.Background())
	if want := map[string]any{"last_status": "error", "running": false, "lock_stale": false}; err != nil || !reflect.DeepEqual(got, want) {
		t.Errorf("rsnapshot = %v, %v; want %v (the success is beyond the tail)", got, err, want)
	}
}

func TestRsnapshotStatusWithoutLogOrRsnapshot(t *testing.T) {
	rsnapshotHere(t, "lockfile\t/var/run/rsnapshot.pid")
	if _, err := rsnapshotStatus(context.Background()); !errors.Is(err, ErrUnsupported) || !strings.Contains(err.Error(), "logfile") {
		t.Errorf("without logfile = %v, want unsupported", err)
	}
	rsnapshotHere(t, "logfile\tvar/log/rsnapshot.log")
	if _, err := rsnapshotStatus(context.Background()); err == nil || errors.Is(err, ErrUnsupported) {
		t.Errorf("a relative logfile = %v, want an error", err)
	}
	dir := rsnapshotHere(t, "logfile\t<dir>/never-written.log")
	stubRsnapshotProcs(t, 0)
	got, err := rsnapshotStatus(context.Background())
	if want := map[string]any{"last_status": "none", "running": false, "lock_stale": false}; err != nil || !reflect.DeepEqual(got, want) {
		t.Errorf("a log not yet written = %v, %v; want %v", got, err, want)
	}
	old := rsnapshotConfigs
	rsnapshotConfigs = []string{filepath.Join(dir, "absent.conf")}
	t.Cleanup(func() { rsnapshotConfigs = old })
	if _, err := rsnapshotStatus(context.Background()); !errors.Is(err, ErrUnsupported) {
		t.Errorf("without configuration = %v, want unsupported", err)
	}
}
