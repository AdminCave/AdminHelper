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
	"strings"
	"testing"
	"time"

	"golang.org/x/sys/unix"
)

// bbbWithin runs a view of BigBlueButton and fails the test once it waits beyond a generous bound: a
// FIFO opened for reading waits for a writer that never comes.
func bbbWithin(t *testing.T, view func() (map[string]any, error)) (map[string]any, error) {
	t.Helper()
	type result struct {
		values map[string]any
		err    error
	}
	done := make(chan result, 1)
	go func() {
		values, err := view()
		done <- result{values, err}
	}()
	select {
	case r := <-done:
		return r.values, r.err
	case <-time.After(30 * time.Second):
		t.Fatal("the view waits")
		return nil, nil
	}
}

func recordingsWithin(t *testing.T) (map[string]any, error) {
	t.Helper()
	return bbbWithin(t, func() (map[string]any, error) { return bbbRecordings(context.Background(), Target{}) })
}

// notADirectory puts something that is no directory at path; other is a free path beside it.
var notADirectory = map[string]func(t *testing.T, path, other string){
	"a FIFO": func(t *testing.T, path, _ string) {
		if err := unix.Mkfifo(path, 0o600); err != nil {
			t.Fatal(err)
		}
	},
	"a link to a FIFO": func(t *testing.T, path, other string) {
		if err := unix.Mkfifo(other, 0o600); err != nil {
			t.Fatal(err)
		}
		if err := os.Symlink(other, path); err != nil {
			t.Fatal(err)
		}
	},
	"a link to a directory with a marker": func(t *testing.T, path, other string) {
		if err := os.Mkdir(other, 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(other, "a-1.fail"), nil, 0o644); err != nil {
			t.Fatal(err)
		}
		if err := os.Symlink(other, path); err != nil {
			t.Fatal(err)
		}
	},
}

// A step's directory is opened as a directory and nothing else, and a link there is not followed: a
// FIFO would hold the whole run of the agent, a device can act when it is opened.
func TestTheRecordingsViewOpensAStepOnlyAsADirectory(t *testing.T) {
	for name, put := range notADirectory {
		t.Run(name, func(t *testing.T) {
			root := stubRecordingDir(t)
			put(t, filepath.Join(root, "status", "archived"), filepath.Join(root, "elsewhere"))
			values, err := recordingsWithin(t)
			if err == nil || errors.Is(err, ErrUnsupported) {
				t.Fatalf("values %v, error %v; want a plain error", values, err)
			}
			if strings.Contains(err.Error(), root) {
				t.Errorf("error %q names the path", err)
			}
		})
	}
}

// The status directory is opened as a directory and nothing else, and a link there is not followed;
// the view then finds no recording status, as for a file there.
func TestTheRecordingsViewOpensTheStatusOnlyAsADirectory(t *testing.T) {
	for name, put := range notADirectory {
		t.Run(name, func(t *testing.T) {
			root := stubRecordingDir(t)
			status := filepath.Join(root, "status")
			if err := os.Remove(status); err != nil {
				t.Fatal(err)
			}
			put(t, status, filepath.Join(root, "elsewhere"))
			if values, err := recordingsWithin(t); !errors.Is(err, ErrUnsupported) {
				t.Errorf("values %v, error %v; want ErrUnsupported", values, err)
			}
		})
	}
}

// A properties file of bbb-web is read only as a regular file: a FIFO in its place fails the view at
// once instead of holding it.
func TestTheMeetingsViewReadsItsConfigurationOnlyFromARegularFile(t *testing.T) {
	stubBBBProperties(t, map[int]string{1: "securitySalt=" + testSalt + "\n"})
	if err := unix.Mkfifo(bbbPropertyFiles[0], 0o600); err != nil {
		t.Fatal(err)
	}
	values, err := bbbWithin(t, func() (map[string]any, error) { return bbbMeetings(context.Background(), bbbWeb()) })
	if err == nil || !strings.Contains(err.Error(), "configuration") {
		t.Fatalf("values %v, error %v; want the configuration to fail", values, err)
	}
	holdsNoSecret(t, "error", err.Error(), append(bbbSecrets(testSalt), bbbPropertyFiles[0]))
}

// The markers are read at the directory the view opened: a status directory put at its path since
// counts nothing.
func TestTheRecordingsViewReadsTheMarkersOfTheDirectoryItOpened(t *testing.T) {
	root := t.TempDir()
	put := func(status string, mtime time.Time) {
		dir := filepath.Join(status, "processed")
		if err := os.MkdirAll(dir, 0o755); err != nil {
			t.Fatal(err)
		}
		marker := filepath.Join(dir, "a-1.fail")
		if err := os.WriteFile(marker, nil, 0o644); err != nil {
			t.Fatal(err)
		}
		if err := os.Chtimes(marker, mtime, mtime); err != nil {
			t.Fatal(err)
		}
	}
	opened := time.Date(2026, 1, 2, 3, 4, 5, 0, time.UTC)
	path := filepath.Join(root, "status")
	put(path, opened)
	status, err := openDir(nil, path)
	if err != nil {
		t.Fatal(err)
	}
	defer status.Close()
	if err := os.Rename(path, filepath.Join(root, "moved")); err != nil {
		t.Fatal(err)
	}
	put(path, opened.Add(time.Hour))
	if err := os.Symlink(filepath.Join(root, "moved", "processed", "a-1.fail"), filepath.Join(root, "moved", "processed", "b-1.fail")); err != nil {
		t.Fatal(err)
	}

	n, newest, err := countFailMarkers(context.Background(), status, "processed", 10)
	if err != nil || n != 1 || !newest.Equal(opened) {
		t.Errorf("countFailMarkers = %d, %v, %v; want the one marker of the opened directory, %v", n, newest, err, opened)
	}
}
