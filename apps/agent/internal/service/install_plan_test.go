// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package service

import (
	"errors"
	"slices"
	"testing"
)

const newAgent = `C:\Program Files\AdminHelper Agent\adminhelper-agent.exe`

// fakeInstall records the steps runInstall takes; fail names a step that fails.
type fakeInstall struct {
	registered bool
	oldBinary  string
	fail       string
	steps      []string
	warnings   int
}

func (f *fakeInstall) step(name string) error {
	f.steps = append(f.steps, name)
	if f.fail == name {
		return errors.New(name + " failed")
	}
	return nil
}

func (f *fakeInstall) hooks() installHooks {
	return installHooks{
		lookup: func() (bool, string, error) {
			return f.registered, f.oldBinary, f.step("lookup")
		},
		stop:      func() error { return f.step("stop") },
		place:     func() error { return f.step("place") },
		create:    func() error { return f.step("create") },
		update:    func() error { return f.step("update") },
		extras:    func() { _ = f.step("extras") },
		removeOld: func(binary string) error { return f.step("removeOld " + binary) },
		start:     func() error { return f.step("start") },
		warnf:     func(string, ...any) { f.warnings++ },
	}
}

func TestRunInstall(t *testing.T) {
	const legacy = `C:\Program Files\AdminHelper\adminhelper-agent.exe`
	for _, tc := range []struct {
		name       string
		registered bool
		oldBinary  string
		fail       string
		wantSteps  []string
		wantErr    bool
		wantWarn   int
	}{
		{
			name:      "a first install registers the service",
			wantSteps: []string{"lookup", "place", "create", "extras", "start"},
		},
		{
			name:       "a second install stops, replaces and starts the service",
			registered: true, oldBinary: newAgent,
			wantSteps: []string{"lookup", "stop", "place", "update", "extras", "start"},
		},
		{
			name:       "the same binary in other case is no earlier install",
			registered: true, oldBinary: `c:\program files\adminhelper agent\ADMINHELPER-AGENT.EXE`,
			wantSteps: []string{"lookup", "stop", "place", "update", "extras", "start"},
		},
		{
			name:       "an install in the old folder moves to the new one",
			registered: true, oldBinary: legacy,
			wantSteps: []string{"lookup", "stop", "place", "update", "extras", "removeOld " + legacy, "start"},
		},
		{
			name:       "a failed lookup changes nothing",
			registered: true, oldBinary: newAgent, fail: "lookup",
			wantSteps: []string{"lookup"}, wantErr: true,
		},
		{
			name:       "a service that does not stop keeps its files",
			registered: true, oldBinary: legacy, fail: "stop",
			wantSteps: []string{"lookup", "stop"}, wantErr: true,
		},
		{
			name:       "files that cannot be placed leave the old service running",
			registered: true, oldBinary: legacy, fail: "place",
			wantSteps: []string{"lookup", "stop", "place", "start"}, wantErr: true,
		},
		{
			name:      "a service that cannot be registered is not started",
			fail:      "create",
			wantSteps: []string{"lookup", "place", "create"}, wantErr: true,
		},
		{
			name:      "a first install whose files cannot be placed registers nothing",
			fail:      "place",
			wantSteps: []string{"lookup", "place"}, wantErr: true,
		},
		{
			name:       "the old binary stays and runs when the service cannot be pointed at the new one",
			registered: true, oldBinary: legacy, fail: "update",
			wantSteps: []string{"lookup", "stop", "place", "update", "start"}, wantErr: true,
		},
		{
			name:       "an old binary that cannot be removed only warns",
			registered: true, oldBinary: legacy, fail: "removeOld " + legacy,
			wantSteps: []string{"lookup", "stop", "place", "update", "extras", "removeOld " + legacy, "start"},
			wantWarn:  1,
		},
		{
			name:      "a service that does not start only warns",
			fail:      "start",
			wantSteps: []string{"lookup", "place", "create", "extras", "start"},
			wantWarn:  1,
		},
	} {
		t.Run(tc.name, func(t *testing.T) {
			f := &fakeInstall{registered: tc.registered, oldBinary: tc.oldBinary, fail: tc.fail}
			err := runInstall(f.hooks(), newAgent)
			if (err != nil) != tc.wantErr {
				t.Errorf("runInstall = %v, want error %v", err, tc.wantErr)
			}
			if !slices.Equal(f.steps, tc.wantSteps) {
				t.Errorf("steps = %q, want %q", f.steps, tc.wantSteps)
			}
			if f.warnings != tc.wantWarn {
				t.Errorf("warnings = %d, want %d", f.warnings, tc.wantWarn)
			}
		})
	}
}

func TestServiceBinary(t *testing.T) {
	for in, want := range map[string]string{
		`"C:\Program Files\AdminHelper\adminhelper-agent.exe" run`:   `C:\Program Files\AdminHelper\adminhelper-agent.exe`,
		`"C:\Program Files\AdminHelper Agent\adminhelper-agent.exe"`: `C:\Program Files\AdminHelper Agent\adminhelper-agent.exe`,
		`C:\agent\adminhelper-agent.exe run`:                         `C:\agent\adminhelper-agent.exe`,
		` "C:\unterminated`:                                          `C:\unterminated`,
		``:                                                           ``,
	} {
		if got := serviceBinary(in); got != want {
			t.Errorf("serviceBinary(%q) = %q, want %q", in, got, want)
		}
	}
}
