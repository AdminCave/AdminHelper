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

// EnsureSecureDir leaves a secret-bearing dir owner-only (0700), whether it creates
// the dir (with its parents) or finds it open; an existing dir keeps its files.
func TestEnsureSecureDirRestrictsToOwner(t *testing.T) {
	cases := []struct {
		name     string
		existing bool
	}{
		{"new, with a missing parent", false},
		{"existing and open", true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			dir := filepath.Join(t.TempDir(), "parent", "secret")
			kept := filepath.Join(dir, "keep")
			if tc.existing {
				if err := os.MkdirAll(dir, 0o777); err != nil {
					t.Fatal(err)
				}
				if err := os.Chmod(dir, 0o777); err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(kept, []byte("x"), 0o600); err != nil {
					t.Fatal(err)
				}
			}
			if err := EnsureSecureDir(dir); err != nil {
				t.Fatalf("EnsureSecureDir: %v", err)
			}
			info, err := os.Stat(dir)
			if err != nil {
				t.Fatal(err)
			}
			if !info.IsDir() {
				t.Fatalf("%s is not a directory", dir)
			}
			if perm := info.Mode().Perm(); perm != 0o700 {
				t.Fatalf("perm = %o, want 0700", perm)
			}
			if tc.existing {
				if _, err := os.Stat(kept); err != nil {
					t.Fatalf("the existing file is gone: %v", err)
				}
			}
		})
	}
}

// On Windows EnsureSecureDir keeps only an existing dir that SYSTEM or the
// Administrators own.
func TestTrustedOwner(t *testing.T) {
	cases := []struct {
		name string
		sid  string
		want bool
	}{
		{"SYSTEM", "S-1-5-18", true},
		{"Administrators", "S-1-5-32-544", true},
		{"Users", "S-1-5-32-545", false},
		{"a local user", "S-1-5-21-1111111111-2222222222-3333333333-1001", false},
		{"Everyone", "S-1-1-0", false},
		{"Administrators with a suffix", "S-1-5-32-5440", false},
		{"no owner", "", false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := trustedOwner(tc.sid); got != tc.want {
				t.Fatalf("trustedOwner(%q) = %v, want %v", tc.sid, got, tc.want)
			}
		})
	}
}
