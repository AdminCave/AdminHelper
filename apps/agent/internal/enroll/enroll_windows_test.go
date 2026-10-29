// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package enroll

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"testing"

	"golang.org/x/sys/windows"

	"adminhelper-agent/internal/config"
)

// descriptorOf returns the owner and the DACL of path as an SDDL string.
func descriptorOf(t *testing.T, path string) string {
	t.Helper()
	sd, err := windows.GetNamedSecurityInfo(path, windows.SE_FILE_OBJECT,
		windows.OWNER_SECURITY_INFORMATION|windows.DACL_SECURITY_INFORMATION)
	if err != nil {
		t.Fatalf("read the security descriptor of %s: %v", path, err)
	}
	return sd.String()
}

// ownerOf returns the owner of path as a SID string.
func ownerOf(t *testing.T, path string) string {
	t.Helper()
	sd, err := windows.GetNamedSecurityInfo(path, windows.SE_FILE_OBJECT, windows.OWNER_SECURITY_INFORMATION)
	if err != nil {
		t.Fatalf("read the owner of %s: %v", path, err)
	}
	owner, _, err := sd.Owner()
	if err != nil {
		t.Fatalf("read the owner of %s: %v", path, err)
	}
	return owner.String()
}

// LockIdentity, CheckStorable and Store secure the data root before the identity
// directory in it: a junction at the root is replaced, and the identity directory
// behind it keeps its descriptor and its file. Securing only the identity directory
// would open the root by path, follow the junction and lock or remove the directory
// behind it, and the identity would be written there.
func TestIdentitySecuresTheDataRootFirst(t *testing.T) {
	key, err := GenerateKey()
	if err != nil {
		t.Fatal(err)
	}
	resp := &IssueResponse{Cert: "leaf", Fullchain: "leaf+int", Chain: "int+root"}
	cases := []struct {
		name string
		run  func(dir string) error
	}{
		{"LockIdentity", func(dir string) error {
			unlock, err := LockIdentity(context.Background(), dir)
			if err == nil {
				unlock()
			}
			return err
		}},
		{"CheckStorable", CheckStorable},
		{"Store", func(dir string) error { return Store(dir, key, resp) }},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			base := t.TempDir()
			target := filepath.Join(base, "target")
			behind := filepath.Join(target, "identity")
			outside := filepath.Join(behind, "outside.txt")
			if err := os.MkdirAll(behind, 0o700); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(outside, []byte("outside"), 0o600); err != nil {
				t.Fatal(err)
			}
			behindSD, outsideSD := descriptorOf(t, behind), descriptorOf(t, outside)
			root := filepath.Join(base, "root")
			if out, err := exec.Command("cmd", "/c", "mklink", "/J", root, target).CombinedOutput(); err != nil {
				t.Fatalf("mklink /J %s %s: %v: %s", root, target, err, out)
			}
			t.Setenv("ADMINHELPER_MONITOR_DIR", root)
			dir := config.AgentPkiDir()

			if err := c.run(dir); err != nil {
				t.Fatalf("%s: %v", c.name, err)
			}

			info, err := os.Lstat(root)
			if err != nil {
				t.Fatal(err)
			}
			if !info.IsDir() || info.Mode()&(os.ModeSymlink|os.ModeIrregular) != 0 {
				t.Fatalf("the data root %s is not a plain directory: mode %v", root, info.Mode())
			}
			if info, err := os.Lstat(dir); err != nil || !info.IsDir() {
				t.Fatalf("the identity directory %s is missing (%v)", dir, err)
			}
			if got := descriptorOf(t, behind); got != behindSD {
				t.Fatalf("the descriptor of %s behind the junction changed: %s, was %s", behind, got, behindSD)
			}
			if got := descriptorOf(t, outside); got != outsideSD {
				t.Fatalf("the descriptor of %s changed: %s, was %s", outside, got, outsideSD)
			}
			if entries, err := os.ReadDir(behind); err != nil || len(entries) != 1 {
				t.Fatalf("%s behind the junction holds %d entries (%v), want only outside.txt", behind, len(entries), err)
			}
			if got, err := os.ReadFile(outside); err != nil || string(got) != "outside" {
				t.Fatalf("the content of %s: %q, %v", outside, got, err)
			}
		})
	}
}

// Store hands key, certificate and CA to the Administrators before it renames them
// into place, also where a new file belongs to the account that writes it: here
// createTemp hands out staged files the test account owns.
func TestStoreHandsTheIdentityToTheAdministrators(t *testing.T) {
	user, err := windows.GetCurrentProcessToken().GetTokenUser()
	if err != nil {
		t.Fatal(err)
	}
	orig := createTemp
	createTemp = func(dir, pattern string) (*os.File, error) {
		f, err := orig(dir, pattern)
		if err != nil {
			return nil, err
		}
		if err := f.Close(); err != nil {
			return nil, err
		}
		if err := windows.SetNamedSecurityInfo(f.Name(), windows.SE_FILE_OBJECT, windows.OWNER_SECURITY_INFORMATION,
			user.User.Sid, nil, nil, nil); err != nil {
			return nil, err
		}
		return os.OpenFile(f.Name(), os.O_RDWR, 0)
	}
	t.Cleanup(func() { createTemp = orig })
	// The seam works: a file it hands out belongs to the test account.
	probe, err := createTemp(t.TempDir(), "probe.*")
	if err != nil {
		t.Fatal(err)
	}
	if err := probe.Close(); err != nil {
		t.Fatal(err)
	}
	if got := ownerOf(t, probe.Name()); got != user.User.Sid.String() {
		t.Fatalf("the probe %s is owned by %s, want the test account %s", probe.Name(), got, user.User.Sid)
	}
	t.Setenv("ADMINHELPER_MONITOR_DIR", t.TempDir())
	dir := config.AgentPkiDir()
	key, err := GenerateKey()
	if err != nil {
		t.Fatal(err)
	}

	if err := Store(dir, key, &IssueResponse{Cert: "leaf", Fullchain: "leaf+int", Chain: "int+root"}); err != nil {
		t.Fatalf("Store: %v", err)
	}
	for _, p := range []string{KeyPath(dir), CertPath(dir), CAPath(dir)} {
		if got := ownerOf(t, p); got != administratorsSID {
			t.Errorf("%s is owned by %s, want the Administrators %s", p, got, administratorsSID)
		}
	}
}
