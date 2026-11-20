// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package selfupdate

import (
	"encoding/json"
	"errors"
	"os"
	"strings"
	"time"
)

// A host checks once a day; the jitter spreads a fleet that starts together over two hours, so
// that it does not fetch from the server at the same minute.
const (
	CheckInterval = 24 * time.Hour
	CheckJitter   = 2 * time.Hour
)

// State is what the service keeps between restarts: the time of the next check.
type State struct {
	Next time.Time `json:"next"`
}

// LoadState reads the state file; a missing file is the zero state of a first start.
func LoadState(path string) (State, error) {
	var st State
	b, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return st, nil
	}
	if err != nil {
		return st, err
	}
	if err := json.Unmarshal(b, &st); err != nil {
		return State{}, err
	}
	return st, nil
}

// SaveState writes the state file through a temporary file, so that a crash leaves the old one.
func SaveState(path string, st State) error {
	b, err := json.Marshal(st)
	if err != nil {
		return err
	}
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, b, 0o600); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

// Tick reports whether a check is due at now and returns the state with the check after it.
// jitter returns a duration in [0, CheckJitter).
func Tick(now time.Time, st State, jitter func() time.Duration) (State, bool) {
	// A first start, or a clock that went back by more than a day: the first check comes within
	// the jitter rather than days later.
	if st.Next.IsZero() || st.Next.After(now.Add(CheckInterval+CheckJitter)) {
		st.Next = now.Add(jitter())
		return st, false
	}
	if now.Before(st.Next) {
		return st, false
	}
	st.Next = now.Add(CheckInterval + jitter())
	return st, true
}

// Enabled reports whether the agent configuration allows the self-update: on unless AUTO_UPDATE
// says otherwise.
func Enabled(conf map[string]string) bool {
	switch strings.ToLower(strings.TrimSpace(conf["AUTO_UPDATE"])) {
	case "0", "false", "no", "off":
		return false
	}
	return true
}
