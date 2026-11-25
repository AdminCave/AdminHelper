// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"errors"
	"reflect"
	"sync"
	"testing"
	"time"
)

func TestDisksFromFsstat(t *testing.T) {
	const gib = 1024 * 1024 * 1024
	stats := []fsStat{
		// 100 GiB in 4 KiB blocks: 40 GiB free for root, 30 GiB for users.
		{Mount: "/", FSType: "zfs", Bsize: 4096, Blocks: 100 * gib / 4096, Bfree: 40 * gib / 4096, Bavail: 30 * gib / 4096},
		// Root ate into its reserve: no space left for users.
		{Mount: "/var", FSType: "ufs", Bsize: 4096, Blocks: 10 * gib / 4096, Bfree: 0, Bavail: -1024},
		{Mount: "/dev", FSType: "devfs", Bsize: 512, Blocks: 2, Bfree: 0},
		{Mount: "/mnt/share", FSType: "nfs", Bsize: 4096, Blocks: 50 * gib / 4096, Bfree: 25 * gib / 4096, Bavail: 25 * gib / 4096},
		{Mount: "/empty", FSType: "ufs", Bsize: 4096},
	}

	got := disksFromFsstat(stats, "freebsd")

	want := []DiskInfo{
		{Mount: "/", FSType: "zfs", Percent: 66.7, TotalGB: 100, UsedGB: 60, FreeGB: 30},
		{Mount: "/var", FSType: "ufs", Percent: 100, TotalGB: 10, UsedGB: 10, FreeGB: 0},
		// A share stays a disk off Linux (skippedDisk): MNT_NOWAIT reads it without asking it.
		{Mount: "/mnt/share", FSType: "nfs", Percent: 50, TotalGB: 50, UsedGB: 25, FreeGB: 25},
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("disksFromFsstat =\n%+v\nwant\n%+v", got, want)
	}
}

func TestBoundedStatsLeavesOutAHungMount(t *testing.T) {
	hung := make(chan struct{})
	defer close(hung)
	var answered sync.WaitGroup
	answered.Add(3)
	stat := func(m string) (fsStat, error) {
		if m == "/mnt/hung" {
			<-hung
			return fsStat{Mount: m}, nil
		}
		if m == "/mnt/gone" {
			return fsStat{}, errors.New("stale handle")
		}
		return fsStat{Mount: m, FSType: "nfs", Blocks: 1}, nil
	}
	// The deadline fires once every mount but the hung one has queued its answer, so the test
	// does not race a clock.
	afterAnswer = func(m string) {
		if m != "/mnt/hung" {
			answered.Done()
		}
	}
	defer func() { afterAnswer = func(string) {} }()
	deadline := make(chan time.Time)
	go func() {
		answered.Wait()
		deadline <- time.Time{}
	}()

	got := boundedStats([]string{"/mnt/a", "/mnt/hung", "/mnt/gone", "/mnt/b"}, deadline, stat)

	var mounts []string
	for _, st := range got {
		mounts = append(mounts, st.Mount)
	}
	if want := []string{"/mnt/a", "/mnt/b"}; !reflect.DeepEqual(mounts, want) {
		t.Fatalf("mounts = %v, want %v", mounts, want)
	}
}

func TestBoundedStatsDoesNotWaitForTheDeadlineWhenAllAnswer(t *testing.T) {
	stat := func(m string) (fsStat, error) { return fsStat{Mount: m}, nil }
	// A deadline that never fires: boundedStats returns only because both mounts answered.
	got := boundedStats([]string{"/x", "/y"}, make(chan time.Time), stat)
	if len(got) != 2 {
		t.Fatalf("got %d stats, want 2", len(got))
	}
}

// R-1772: a mount whose stat still hangs from an earlier run is not asked again, so a long-running
// agent keeps one goroutine per hung mount, not one per run; once it answers it is asked again.
func TestBoundedStatsAsksAHungMountOnlyOnce(t *testing.T) {
	hung := make(chan struct{})
	released := make(chan struct{}, 2)
	var mu sync.Mutex
	asks := map[string]int{}
	stat := func(m string) (fsStat, error) {
		mu.Lock()
		asks[m]++
		mu.Unlock()
		if m == "/mnt/once-hung" {
			<-hung
		}
		return fsStat{Mount: m}, nil
	}
	var answered sync.WaitGroup
	answered.Add(1)
	afterAnswer = func(m string) {
		if m == "/mnt/once-hung" {
			released <- struct{}{}
		} else {
			answered.Done()
		}
	}
	defer func() { afterAnswer = func(string) {} }()
	deadline := make(chan time.Time)
	go func() {
		answered.Wait()
		deadline <- time.Time{}
	}()
	mounts := []string{"/mnt/once-ok", "/mnt/once-hung"}
	if got := boundedStats(mounts, deadline, stat); len(got) != 1 || got[0].Mount != "/mnt/once-ok" {
		t.Fatalf("first run = %+v, want /mnt/once-ok only", got)
	}

	// The hung mount is not asked: the run ends without a deadline, since all it asked answered.
	answered.Add(1)
	if got := boundedStats(mounts, make(chan time.Time), stat); len(got) != 1 || got[0].Mount != "/mnt/once-ok" {
		t.Fatalf("second run = %+v, want /mnt/once-ok only", got)
	}
	mu.Lock()
	if asks["/mnt/once-hung"] != 1 {
		t.Fatalf("the hung mount was asked %d times, want 1", asks["/mnt/once-hung"])
	}
	mu.Unlock()

	close(hung)
	select {
	case <-released:
	case <-time.After(30 * time.Second):
		t.Fatal("the hung stat did not come back")
	}
	answered.Add(1)
	if got := boundedStats(mounts, make(chan time.Time), stat); len(got) != 2 {
		t.Fatalf("after the answer = %+v, want both mounts", got)
	}
	mu.Lock()
	defer mu.Unlock()
	if asks["/mnt/once-hung"] != 2 {
		t.Fatalf("the answered mount was asked %d times in all, want 2", asks["/mnt/once-hung"])
	}
}

func TestUnderNetMount(t *testing.T) {
	shares := []string{"/mnt/nfs", "/net/smb/"}
	for mount, want := range map[string]bool{
		"/mnt/nfs/local": true, "/mnt/nfs/a/b": true, "/net/smb/x": true,
		"/mnt/nfs": false, "/mnt/nfsx": false, "/var": false, "/": false,
	} {
		if got := underNetMount(mount, shares); got != want {
			t.Errorf("underNetMount(%q) = %v, want %v", mount, got, want)
		}
	}
}

func TestFreebsdNetFS(t *testing.T) {
	for fstype, want := range map[string]bool{
		"nfs": true, "smbfs": true, "fusefs": true, "fusefs.sshfs": true,
		"ufs": false, "zfs": false, "tmpfs": false, "fusefsx": false,
	} {
		if got := freebsdNetFS(fstype); got != want {
			t.Errorf("freebsdNetFS(%q) = %v, want %v", fstype, got, want)
		}
	}
}
