// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux || freebsd

package probe

import (
	"errors"
	"io"
	"os"
	"path/filepath"
	"syscall"
	"testing"
	"time"
)

// stubReopen counts the files openChecked opens for reading; before each it runs between, if not nil.
func stubReopen(t *testing.T, between func()) *int {
	t.Helper()
	calls := 0
	old := reopenChecked
	reopenChecked = func(p *os.File) (*os.File, error) {
		calls++
		if between != nil {
			between()
		}
		return old(p)
	}
	t.Cleanup(func() { reopenChecked = old })
	return &calls
}

func TestOpenCheckedNeverOpensADeviceOrAFIFOForReading(t *testing.T) {
	dir := t.TempDir()
	fifo := filepath.Join(dir, "fifo")
	if err := syscall.Mkfifo(fifo, 0o600); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(dir, "link")
	if err := os.Symlink("/dev/zero", link); err != nil {
		t.Fatal(err)
	}
	// A writer of the FIFO waits in its open until a reader opens it: a read open shows as its end.
	written := make(chan struct{})
	go func() {
		if w, err := os.OpenFile(fifo, os.O_WRONLY, 0); err == nil {
			close(written)
			_ = w.Close()
		}
	}()
	time.Sleep(100 * time.Millisecond)
	t.Cleanup(func() {
		if r, err := os.OpenFile(fifo, os.O_RDONLY|syscall.O_NONBLOCK, 0); err == nil {
			<-written
			_ = r.Close()
		}
	})
	calls := stubReopen(t, nil)
	for _, path := range []string{fifo, "/dev/null", link, dir} {
		if f, err := openChecked(path); err == nil {
			_ = f.Close()
			t.Errorf("openChecked(%s) opened it, want it refused", path)
		}
	}
	if *calls != 0 {
		t.Errorf("%d of them opened for reading, want none", *calls)
	}
	select {
	case <-written:
		t.Error("the FIFO was opened for reading")
	case <-time.After(200 * time.Millisecond):
	}

	plain := filepath.Join(dir, "plain")
	if err := os.WriteFile(plain, []byte("plain"), 0o600); err != nil {
		t.Fatal(err)
	}
	if data, err := readSmallFile(plain, 10); err != nil || string(data) != "plain" {
		t.Errorf("readSmallFile(regular file) = %q, %v", data, err)
	}
	if _, err := openChecked(filepath.Join(dir, "gone")); !errors.Is(err, os.ErrNotExist) {
		t.Errorf("openChecked(missing file) = %v, want it not to exist", err)
	}
}

// A file put at the path between the check and the open for reading is never read: the agent reads
// the file it checked.
func TestOpenCheckedReadsTheFileItChecked(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "conf")
	if err := os.WriteFile(path, []byte("checked"), 0o600); err != nil {
		t.Fatal(err)
	}
	for name, put := range map[string]func(string) error{
		"a FIFO":         func(p string) error { return syscall.Mkfifo(p, 0o600) },
		"another file":   func(p string) error { return os.WriteFile(p, []byte("swapped"), 0o600) },
		"a link to null": func(p string) error { return os.Symlink("/dev/null", p) },
	} {
		t.Run(name, func(t *testing.T) {
			// What the run before put there may be a FIFO, which a write would wait on.
			_ = os.Remove(path)
			if err := os.WriteFile(path, []byte("checked"), 0o600); err != nil {
				t.Fatal(err)
			}
			stubReopen(t, func() {
				other := filepath.Join(dir, "other")
				_ = os.Remove(other)
				if err := put(other); err != nil {
					t.Error(err)
				}
				if err := os.Rename(other, path); err != nil {
					t.Error(err)
				}
			})
			f, err := openChecked(path)
			if err != nil {
				t.Fatalf("openChecked = %v", err)
			}
			defer f.Close()
			if data, err := io.ReadAll(f); err != nil || string(data) != "checked" {
				t.Errorf("read %q, %v; want the file that was checked", data, err)
			}
		})
	}
}
