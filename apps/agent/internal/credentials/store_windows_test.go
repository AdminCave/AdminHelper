// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package credentials

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"golang.org/x/sys/windows"
)

// securityOf returns the owner (SID string) and the DACL of path.
func securityOf(t *testing.T, path string) (string, *windows.ACL) {
	t.Helper()
	sd, err := windows.GetNamedSecurityInfo(path, windows.SE_FILE_OBJECT,
		windows.OWNER_SECURITY_INFORMATION|windows.DACL_SECURITY_INFORMATION)
	if err != nil {
		t.Fatalf("read the security of %s: %v", path, err)
	}
	owner, _, err := sd.Owner()
	if err != nil {
		t.Fatal(err)
	}
	dacl, _, err := sd.DACL()
	if err != nil {
		t.Fatal(err)
	}
	return owner.String(), dacl
}

// setDACL gives path the DACL of the SDDL string sddl, protected.
func setDACL(t *testing.T, path, sddl string) {
	t.Helper()
	sd, err := windows.SecurityDescriptorFromString(sddl)
	if err != nil {
		t.Fatalf("parse %s: %v", sddl, err)
	}
	dacl, _, err := sd.DACL()
	if err != nil {
		t.Fatal(err)
	}
	if err := windows.SetNamedSecurityInfo(path, windows.SE_FILE_OBJECT,
		windows.DACL_SECURITY_INFORMATION|windows.PROTECTED_DACL_SECURITY_INFORMATION, nil, nil, dacl, nil); err != nil {
		t.Fatalf("set the DACL %s on %s: %v", sddl, path, err)
	}
}

func TestSetWritesAFileOfSystemAndTheAdministratorsAlone(t *testing.T) {
	path := storePath(t)
	if err := Set(context.Background(), path, "db", "secret"); err != nil {
		t.Fatal(err)
	}
	owner, dacl := securityOf(t, path)
	if owner != administratorsSID {
		t.Errorf("%s is owned by %s, want the Administrators", path, owner)
	}
	if !daclPrivate(dacl) {
		t.Errorf("the DACL of %s lets others in", path)
	}
	if creds, err := Load(path); err != nil || creds["db"].Secret != "secret" {
		t.Fatalf("Load = %v, %v", Refs(creds), err)
	}
}

func TestLoadUsesNoFileOthersCanRead(t *testing.T) {
	path := storePath(t)
	if err := Set(context.Background(), path, "db", "secret"); err != nil {
		t.Fatal(err)
	}
	setDACL(t, path, "D:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FR;;;BU)")
	if creds, err := Load(path); err == nil || !strings.Contains(err.Error(), "open to other accounts") {
		t.Fatalf("Load = %v, %v; want an error that the file is open", Refs(creds), err)
	}
}

func TestLoadUsesNoFileOfAnotherOwner(t *testing.T) {
	path := storePath(t)
	if err := Set(context.Background(), path, "db", "secret"); err != nil {
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
	if creds, err := Load(path); err == nil || !strings.Contains(err.Error(), "not by SYSTEM or the Administrators") {
		t.Fatalf("Load = %v, %v; want an error that names the owner", Refs(creds), err)
	}
}

func TestLoadFollowsNoLink(t *testing.T) {
	target := storePath(t)
	if err := Set(context.Background(), target, "db", "secret"); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(filepath.Dir(target), "link.json")
	if err := os.Symlink(target, link); err != nil {
		t.Fatal(err)
	}
	if creds, err := Load(link); err == nil {
		t.Fatalf("Load through a link = %v; want an error", Refs(creds))
	}
}

func TestDaclPrivate(t *testing.T) {
	const own = "(A;;FA;;;SY)(A;;FA;;;BA)"
	cases := []struct {
		name, sddl string
		want       bool
	}{
		{"SYSTEM and the Administrators", "D:P" + own, true},
		{"inherited from the data directory", "D:AI(A;ID;FA;;;SY)(A;ID;FA;;;BA)", true},
		{"Users are denied", "D:P(D;;FA;;;BU)" + own, true},
		{"Users may read", "D:P" + own + "(A;;FR;;;BU)", false},
		{"Everyone may read attributes", "D:P" + own + "(A;;0x80;;;WD)", false},
		{"null DACL", "D:NO_ACCESS_CONTROL", false},
		{"object ACE", "D:P" + own + "(OA;;FR;6f2e1d3c-0b4a-4c5d-8e9f-0a1b2c3d4e5f;;BU)", false},
		{"callback ACE", "D:P" + own + "(XA;;FR;;;BU;(Member_of {SID(BA)}))", false},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			sd, err := windows.SecurityDescriptorFromString(c.sddl)
			if err != nil {
				t.Fatalf("parse %s: %v", c.sddl, err)
			}
			dacl, _, err := sd.DACL()
			if err != nil {
				t.Fatalf("the DACL of %s: %v", c.sddl, err)
			}
			if got := daclPrivate(dacl); got != c.want {
				t.Fatalf("daclPrivate(%s) = %v, want %v", c.sddl, got, c.want)
			}
		})
	}
}
