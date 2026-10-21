// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package monitor

import (
	"os"
	"path/filepath"
	"testing"

	"golang.org/x/sys/windows"
)

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

// saveReportState hands the state file to the Administrators, also when the file it
// overwrites belongs to the test account: overwriting an existing file keeps its owner.
func TestSaveReportStateHandsTheFileToTheAdministrators(t *testing.T) {
	path := filepath.Join(t.TempDir(), ".report-state.json")
	if err := os.WriteFile(path, []byte("{}"), 0o600); err != nil {
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
	if got := ownerOf(t, path); got != user.User.Sid.String() {
		t.Fatalf("%s is owned by %s, want the test account %s", path, got, user.User.Sid)
	}

	want := cpuSample{Unix: 1_700_000_000, Total: 1234.5, Busy: 321.25}
	if err := saveReportState(path, reportState{CPU: &want}); err != nil {
		t.Fatalf("saveReportState: %v", err)
	}
	if got := ownerOf(t, path); got != "S-1-5-32-544" {
		t.Errorf("%s is owned by %s, want the Administrators S-1-5-32-544", path, got)
	}
	if got := loadReportState(path); got.CPU == nil || *got.CPU != want {
		t.Errorf("state after the save: got %+v, want %+v", got.CPU, want)
	}
}
