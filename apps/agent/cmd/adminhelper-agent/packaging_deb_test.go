// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package main

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// dpkg runs the maintainer scripts under their own set -e: an unguarded systemctl call
// without systemd as PID 1 (a container, a chroot) fails the whole install or removal
// (R-1670). The scripts run on the systemctl stub of packaging_rpm_test.go with /etc/
// pointing into the host's root.
func TestDEBMaintainerScriptsPassWithoutSystemd(t *testing.T) {
	t.Setenv("AH_SYSTEMCTL_DOWN", "1")
	for _, tc := range []struct {
		name  string
		steps [][2]string // script, $1
	}{
		{"install", [][2]string{{"postinst", "configure"}}},
		{"upgrade", [][2]string{{"prerm", "upgrade"}, {"postrm", "upgrade"}, {"postinst", "configure"}}},
		{"remove", [][2]string{{"prerm", "remove"}, {"postrm", "remove"}}},
		{"purge", [][2]string{{"postrm", "purge"}}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			h := newRPMHost(t, true)
			for _, s := range tc.steps {
				data, err := os.ReadFile(filepath.Join("../../deb/DEBIAN", s[0]))
				if err != nil {
					t.Fatal(err)
				}
				script := filepath.Join(h.scripts, s[0])
				body := strings.ReplaceAll(string(data), "/etc/", h.root+"/etc/")
				if err := os.WriteFile(script, []byte(body), 0o600); err != nil {
					t.Fatal(err)
				}
				cmd := exec.Command("/bin/sh", script, s[1])
				cmd.Env = append(os.Environ(), "PATH="+h.path, "AH_SYSTEMCTL_STATE="+h.state)
				out, err := cmd.CombinedOutput()
				if err != nil {
					t.Fatalf("%s %s: %v\n%s", s[0], s[1], err, out)
				}
				// The guard keeps the failed reload out of the dpkg output, too.
				if strings.Contains(string(out), "has not been booted") {
					t.Errorf("%s %s shows the failed systemctl call:\n%s", s[0], s[1], out)
				}
			}
		})
	}
}
