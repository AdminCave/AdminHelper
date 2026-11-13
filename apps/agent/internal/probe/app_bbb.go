// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// bbbRecordingDir is where BigBlueButton keeps its recordings and the status of their processing
// (recording_dir in bigbluebutton.yml, the packages' default); tests point it elsewhere.
var bbbRecordingDir = "/var/bigbluebutton/recording"

// maxStatusEntries caps the entries the recordings view reads in one status directory: a .done
// marker stays there for every recording ever processed.
const maxStatusEntries = 500_000

// bbbFailSteps are the steps of the recording processing that leave a marker <id>.fail (archive,
// sanity) or <id>-<format>.fail (process, publish) in their status directory when they fail
// (record-and-playback/core/lib/recordandplayback/workers/*_worker.rb).
var bbbFailSteps = []struct{ dir, field string }{
	{"archived", "archive_failed"},
	{"sanity", "sanity_failed"},
	{"processed", "process_failed"},
	{"published", "publish_failed"},
}

// bbbRecordings counts the recordings whose processing failed, by step, and how long ago the newest
// failure was marked. It reads names and the mtime of the markers, never a file's content.
func bbbRecordings(ctx context.Context, _ Target) (map[string]any, error) {
	status := filepath.Join(bbbRecordingDir, "status")
	if info, err := os.Stat(status); err != nil || !info.IsDir() {
		if err == nil || errors.Is(err, fs.ErrNotExist) {
			return nil, fmt.Errorf("%w: no BigBlueButton recording status on this host", ErrUnsupported)
		}
		return nil, errors.New("the BigBlueButton recording status cannot be read")
	}
	values := map[string]any{}
	failed := 0
	var newest time.Time
	for _, step := range bbbFailSteps {
		n, last, err := countFailMarkers(ctx, filepath.Join(status, step.dir), maxStatusEntries)
		if err != nil {
			return nil, fmt.Errorf("status/%s: %w", step.dir, err)
		}
		values[step.field] = n
		failed += n
		if last.After(newest) {
			newest = last
		}
	}
	values["failed"] = failed
	if failed > 0 {
		values["newest_fail_age_s"] = max(int(now().Sub(newest).Seconds()), 0)
	}
	return values, nil
}

// countFailMarkers counts the regular files *.fail in dir and returns the newest mtime among them; a
// step that never ran has no directory yet and no marker. A directory of more than limit entries is
// an error, not counted in part, and so is the end of ctx between two batches of entries.
func countFailMarkers(ctx context.Context, dir string, limit int) (int, time.Time, error) {
	f, err := os.Open(dir)
	if errors.Is(err, fs.ErrNotExist) {
		return 0, time.Time{}, nil
	}
	if err != nil {
		return 0, time.Time{}, errors.New("cannot be read")
	}
	defer f.Close()
	n, seen := 0, 0
	var newest time.Time
	for {
		if err := ctx.Err(); err != nil {
			return 0, time.Time{}, err
		}
		entries, err := f.ReadDir(4096)
		seen += len(entries)
		if seen > limit {
			return 0, time.Time{}, fmt.Errorf("more than %d entries", limit)
		}
		for _, e := range entries {
			if !e.Type().IsRegular() || !strings.HasSuffix(e.Name(), ".fail") {
				continue
			}
			info, err := e.Info()
			if err != nil {
				continue // removed since it was listed
			}
			n++
			if info.ModTime().After(newest) {
				newest = info.ModTime()
			}
		}
		if errors.Is(err, io.EOF) {
			return n, newest, nil
		}
		if err != nil {
			return 0, time.Time{}, errors.New("cannot be read")
		}
	}
}
