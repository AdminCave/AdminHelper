// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package selfupdate

import (
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"
)

// fakeApply records the steps Apply takes; fail names a step that fails, healthy what WaitHealthy
// reports.
type fakeApply struct {
	steps   []string
	fail    string
	healthy bool
}

func (f *fakeApply) hooks() ApplyHooks {
	step := func(name string) func() error {
		return func() error {
			f.steps = append(f.steps, name)
			if f.fail == name {
				return errors.New(name + " failed")
			}
			return nil
		}
	}
	return ApplyHooks{
		ClearHealthy: step("clear"),
		Backup:       step("backup"),
		Install:      step("install"),
		WaitHealthy: func(v string) bool {
			f.steps = append(f.steps, "wait "+v)
			return f.healthy
		},
		Restore:    step("restore"),
		MarkFailed: func(v string) { f.steps = append(f.steps, "failed "+v) },
		Logf:       func(string, ...any) {},
	}
}

func TestApply(t *testing.T) {
	for _, c := range []struct {
		name       string
		fail       string
		healthy    bool
		want       []string
		rolledBack bool
		ok         bool
	}{
		{name: "healthy", healthy: true,
			want: []string{"clear", "backup", "install", "wait 1.2.3"}, ok: true},
		{name: "no healthy cycle",
			want:       []string{"clear", "backup", "install", "wait 1.2.3", "failed 1.2.3", "restore"},
			rolledBack: true},
		{name: "install fails", fail: "install", healthy: true,
			want:       []string{"clear", "backup", "install", "failed 1.2.3", "restore"},
			rolledBack: true},
		{name: "backup fails", fail: "backup", healthy: true,
			want: []string{"clear", "backup"}},
		{name: "clear fails", fail: "clear", healthy: true,
			want: []string{"clear"}},
		{name: "restore fails", fail: "restore",
			want: []string{"clear", "backup", "install", "wait 1.2.3", "failed 1.2.3", "restore"}},
	} {
		t.Run(c.name, func(t *testing.T) {
			f := &fakeApply{fail: c.fail, healthy: c.healthy}
			err := Apply(f.hooks(), "1.2.3")
			if !reflect.DeepEqual(f.steps, c.want) {
				t.Fatalf("steps = %q, want %q", f.steps, c.want)
			}
			if c.ok != (err == nil) {
				t.Fatalf("err = %v, want ok=%v", err, c.ok)
			}
			if got := errors.Is(err, ErrRolledBack); got != c.rolledBack {
				t.Fatalf("errors.Is(err, ErrRolledBack) = %v, want %v (err %v)", got, c.rolledBack, err)
			}
		})
	}
}

func TestApplyRestoreFailureNamesBoth(t *testing.T) {
	f := &fakeApply{fail: "restore"}
	err := Apply(f.hooks(), "1.2.3")
	if err == nil || !strings.Contains(err.Error(), "no cycle") || !strings.Contains(err.Error(), "restore failed") {
		t.Fatalf("err = %v, want the cause and the failed restore", err)
	}
}

func TestWaitHealthy(t *testing.T) {
	path := filepath.Join(t.TempDir(), "healthy")
	// The 30 ms waits test the deadline itself: they must run out.
	if waitHealthy(path, "1.2.3", 30*time.Millisecond, 5*time.Millisecond) {
		t.Fatal("healthy without a marker")
	}
	if err := writeMarker(path, "1.2.2"); err != nil {
		t.Fatal(err)
	}
	if waitHealthy(path, "1.2.3", 30*time.Millisecond, 5*time.Millisecond) {
		t.Fatal("the marker of another version counted")
	}
	go func() {
		time.Sleep(20 * time.Millisecond)
		_ = writeMarker(path, "1.2.3")
	}()
	if !waitHealthy(path, "1.2.3", 30*time.Second, 5*time.Millisecond) {
		t.Fatal("marker written during the wait was not seen")
	}
	if _, err := os.Stat(path); err != nil {
		t.Fatal(err)
	}
}
