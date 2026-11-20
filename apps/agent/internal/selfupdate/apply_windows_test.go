// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package selfupdate

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// seams points the update folder and the FRP config at temp dirs and counts the checks.
func seams(t *testing.T, conf string) (dir string, checks *int) {
	t.Helper()
	frp := t.TempDir()
	t.Setenv("ADMINHELPER_FRP_DIR", frp)
	if conf != "" {
		if err := os.WriteFile(filepath.Join(frp, "adminhelper.conf"), []byte(conf), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	dir = filepath.Join(t.TempDir(), updateDirName)
	n := 0
	oldDir, oldCheck := updateDir, checkNow
	updateDir = func() (string, error) { return dir, nil }
	checkNow = func(_ context.Context, current, d string) {
		if current != "1.2.3" || d != dir {
			t.Errorf("check(%q, %q), want (1.2.3, %q)", current, d, dir)
		}
		n++
	}
	t.Cleanup(func() { updateDir, checkNow = oldDir, oldCheck })
	return dir, &n
}

func TestTickNotProvisioned(t *testing.T) {
	dir, checks := seams(t, "")
	tick(context.Background(), "1.2.3", time.Now())
	if _, err := os.Stat(dir); !os.IsNotExist(err) || *checks != 0 {
		t.Fatalf("unprovisioned host: update dir %v, %d checks; want neither", err, *checks)
	}
}

func TestTickDisabled(t *testing.T) {
	dir, checks := seams(t, "ADMINHELPER_URL=\"https://srv.example\"\nAUTO_UPDATE=\"0\"\n")
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := SaveState(filepath.Join(dir, stateFile), State{Next: time.Now().Add(-time.Hour)}); err != nil {
		t.Fatal(err)
	}
	tick(context.Background(), "1.2.3", time.Now())
	if *checks != 0 {
		t.Fatalf("AUTO_UPDATE=0 ran %d checks", *checks)
	}
}

func TestTickSchedules(t *testing.T) {
	dir, checks := seams(t, "ADMINHELPER_URL=\"https://srv.example\"\n")
	now := time.Now()
	tick(context.Background(), "1.2.3", now)
	st, err := LoadState(filepath.Join(dir, stateFile))
	if err != nil || st.Next.Before(now) || !st.Next.Before(now.Add(CheckJitter)) || *checks != 0 {
		t.Fatalf("first start: next %v (%v), %d checks; want a check within the jitter and none now",
			st.Next, err, *checks)
	}
	tick(context.Background(), "1.2.3", st.Next)
	if *checks != 1 {
		t.Fatalf("due tick ran %d checks, want 1", *checks)
	}
	st2, _ := LoadState(filepath.Join(dir, stateFile))
	if !st2.Next.After(st.Next.Add(CheckInterval - time.Second)) {
		t.Fatalf("after the check next = %v, want a day later than %v", st2.Next, st.Next)
	}
}

func TestApplyStagedRefuses(t *testing.T) {
	seams(t, "")
	if err := ApplyStaged("dev"); err == nil || !strings.Contains(err.Error(), "no release version") {
		t.Fatalf("ApplyStaged(dev) = %v, want a refusal", err)
	}
	// The test binary is not the staged agent.
	if err := ApplyStaged("1.2.3"); err == nil || !strings.Contains(err.Error(), "runs only from") {
		t.Fatalf("ApplyStaged from elsewhere = %v, want a refusal", err)
	}
}

func TestMarkHealthy(t *testing.T) {
	dir, _ := seams(t, "")
	MarkHealthy("1.2.3")
	if _, err := os.Stat(dir); !os.IsNotExist(err) {
		t.Fatalf("MarkHealthy created the update folder (%v)", err)
	}
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	MarkHealthy("1.2.3")
	if !waitHealthy(filepath.Join(dir, healthyFile), "1.2.3", 30*time.Second, 10*time.Millisecond) {
		t.Fatal("no health marker for 1.2.3")
	}
}
