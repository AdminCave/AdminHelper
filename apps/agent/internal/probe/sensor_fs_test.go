// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Windows has no statfs: its dirStatfs is ErrUnsupported, and no FIFO is made there.

//go:build linux || freebsd

package probe

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
	"time"
)

func TestFsValuesCountLikeDf(t *testing.T) {
	cases := map[string]struct {
		u    fsUsage
		want map[string]any
	}{
		// 600 of 1000 free, 100 of them reserved for root: 400 used of the 900 a user sees.
		"a reserve for root": {fsUsage{total: 1000, free: 600, avail: 500, inodes: 200, inodesFree: 150},
			map[string]any{"used_pct": 44.4, "free_bytes": uint64(500), "inodes_used_pct": 25.0}},
		"full": {fsUsage{total: 1000, free: 50, avail: 0, inodes: 10, inodesFree: 0},
			map[string]any{"used_pct": 100.0, "free_bytes": uint64(0), "inodes_used_pct": 100.0}},
		// btrfs has no fixed number of inodes, statfs reports 0 of them.
		"no inode count": {fsUsage{total: 1000, free: 1000, avail: 1000},
			map[string]any{"used_pct": 0.0, "free_bytes": uint64(1000), "inodes_used_pct": 0.0}},
		"nothing at all": {fsUsage{}, map[string]any{"used_pct": 0.0, "free_bytes": uint64(0), "inodes_used_pct": 0.0}},
	}
	for name, c := range cases {
		if got := fsValues(c.u); fmt.Sprint(got) != fmt.Sprint(c.want) {
			t.Errorf("%s: fsValues = %v, want %v", name, got, c.want)
		}
	}
}

// fsBounds checks that got holds the fields of the fs sensor within their bounds.
func fsBounds(t *testing.T, what string, got map[string]any) {
	t.Helper()
	used, ok1 := got["used_pct"].(float64)
	inodes, ok2 := got["inodes_used_pct"].(float64)
	_, ok3 := got["free_bytes"].(uint64)
	if !ok1 || !ok2 || !ok3 || len(got) != 3 || used < 0 || used > 100 || inodes < 0 || inodes > 100 {
		t.Errorf("fs on %s = %v, want used_pct, free_bytes and inodes_used_pct", what, got)
	}
}

func TestFsSensorReadsTheFileSystemOfADirectory(t *testing.T) {
	ctx := context.Background()
	dir := t.TempDir()
	p := Probe{Sensor: "fs", Params: map[string]any{"path": slashPath(t, dir)}}
	got, err := fsSensor(ctx, p, "")
	if err != nil {
		t.Fatalf("fs = %v", err)
	}
	fsBounds(t, "a directory", got)
	// On this host a link to a directory is followed, as by file_age: the path is the admin's.
	link := filepath.Join(dir, "link")
	if err := os.Symlink(t.TempDir(), link); err != nil {
		t.Fatal(err)
	}
	got, err = fsSensor(ctx, Probe{Sensor: "fs", Params: map[string]any{"path": link}}, "")
	if err != nil {
		t.Fatalf("fs on a link = %v", err)
	}
	fsBounds(t, "a link", got)

	file := filepath.Join(dir, "f")
	if err := os.WriteFile(file, nil, 0o600); err != nil {
		t.Fatal(err)
	}
	fifo := filepath.Join(dir, "fifo")
	if err := syscall.Mkfifo(fifo, 0o600); err != nil {
		t.Fatal(err)
	}
	for name, c := range map[string]struct {
		path string
		want error
	}{
		"a file":    {file, errNotDir},
		"a FIFO":    {fifo, errNotDir}, // O_DIRECTORY refuses it before the open would wait for a writer
		"no file":   {filepath.Join(dir, "gone"), nil},
		"a subpath": {filepath.Join(file, "x"), nil},
	} {
		done := make(chan error, 1)
		go func() {
			_, err := fsSensor(ctx, Probe{Sensor: "fs", Params: map[string]any{"path": c.path}}, "")
			done <- err
		}()
		select {
		case err := <-done:
			if err == nil || (c.want != nil && !errors.Is(err, c.want)) {
				t.Errorf("fs on %s = %v, want an error (%v)", name, err, c.want)
			}
		case <-time.After(30 * time.Second):
			t.Fatalf("fs on %s waits", name)
		}
	}
}

func TestFsSensorReadsADirectoryInsideAContainer(t *testing.T) {
	ctx := context.Background()
	src := t.TempDir()
	if err := os.Mkdir(filepath.Join(src, "data"), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(src, "f"), nil, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink("/", filepath.Join(src, "root")); err != nil {
		t.Fatal(err)
	}
	tl := stubTool(t, mountsJSON(t, [3]string{"volume", src, "/victoria-metrics-data"}), nil)

	for _, path := range []string{"/victoria-metrics-data", "/victoria-metrics-data/data"} {
		got, err := fsSensor(ctx, containerProbe("fs", "path", path), "")
		if err != nil {
			t.Fatalf("fs on %s in a container = %v", path, err)
		}
		fsBounds(t, path, got)
	}
	if tl.args[len(tl.args)-1] != "web" {
		t.Errorf("runTool %v, want docker inspect of web", tl.args)
	}
	for _, c := range []struct {
		path string
		want error
	}{
		{"/victoria-metrics-data/f", errNotDir},
		{"/victoria-metrics-data/root", nil}, // a link out of the mount
		{"/victoria-metrics-data/gone", nil},
		{"/var/lib", ErrInvalid},
	} {
		_, err := fsSensor(ctx, containerProbe("fs", "path", c.path), "")
		if err == nil || (c.want != nil && !errors.Is(err, c.want)) || strings.Contains(err.Error(), src) {
			t.Errorf("fs on %s in a container = %v, want an error (%v) without the host path", c.path, err, c.want)
		}
	}
}

// A mount source that is neither a directory nor a regular file is refused without its host path.
func TestAMountOfAFifoIsRefused(t *testing.T) {
	stubNow(t, start)
	dir := t.TempDir()
	fifo := filepath.Join(dir, "fifo")
	if err := syscall.Mkfifo(fifo, 0o600); err != nil {
		t.Fatal(err)
	}
	stubTool(t, mountsJSON(t, [3]string{"bind", fifo, "/etc/nginx/cert.pem"}), nil)
	for _, sensor := range []string{"certfile", "file_age", "fs"} {
		got, err := sensors[sensor](context.Background(), containerProbe(sensor, "path", "/etc/nginx/cert.pem"), "")
		if err == nil || strings.Contains(err.Error(), dir) {
			t.Errorf("%s on a bind of a fifo = %v, %v; want an error without a host path", sensor, got, err)
		}
	}
}

func TestFsSensorTakesAPathAlone(t *testing.T) {
	for name, p := range map[string]Probe{
		"a loopback target": {Target: &Target{Kind: kindLoopback, PortHint: 80}, Params: map[string]any{"path": "/var"}},
		"a relative path":   {Params: map[string]any{"path": "var"}},
		"no path":           {},
		"another parameter": {Params: map[string]any{"path": "/var", "x": 1}},
	} {
		p.ID, p.Sensor, p.TimeoutS = "f1", "fs", 5
		if res := Run(context.Background(), p, start, nil); res.Status != StatusInvalid {
			t.Errorf("fs with %s = %+v, want invalid", name, res)
		}
	}
}
