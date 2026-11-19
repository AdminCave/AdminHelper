// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package main

import (
	"errors"
	"io"
	"slices"
	"testing"
)

// runUninstallCmd runs service uninstall with args against recording service calls; purge says
// whether the platform supports --purge.
func runUninstallCmd(t *testing.T, purge bool, failUninstall bool, args ...string) (calls []string, err error) {
	t.Helper()
	origSupported, origUninstall, origPurge := purgeSupported, serviceUninstall, servicePurge
	t.Cleanup(func() {
		purgeSupported, serviceUninstall, servicePurge = origSupported, origUninstall, origPurge
	})
	purgeSupported = purge
	serviceUninstall = func() error {
		calls = append(calls, "uninstall")
		if failUninstall {
			return errors.New("uninstall failed")
		}
		return nil
	}
	servicePurge = func() error {
		calls = append(calls, "purge")
		return nil
	}
	cmd := serviceUninstallCmd()
	cmd.SetArgs(args)
	cmd.SetOut(io.Discard)
	cmd.SetErr(io.Discard)
	err = cmd.Execute()
	return calls, err
}

func TestServiceUninstallPurge(t *testing.T) {
	for _, tc := range []struct {
		name          string
		supported     bool
		failUninstall bool
		args          []string
		wantCalls     []string
		wantErr       bool
	}{
		{name: "uninstall alone keeps the files", supported: true, wantCalls: []string{"uninstall"}},
		{name: "purge removes the files after the service", supported: true, args: []string{"--purge"},
			wantCalls: []string{"uninstall", "purge"}},
		{name: "purge waits for a successful uninstall", supported: true, failUninstall: true,
			args: []string{"--purge"}, wantCalls: []string{"uninstall"}, wantErr: true},
		{name: "purge outside Windows changes nothing", args: []string{"--purge"}, wantErr: true},
		{name: "uninstall outside Windows works as before", wantCalls: []string{"uninstall"}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			calls, err := runUninstallCmd(t, tc.supported, tc.failUninstall, tc.args...)
			if (err != nil) != tc.wantErr {
				t.Errorf("err = %v, want error %v", err, tc.wantErr)
			}
			if !slices.Equal(calls, tc.wantCalls) {
				t.Errorf("calls = %q, want %q", calls, tc.wantCalls)
			}
		})
	}
}
