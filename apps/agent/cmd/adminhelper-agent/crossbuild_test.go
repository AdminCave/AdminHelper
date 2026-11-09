// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package main

import (
	"os"
	"os/exec"
	"testing"
)

// freebsdPackages are the agent packages that already build for FreeBSD (R-1247). The list grows
// with the port until it is the whole module.
var freebsdPackages = []string{
	"./internal/config/...",
	"./internal/enroll/...",
	"./internal/logging/...",
	"./internal/service/...",
}

// The FreeBSD packages compile for freebsd/amd64, their tests included, and pass go vet. A file
// a FreeBSD build needs that only builds for Linux (a new _linux.go) fails here on the Linux CI,
// long before a FreeBSD box sees it. go test puts its own go first on PATH.
func TestAgentPackagesBuildForFreeBSD(t *testing.T) {
	args := append([]string{"vet"}, freebsdPackages...)
	cmd := exec.Command("go", args...)
	cmd.Dir = "../.."
	cmd.Env = append(os.Environ(), "GOOS=freebsd", "GOARCH=amd64", "CGO_ENABLED=0")
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("GOOS=freebsd go vet %v: %v\n%s", freebsdPackages, err, out)
	}
}
