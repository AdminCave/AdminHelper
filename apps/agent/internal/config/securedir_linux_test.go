// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package config

import (
	"os"
	"path/filepath"
	"testing"
)

// SecureDir must clamp a secret-bearing dir to owner-only (0700), even if it was
// created — or squatted — world-accessible; the Linux half of the 3.1 hardening.
func TestSecureDirRestrictsToOwner(t *testing.T) {
	sub := filepath.Join(t.TempDir(), "secret")
	if err := os.MkdirAll(sub, 0o777); err != nil {
		t.Fatal(err)
	}
	if err := SecureDir(sub); err != nil {
		t.Fatalf("SecureDir: %v", err)
	}
	info, err := os.Stat(sub)
	if err != nil {
		t.Fatal(err)
	}
	if perm := info.Mode().Perm(); perm != 0o700 {
		t.Fatalf("perm = %o, want 0700", perm)
	}
}
