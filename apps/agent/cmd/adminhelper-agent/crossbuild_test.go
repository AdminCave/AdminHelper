// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package main

import (
	"os"
	"os/exec"
	"testing"
)

// The whole agent module compiles for freebsd/amd64 (R-1247), its tests included, and passes go vet.
// A file a FreeBSD build needs that only builds for Linux (a new _linux.go) fails here on the Linux
// CI, long before a FreeBSD box sees it. go test puts its own go first on PATH.
func TestAgentPackagesBuildForFreeBSD(t *testing.T) {
	cmd := exec.Command("go", "vet", "./...")
	cmd.Dir = "../.."
	cmd.Env = append(os.Environ(), "GOOS=freebsd", "GOARCH=amd64", "CGO_ENABLED=0")
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("GOOS=freebsd go vet ./...: %v\n%s", err, out)
	}
}
