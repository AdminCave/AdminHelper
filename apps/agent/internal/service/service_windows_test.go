// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package service

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
	"time"
	"unsafe"

	"golang.org/x/sys/windows"
	"golang.org/x/sys/windows/registry"
	"golang.org/x/sys/windows/svc/eventlog"

	"adminhelper-agent/internal/logging"
)

// A repeated service install and uninstall must not fail on the event source: the
// helpers register it once and keep it on a second registration, and remove it once
// and accept its absence on a second removal. The source has a name of its own, so
// that the test leaves the source of an installed agent alone, and the cleanup removes
// it also when the test fails.
func TestEventSourceRegistrationAndRemovalAreRepeatable(t *testing.T) {
	source := fmt.Sprintf("%s-Test-%d-%d", logging.EventSource, os.Getpid(), time.Now().UnixNano())
	key := `SYSTEM\CurrentControlSet\Services\EventLog\Application\` + source
	t.Cleanup(func() {
		if err := eventlog.Remove(source); err != nil && !errors.Is(err, registry.ErrNotExist) {
			t.Errorf("remove the test source %s: %v", source, err)
		}
	})

	if err := registerEventSource(source); err != nil {
		t.Fatalf("first registration: %v", err)
	}
	if err := registerEventSource(source); err != nil {
		t.Errorf("second registration of an existing source: %v", err)
	}
	k, err := registry.OpenKey(registry.LOCAL_MACHINE, key, registry.QUERY_VALUE)
	if err != nil {
		t.Fatalf(`HKLM\%s is missing after the registration: %v`, key, err)
	}
	msgFile, _, err := k.GetStringValue("EventMessageFile")
	if err != nil || !strings.HasSuffix(strings.ToLower(msgFile), `\eventcreate.exe`) {
		t.Errorf("EventMessageFile is %q (%v), want EventCreate.exe", msgFile, err)
	}
	types, _, err := k.GetIntegerValue("TypesSupported")
	if want := uint64(eventlog.Error | eventlog.Warning | eventlog.Info); err != nil || types != want {
		t.Errorf("TypesSupported is %d (%v), want %d (errors, warnings, information)", types, err, want)
	}
	k.Close()

	if err := removeEventSource(source); err != nil {
		t.Fatalf("first removal: %v", err)
	}
	if err := removeEventSource(source); err != nil {
		t.Errorf("second removal of a missing source: %v", err)
	}
	if k, err := registry.OpenKey(registry.LOCAL_MACHINE, key, registry.QUERY_VALUE); err == nil {
		k.Close()
		t.Errorf(`HKLM\%s is still there after the removal`, key)
	} else if !errors.Is(err, registry.ErrNotExist) {
		t.Errorf(`open HKLM\%s after the removal: %v`, key, err)
	}
}

// The program directory gets the protected DACL of the data directory, also when it
// already exists with the inherited rights of its parent: afterwards it grants only
// SYSTEM and the Administrators, none of it inherited.
func TestPrepareInstallDirProtectsAnExistingDirectory(t *testing.T) {
	for _, existing := range []bool{false, true} {
		dir := filepath.Join(t.TempDir(), "AdminHelper")
		if existing {
			if err := os.Mkdir(dir, 0o755); err != nil {
				t.Fatal(err)
			}
		}
		if err := prepareInstallDir(dir); err != nil {
			t.Fatalf("existing=%v: %v", existing, err)
		}
		sd, err := windows.GetNamedSecurityInfo(dir, windows.SE_FILE_OBJECT,
			windows.OWNER_SECURITY_INFORMATION|windows.DACL_SECURITY_INFORMATION)
		if err != nil {
			t.Fatal(err)
		}
		assertOwnedByAdministrators(t, sd, dir)
		control, _, err := sd.Control()
		if err != nil {
			t.Fatal(err)
		}
		if control&windows.SE_DACL_PROTECTED == 0 {
			t.Fatalf("existing=%v: the DACL of %s is not protected: %s", existing, dir, sd)
		}
		dacl, _, err := sd.DACL()
		if err != nil {
			t.Fatal(err)
		}
		var sids []string
		for i := uint32(0); i < uint32(dacl.AceCount); i++ {
			var ace *windows.ACCESS_ALLOWED_ACE
			if err := windows.GetAce(dacl, i, &ace); err != nil {
				t.Fatal(err)
			}
			if ace.Header.AceFlags&windows.INHERITED_ACE != 0 {
				t.Fatalf("existing=%v: %s keeps an inherited ACE: %s", existing, dir, sd)
			}
			sid := (*windows.SID)(unsafe.Pointer(&ace.SidStart))
			sids = append(sids, sid.String())
		}
		slices.Sort(sids)
		sids = slices.Compact(sids)
		if want := []string{"S-1-5-18", "S-1-5-32-544"}; !slices.Equal(sids, want) {
			t.Fatalf("existing=%v: the DACL of %s grants %v, want %v: %s", existing, dir, sids, want, sd)
		}
	}
}

// The agent installs into its own folder under Program Files, never into "AdminHelper", the MSI
// folder of the desktop app.
func TestProgramDirIsTheAgentsOwnFolder(t *testing.T) {
	dir, err := programDir()
	if err != nil {
		t.Fatal(err)
	}
	pf, err := windows.KnownFolderPath(windows.FOLDERID_ProgramFiles, 0)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.EqualFold(filepath.Dir(dir), pf) || filepath.Base(dir) != "AdminHelper Agent" {
		t.Errorf("programDir = %q, want %q", dir, filepath.Join(pf, "AdminHelper Agent"))
	}
}

// The copied binary belongs to the Administrators group, not to the installing user: its owner
// could otherwise change the DACL of the file the service runs as LocalSystem.
func TestInstallBinaryHandsTheCopyToTheAdministrators(t *testing.T) {
	src := filepath.Join(t.TempDir(), "agent.exe")
	if err := os.WriteFile(src, []byte("binary"), 0o644); err != nil {
		t.Fatal(err)
	}
	dir := filepath.Join(t.TempDir(), "AdminHelper Agent")
	if err := prepareInstallDir(dir); err != nil {
		t.Fatal(err)
	}
	dest := filepath.Join(dir, "adminhelper-agent.exe")
	if err := installBinary(src, dest); err != nil {
		t.Fatal(err)
	}
	if data, err := os.ReadFile(dest); err != nil || string(data) != "binary" {
		t.Fatalf("copy = %q, %v", data, err)
	}
	sd, err := windows.GetNamedSecurityInfo(dest, windows.SE_FILE_OBJECT, windows.OWNER_SECURITY_INFORMATION)
	if err != nil {
		t.Fatal(err)
	}
	assertOwnedByAdministrators(t, sd, dest)
}

func assertOwnedByAdministrators(t *testing.T, sd *windows.SECURITY_DESCRIPTOR, path string) {
	t.Helper()
	owner, _, err := sd.Owner()
	if err != nil {
		t.Fatal(err)
	}
	if got := owner.String(); got != "S-1-5-32-544" {
		t.Fatalf("owner of %s = %s, want S-1-5-32-544", path, got)
	}
}
