// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package selfupdate

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestTick(t *testing.T) {
	now := time.Date(2026, 11, 20, 12, 0, 0, 0, time.UTC)
	jitter := func() time.Duration { return 30 * time.Minute }
	for _, c := range []struct {
		name     string
		next     time.Time
		wantNext time.Time
		due      bool
	}{
		{"first start", time.Time{}, now.Add(30 * time.Minute), false},
		{"not yet", now.Add(time.Hour), now.Add(time.Hour), false},
		{"due", now.Add(-time.Minute), now.Add(24*time.Hour + 30*time.Minute), true},
		{"due exactly", now, now.Add(24*time.Hour + 30*time.Minute), true},
		{"clock went back", now.Add(3 * 24 * time.Hour), now.Add(30 * time.Minute), false},
		{"latest regular", now.Add(CheckInterval + CheckJitter), now.Add(CheckInterval + CheckJitter), false},
	} {
		t.Run(c.name, func(t *testing.T) {
			st, due := Tick(now, State{Next: c.next}, jitter)
			if due != c.due || !st.Next.Equal(c.wantNext) {
				t.Fatalf("Tick = (%v, %v), want (%v, %v)", st.Next, due, c.wantNext, c.due)
			}
		})
	}
}

func TestStateRoundTrip(t *testing.T) {
	path := filepath.Join(t.TempDir(), "state.json")
	st, err := LoadState(path)
	if err != nil || !st.Next.IsZero() {
		t.Fatalf("missing file: %v, %v", st, err)
	}
	want := State{Next: time.Date(2026, 11, 21, 3, 4, 5, 0, time.UTC)}
	if err := SaveState(path, want); err != nil {
		t.Fatal(err)
	}
	got, err := LoadState(path)
	if err != nil || !got.Next.Equal(want.Next) {
		t.Fatalf("LoadState = %v, %v; want %v", got, err, want)
	}
	if err := os.WriteFile(path, []byte("{"), 0o600); err != nil {
		t.Fatal(err)
	}
	if got, err := LoadState(path); err == nil || !got.Next.IsZero() {
		t.Fatalf("corrupt file: %v, %v; want an error and the zero state", got, err)
	}
}

func TestEnabled(t *testing.T) {
	for v, want := range map[string]bool{
		"": true, "1": true, "yes": true, "0": false, "false": false, "No": false, " off ": false,
	} {
		if got := Enabled(map[string]string{"AUTO_UPDATE": v}); got != want {
			t.Errorf("Enabled(AUTO_UPDATE=%q) = %v, want %v", v, got, want)
		}
	}
	if !Enabled(map[string]string{}) {
		t.Error("Enabled without the key = false, want true")
	}
}
