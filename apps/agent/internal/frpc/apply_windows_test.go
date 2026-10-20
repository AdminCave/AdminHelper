// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package frpc

import (
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

// holdForeignChild writes the file name in dir, gives it to the test account, which
// makes it foreign to EnsureSecureDir, and keeps it open without FILE_SHARE_DELETE
// until the test ends, so that it cannot be removed.
func holdForeignChild(t *testing.T, dir, name string) {
	t.Helper()
	path := filepath.Join(dir, name)
	if err := os.WriteFile(path, []byte("x"), 0o600); err != nil {
		t.Fatal(err)
	}
	user, err := windows.GetCurrentProcessToken().GetTokenUser()
	if err != nil {
		t.Fatal(err)
	}
	if err := windows.SetNamedSecurityInfo(path, windows.SE_FILE_OBJECT, windows.OWNER_SECURITY_INFORMATION,
		user.User.Sid, nil, nil, nil); err != nil {
		t.Fatalf("give %s to the test account: %v", path, err)
	}
	name16, err := windows.UTF16PtrFromString(path)
	if err != nil {
		t.Fatal(err)
	}
	h, err := windows.CreateFile(name16, windows.GENERIC_READ, windows.FILE_SHARE_READ, nil, windows.OPEN_EXISTING,
		windows.FILE_ATTRIBUTE_NORMAL, 0)
	if err != nil {
		t.Fatalf("open %s: %v", path, err)
	}
	t.Cleanup(func() { windows.CloseHandle(h) })
}

// WriteSyncConfig secures the data root before its frp directory: a junction at the
// root is replaced, and the frp directory behind it keeps its descriptor and its file.
// Securing frp alone would open the root by path, follow the junction, lock or remove
// the frp directory behind it and write the sync config there.
func TestWriteSyncConfigSecuresTheDataRootFirst(t *testing.T) {
	base := t.TempDir()
	target := filepath.Join(base, "target")
	behind := filepath.Join(target, "frp")
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
	t.Setenv("ADMINHELPER_FRP_DIR", filepath.Join(root, "frp"))

	if err := WriteSyncConfig(SyncConfigParams{
		AdminHelperURL: "https://srv.example",
		ServerID:       "srv-1",
		APIKey:         "key-1",
		TLS:            config.TLSOpts{Insecure: true},
	}); err != nil {
		t.Fatalf("WriteSyncConfig: %v", err)
	}

	info, err := os.Lstat(root)
	if err != nil {
		t.Fatal(err)
	}
	if !info.IsDir() || info.Mode()&(os.ModeSymlink|os.ModeIrregular) != 0 {
		t.Fatalf("the data root %s is not a plain directory: mode %v", root, info.Mode())
	}
	if _, err := os.Stat(config.FrpAdminHelperConf()); err != nil {
		t.Fatalf("sync config: %v", err)
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
}

// WriteSyncConfig fails and writes no sync config when the data root cannot be
// secured: the open root holds a child of another account that is held open, so
// that it cannot be removed. frp exists already, so a run that went on after the
// error could write the API key there.
func TestWriteSyncConfigFailsWhenTheDataRootCannotBeSecured(t *testing.T) {
	root := t.TempDir()
	frpDir := filepath.Join(root, "frp")
	if err := os.Mkdir(frpDir, 0o700); err != nil {
		t.Fatal(err)
	}
	// Named to come before frp, so that the cleanup of the root stops at it first.
	holdForeignChild(t, root, "a-held.txt")
	t.Setenv("ADMINHELPER_MONITOR_DIR", root)
	t.Setenv("ADMINHELPER_FRP_DIR", frpDir)

	if err := WriteSyncConfig(SyncConfigParams{
		AdminHelperURL: "https://srv.example",
		ServerID:       "srv-1",
		APIKey:         "key-1",
		TLS:            config.TLSOpts{Insecure: true},
	}); err == nil {
		t.Fatal("WriteSyncConfig returned no error although the data root could not be secured")
	}
	if _, err := os.Stat(config.FrpAdminHelperConf()); !os.IsNotExist(err) {
		t.Fatalf("the sync config with the API key was written (Stat: %v)", err)
	}
}
