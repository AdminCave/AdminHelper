// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"strings"
	"testing"
	"time"
)

// stubRecordingDir points the recordings view at a fresh recording directory with an empty status
// directory and returns it.
func stubRecordingDir(t *testing.T) string {
	t.Helper()
	root := t.TempDir()
	if err := os.Mkdir(filepath.Join(root, "status"), 0o755); err != nil {
		t.Fatal(err)
	}
	old := bbbRecordingDir
	bbbRecordingDir = root
	t.Cleanup(func() { bbbRecordingDir = old })
	return root
}

// failMarker writes the file name into status/<step> of root, modified at mod.
func failMarker(t *testing.T, root, step, name string, mod time.Time) {
	t.Helper()
	dir := filepath.Join(root, "status", step)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(dir, name)
	if err := os.WriteFile(path, []byte("secret log line"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.Chtimes(path, mod, mod); err != nil {
		t.Fatal(err)
	}
}

func TestTheRecordingsViewCountsTheFailMarkersOfEachStep(t *testing.T) {
	at := time.Date(2026, 11, 13, 12, 0, 0, 0, time.UTC)
	stubNow(t, at)
	root := stubRecordingDir(t)
	id := "6e35e3b2778883f5db637d7a5dba0a427f692e91-1700000000000"
	failMarker(t, root, "archived", id+".done", at.Add(-48*time.Hour))
	failMarker(t, root, "archived", "a-1.fail", at.Add(-5*time.Hour))
	failMarker(t, root, "sanity", "b-2.fail", at.Add(-4*time.Hour))
	failMarker(t, root, "sanity", "c-3.fail", at.Add(-3*time.Hour))
	failMarker(t, root, "processed", id+"-presentation.done", at.Add(-time.Hour))
	failMarker(t, root, "processed", "d-4-presentation.fail", at.Add(-90*time.Minute))
	failMarker(t, root, "published", "e-5-video.fail", at.Add(-2*time.Hour))
	failMarker(t, root, "published", id+"-presentation.done", at.Add(-time.Hour))
	failMarker(t, root, "recorded", "f-6.fail", at.Add(-time.Minute)) // no step of the view
	if err := os.Mkdir(filepath.Join(root, "status", "sanity", "g-7.fail"), 0o755); err != nil {
		t.Fatal(err)
	}
	// Windows lets only privileged users link; without the link the count is the same.
	sanity := filepath.Join(root, "status", "sanity")
	err := os.Symlink(filepath.Join(sanity, "b-2.fail"), filepath.Join(sanity, "h-8.fail"))
	if err != nil && runtime.GOOS != "windows" {
		t.Fatal(err)
	}
	got, err := bbbRecordings(context.Background(), Target{Kind: kindUnit, Name: "bbb-web.service"})
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]any{
		"failed": 5, "archive_failed": 1, "sanity_failed": 2, "process_failed": 1, "publish_failed": 1,
		"newest_fail_age_s": 5400,
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("values %v, want %v (only regular files *.fail of the four steps)", got, want)
	}
}

func TestTheRecordingsViewHasNoAgeWithoutAFailure(t *testing.T) {
	at := time.Date(2026, 11, 13, 12, 0, 0, 0, time.UTC)
	stubNow(t, at)
	root := stubRecordingDir(t)
	failMarker(t, root, "archived", "a-1.done", at.Add(-time.Hour))
	got, err := bbbRecordings(context.Background(), Target{})
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]any{"failed": 0, "archive_failed": 0, "sanity_failed": 0, "process_failed": 0, "publish_failed": 0}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("values %v, want %v", got, want)
	}
}

func TestTheRecordingsViewIsUnsupportedWithoutAStatusDirectory(t *testing.T) {
	old := bbbRecordingDir
	bbbRecordingDir = filepath.Join(t.TempDir(), "recording")
	t.Cleanup(func() { bbbRecordingDir = old })
	if _, err := bbbRecordings(context.Background(), Target{}); !errors.Is(err, ErrUnsupported) {
		t.Errorf("error %v, want ErrUnsupported", err)
	}
	// A file where the directory belongs is no BigBlueButton either.
	if err := os.MkdirAll(bbbRecordingDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(bbbRecordingDir, "status"), nil, 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := bbbRecordings(context.Background(), Target{}); !errors.Is(err, ErrUnsupported) {
		t.Errorf("error %v, want ErrUnsupported", err)
	}
}

func TestTheRecordingsViewStopsAtTheEntryCap(t *testing.T) {
	root := stubRecordingDir(t)
	dir := filepath.Join(root, "status", "processed")
	if err := os.Mkdir(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	for i := range 3 {
		if err := os.WriteFile(filepath.Join(dir, strings.Repeat("x", i+1)+".fail"), nil, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	if got, _, err := countFailMarkers(context.Background(), dir, 3); err != nil || got != 3 {
		t.Fatalf("countFailMarkers = %d, %v; want 3 at the cap", got, err)
	}
	n, _, err := countFailMarkers(context.Background(), dir, 2)
	if err == nil || n != 0 || !strings.Contains(err.Error(), "more than 2 entries") {
		t.Errorf("over the cap: %d, %v; want an error and no count", n, err)
	}
}

func TestTheRecordingsViewFailsWithoutNamingPathOrContent(t *testing.T) {
	root := stubRecordingDir(t)
	// A file where a step's directory belongs opens but cannot be listed, on every platform.
	if err := os.WriteFile(filepath.Join(root, "status", "processed"), []byte("salt-0123456789abcdef"), 0o644); err != nil {
		t.Fatal(err)
	}
	_, err := bbbRecordings(context.Background(), Target{})
	if err == nil || errors.Is(err, ErrUnsupported) || errors.Is(err, ErrInvalid) {
		t.Fatalf("error %v, want a plain error", err)
	}
	res := Run(context.Background(), appProbe("bbb_recordings", unitTarget("bbb-web.service")), time.Now(), nil)
	if res.Status != StatusError {
		t.Errorf("status %s, want error", res.Status)
	}
	for _, text := range []string{err.Error(), res.Error} {
		if strings.Contains(text, root) || strings.Contains(text, "salt-0123456789abcdef") {
			t.Errorf("error %q names the path or the content", text)
		}
	}
}

func TestTheRecordingsViewStopsWhenTheContextEnds(t *testing.T) {
	root := stubRecordingDir(t)
	failMarker(t, root, "sanity", "a-1.fail", time.Now())
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := bbbRecordings(ctx, Target{}); !errors.Is(err, context.Canceled) {
		t.Errorf("error %v, want context.Canceled", err)
	}
}
