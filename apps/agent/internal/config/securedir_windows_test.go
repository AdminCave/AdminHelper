// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package config

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"
	"testing"
	"unsafe"

	"golang.org/x/sys/windows"
)

// foreignSID is a local user: neither SYSTEM nor the Administrators.
const foreignSID = "S-1-5-21-1111111111-2222222222-3333333333-1001"

// openDACL is a protected DACL that, besides SYSTEM and the Administrators, lets the
// Users write: a kept directory with it is "open", not "closed".
const openDACL = "D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;BU)"

// readDescriptor returns the owner and the DACL of path.
func readDescriptor(t *testing.T, path string) *windows.SECURITY_DESCRIPTOR {
	t.Helper()
	sd, err := windows.GetNamedSecurityInfo(path, windows.SE_FILE_OBJECT,
		windows.OWNER_SECURITY_INFORMATION|windows.DACL_SECURITY_INFORMATION)
	if err != nil {
		t.Fatalf("read the security descriptor of %s: %v", path, err)
	}
	return sd
}

// daclSIDs returns the SIDs the DACL of sd grants, sorted. It fails unless every ACE
// allows and is inherited exactly if inherited is true.
func daclSIDs(t *testing.T, path string, sd *windows.SECURITY_DESCRIPTOR, inherited bool) []string {
	t.Helper()
	dacl, _, err := sd.DACL()
	if err != nil {
		t.Fatal(err)
	}
	var sids []string
	for i := range uint32(dacl.AceCount) {
		var ace *windows.ACCESS_ALLOWED_ACE
		if err := windows.GetAce(dacl, i, &ace); err != nil {
			t.Fatal(err)
		}
		if ace.Header.AceType != windows.ACCESS_ALLOWED_ACE_TYPE || (ace.Header.AceFlags&windows.INHERITED_ACE != 0) != inherited {
			t.Fatalf("the DACL of %s holds a non-allow ACE or one with the wrong inherited flag (want %v): %s", path, inherited, sd)
		}
		sids = append(sids, (*windows.SID)(unsafe.Pointer(&ace.SidStart)).String())
	}
	slices.Sort(sids)
	return sids
}

// requireProtected fails unless the Administrators own path and its DACL is protected
// and holds one ACE each for SYSTEM and the Administrators, neither inherited.
func requireProtected(t *testing.T, path string) {
	t.Helper()
	sd := readDescriptor(t, path)
	owner, _, err := sd.Owner()
	if err != nil {
		t.Fatal(err)
	}
	if got := owner.String(); got != administratorsSID {
		t.Fatalf("%s is owned by %s, want the Administrators: %s", path, got, sd)
	}
	control, _, err := sd.Control()
	if err != nil {
		t.Fatal(err)
	}
	if control&windows.SE_DACL_PROTECTED == 0 {
		t.Fatalf("the DACL of %s is not protected: %s", path, sd)
	}
	if got, want := daclSIDs(t, path, sd, false), []string{systemSID, administratorsSID}; !slices.Equal(got, want) {
		t.Fatalf("the DACL of %s grants %v, want %v: %s", path, got, want, sd)
	}
}

// requireInheritedOnly fails unless the DACL of path is not protected and holds only
// inherited ACEs, one each for SYSTEM and the Administrators.
func requireInheritedOnly(t *testing.T, path string) {
	t.Helper()
	sd := readDescriptor(t, path)
	control, _, err := sd.Control()
	if err != nil {
		t.Fatal(err)
	}
	if control&windows.SE_DACL_PROTECTED != 0 {
		t.Fatalf("the DACL of %s is still protected: %s", path, sd)
	}
	if got, want := daclSIDs(t, path, sd, true), []string{systemSID, administratorsSID}; !slices.Equal(got, want) {
		t.Fatalf("the DACL of %s grants %v, want %v: %s", path, got, want, sd)
	}
}

// requireUnchanged fails unless the file path still has the descriptor wantSD, as a
// string, and the content content.
func requireUnchanged(t *testing.T, path, wantSD, content string) {
	t.Helper()
	if got := readDescriptor(t, path).String(); got != wantSD {
		t.Fatalf("the descriptor of %s changed: %s, was %s", path, got, wantSD)
	}
	if got, err := os.ReadFile(path); err != nil || string(got) != content {
		t.Fatalf("the content of %s: %q, %v; want %q", path, got, err, content)
	}
}

// setOwner makes owner the owner of path, independently of OwnByAdministrators.
func setOwner(t *testing.T, path string, owner *windows.SID) {
	t.Helper()
	if err := windows.SetNamedSecurityInfo(path, windows.SE_FILE_OBJECT, windows.OWNER_SECURITY_INFORMATION,
		owner, nil, nil, nil); err != nil {
		t.Fatalf("make %s the owner of %s: %v", owner, path, err)
	}
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

// administrators returns the SID of the built-in Administrators group.
func administrators(t *testing.T) *windows.SID {
	t.Helper()
	sid, err := windows.CreateWellKnownSid(windows.WinBuiltinAdministratorsSid)
	if err != nil {
		t.Fatal(err)
	}
	return sid
}

// currentUser returns the SID of the account the test runs as.
func currentUser(t *testing.T) *windows.SID {
	t.Helper()
	u, err := windows.GetCurrentProcessToken().GetTokenUser()
	if err != nil {
		t.Fatal(err)
	}
	return u.User.Sid
}

// requireOwner fails unless the SID want owns path.
func requireOwner(t *testing.T, path, want string) {
	t.Helper()
	owner, _, err := readDescriptor(t, path).Owner()
	if err != nil {
		t.Fatal(err)
	}
	if got := owner.String(); got != want {
		t.Fatalf("%s is owned by %s, want %s", path, got, want)
	}
}

// junction creates a directory junction at link that points to target.
func junction(t *testing.T, link, target string) {
	t.Helper()
	if out, err := exec.Command("cmd", "/c", "mklink", "/J", link, target).CombinedOutput(); err != nil {
		t.Fatalf("mklink /J %s %s: %v: %s", link, target, err, out)
	}
}

// writeFile writes content to path, creating its parents.
func writeFile(t *testing.T, path, content string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
}

// readOnly sets the read-only attribute on path.
func readOnly(t *testing.T, path string) {
	t.Helper()
	if err := os.Chmod(path, 0o444); err != nil {
		t.Fatal(err)
	}
}

// outsideTarget creates base\target holding the file outside.txt and returns the
// target, the file and the file's descriptor as a string.
func outsideTarget(t *testing.T, base string) (target, file, sd string) {
	t.Helper()
	target = filepath.Join(base, "target")
	file = filepath.Join(target, "outside.txt")
	writeFile(t, file, "outside")
	return target, file, readDescriptor(t, file).String()
}

// holdOpen opens path for reading without FILE_SHARE_DELETE, so that a removal attempt
// hits a sharing violation, until the returned func is called or the test ends.
func holdOpen(t *testing.T, path string) (release func()) {
	t.Helper()
	name, err := windows.UTF16PtrFromString(path)
	if err != nil {
		t.Fatal(err)
	}
	h, err := windows.CreateFile(name, windows.GENERIC_READ, windows.FILE_SHARE_READ, nil, windows.OPEN_EXISTING,
		windows.FILE_ATTRIBUTE_NORMAL, 0)
	if err != nil {
		t.Fatalf("open %s: %v", path, err)
	}
	return keepHandle(t, h)
}

// pendDelete marks path for deletion with the plain disposition, through a handle it
// keeps open: the name stays until that handle is closed, and every other open of it
// fails with STATUS_DELETE_PENDING. The handle is closed, and the name goes, when the
// returned func is called or the test ends.
func pendDelete(t *testing.T, path string) (release func()) {
	t.Helper()
	name, err := windows.UTF16PtrFromString(path)
	if err != nil {
		t.Fatal(err)
	}
	h, err := windows.CreateFile(name, windows.DELETE,
		windows.FILE_SHARE_READ|windows.FILE_SHARE_WRITE|windows.FILE_SHARE_DELETE, nil, windows.OPEN_EXISTING,
		windows.FILE_ATTRIBUTE_NORMAL, 0)
	if err != nil {
		t.Fatalf("open %s: %v", path, err)
	}
	release = keepHandle(t, h)
	deleteFile := uint8(1)
	if err := windows.NtSetInformationFile(h, &windows.IO_STATUS_BLOCK{}, &deleteFile,
		uint32(unsafe.Sizeof(deleteFile)), windows.FileDispositionInformation); err != nil {
		t.Fatalf("mark %s for deletion: %v", path, err)
	}
	return release
}

// keepHandle closes h when the returned func is first called or the test ends.
func keepHandle(t *testing.T, h windows.Handle) (release func()) {
	t.Helper()
	closed := false
	release = func() {
		if !closed {
			closed = true
			windows.CloseHandle(h)
		}
	}
	t.Cleanup(release)
	return release
}

// keptClosedDir creates a data directory with the protected descriptor (SYSTEM and
// the Administrators only): closed.
func keptClosedDir(t *testing.T, base, name string) string {
	t.Helper()
	dir := filepath.Join(base, name)
	if err := EnsureSecureDir(dir); err != nil {
		t.Fatalf("create %s: %v", dir, err)
	}
	return dir
}

// keptOpenDir creates a data directory the Administrators own whose DACL also lets
// the Users write: open, not closed.
func keptOpenDir(t *testing.T, base, name string) string {
	t.Helper()
	dir := keptClosedDir(t, base, name)
	setOwner(t, dir, administrators(t))
	setDACL(t, dir, openDACL)
	return dir
}

// requireRealDir fails unless path is a directory and not a reparse point.
func requireRealDir(t *testing.T, path string) {
	t.Helper()
	info, err := os.Lstat(path)
	if err != nil {
		t.Fatal(err)
	}
	if !info.IsDir() || info.Mode()&(os.ModeSymlink|os.ModeIrregular) != 0 {
		t.Fatalf("%s is not a plain directory: mode %v", path, info.Mode())
	}
}

// requireEmpty fails unless the directory path has no entries.
func requireEmpty(t *testing.T, path string) {
	t.Helper()
	entries, err := os.ReadDir(path)
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 0 {
		t.Fatalf("%s still holds %d entries", path, len(entries))
	}
}

// requireExists fails unless path exists.
func requireExists(t *testing.T, path string) {
	t.Helper()
	if _, err := os.Lstat(path); err != nil {
		t.Fatalf("%s is gone: %v", path, err)
	}
}

// requireGone fails unless path is gone.
func requireGone(t *testing.T, path string) {
	t.Helper()
	if _, err := os.Lstat(path); !os.IsNotExist(err) {
		t.Fatalf("%s is still there (Lstat: %v)", path, err)
	}
}

// ownerByName answers the owner lookup by the last element of the path: names that
// start with "foreign" belong to foreignSID, all others to the Administrators.
func ownerByName(_ windows.Handle, path string) (string, error) {
	if strings.HasPrefix(filepath.Base(path), "foreign") {
		return foreignSID, nil
	}
	return administratorsSID, nil
}

// stopAt runs ensureSecureDir on dir with an owner lookup that answers like
// ownerByName but cuts the run short, by a panic, when it is asked about the entry
// stop, as if the agent had ended there. It fails unless the run got that far.
func stopAt(t *testing.T, dir, stop string) {
	t.Helper()
	type stopped struct{}
	var err error
	reached := func() (reached bool) {
		defer func() {
			if r := recover(); r != nil {
				if _, ok := r.(stopped); !ok {
					panic(r)
				}
				reached = true
			}
		}()
		err = ensureSecureDir(dir, func(h windows.Handle, path string) (string, error) {
			if path == stop {
				panic(stopped{})
			}
			return ownerByName(h, path)
		})
		return false
	}()
	if !reached {
		t.Fatalf("the run on %s ended without reaching %s: %v", dir, stop, err)
	}
}

// vanishAt returns an owner lookup that answers like ownerByName but, when it is asked
// about the entry gone, removes it first: the agent has just opened gone to classify
// it, and the step that follows finds it no longer there.
func vanishAt(t *testing.T, gone string) ownerLookup {
	t.Helper()
	return func(h windows.Handle, path string) (string, error) {
		if path == gone {
			if err := os.Remove(path); err != nil {
				t.Errorf("remove %s: %v", path, err)
			}
		}
		return ownerByName(h, path)
	}
}

// EnsureSecureDir creates a missing dir, and its missing parent, with the protected
// descriptor: nothing is inherited from the temp dir above.
func TestEnsureSecureDirCreatesProtectedDir(t *testing.T) {
	parent := filepath.Join(t.TempDir(), "parent")
	dir := filepath.Join(parent, "secret")
	if err := EnsureSecureDir(dir); err != nil {
		t.Fatalf("EnsureSecureDir: %v", err)
	}
	requireRealDir(t, dir)
	requireProtected(t, dir)
	requireProtected(t, parent)
}

// A data dir the Administrators own, with its inherited ACL, stays with its file and
// gets the protected DACL; the file then inherits from it. The owner comes from the
// real lookup.
func TestEnsureSecureDirKeepsAnAdministratorsDir(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "secret")
	kept := filepath.Join(dir, "agent.conf")
	writeFile(t, kept, "kept")
	setOwner(t, dir, administrators(t))
	setOwner(t, kept, administrators(t))

	if err := EnsureSecureDir(dir); err != nil {
		t.Fatalf("EnsureSecureDir: %v", err)
	}
	requireProtected(t, dir)
	requireInheritedOnly(t, kept)
	if got, err := os.ReadFile(kept); err != nil || string(got) != "kept" {
		t.Fatalf("the file in the kept dir: %q, %v", got, err)
	}
}

// A dir with another owner is removed with what it holds and created anew.
func TestEnsureSecureDirRecreatesAForeignDir(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "foreign")
	writeFile(t, filepath.Join(dir, "sub", "agent.conf"), "old")

	if err := ensureSecureDir(dir, ownerByName); err != nil {
		t.Fatalf("ensureSecureDir: %v", err)
	}
	requireRealDir(t, dir)
	requireProtected(t, dir)
	requireEmpty(t, dir)
}

// A foreign dir is removed and created anew even when its DACL grants SYSTEM and the
// Administrators no right to delete its entries and a child lets no one in.
func TestEnsureSecureDirRecreatesADirThatDeniesDelete(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "foreign")
	child := filepath.Join(dir, "sub")
	writeFile(t, child, "old")
	setDACL(t, child, "D:P")
	// Read and execute for SYSTEM and the Administrators, nothing else: no
	// FILE_DELETE_CHILD, so a child is only deletable after the dir is taken over.
	setDACL(t, dir, "D:P(A;;0x1200a9;;;SY)(A;;0x1200a9;;;BA)")

	if err := ensureSecureDir(dir, ownerByName); err != nil {
		t.Fatalf("ensureSecureDir: %v", err)
	}
	requireRealDir(t, dir)
	requireProtected(t, dir)
	requireEmpty(t, dir)
}

// A foreign dir whose DACL strips the owner's implicit rights through an Owner-Rights
// ACE and grants SYSTEM and the Administrators nothing is still removed and created
// anew.
func TestEnsureSecureDirRecreatesADirWithOwnerRightsACE(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "foreign")
	if err := os.Mkdir(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	// S-1-3-4 is Owner Rights: it fixes the owner's rights at read only, so even after
	// take-over the Administrators have no WRITE_DAC from being the owner.
	setDACL(t, dir, "D:P(A;;FR;;;OW)")

	if err := ensureSecureDir(dir, ownerByName); err != nil {
		t.Fatalf("ensureSecureDir: %v", err)
	}
	requireRealDir(t, dir)
	requireProtected(t, dir)
}

// A junction at the path is replaced by a new dir; the descriptor and the content of
// its target stay as they were. The owner comes from the real lookup.
func TestEnsureSecureDirReplacesAJunction(t *testing.T) {
	base := t.TempDir()
	target, outside, outsideSD := outsideTarget(t, base)
	targetSD := readDescriptor(t, target).String()
	dir := filepath.Join(base, "secret")
	junction(t, dir, target)

	if err := EnsureSecureDir(dir); err != nil {
		t.Fatalf("EnsureSecureDir: %v", err)
	}
	requireRealDir(t, dir)
	requireProtected(t, dir)
	requireEmpty(t, dir)
	if got := readDescriptor(t, target).String(); got != targetSD {
		t.Fatalf("the descriptor of the junction target changed: %s, was %s", got, targetSD)
	}
	requireUnchanged(t, outside, outsideSD, "outside")
}

// In an open dir it keeps, EnsureSecureDir removes the direct entries with another
// owner and the reparse points; behind a junction nothing changes.
func TestEnsureSecureDirRemovesForeignChildren(t *testing.T) {
	base := t.TempDir()
	dir := keptOpenDir(t, base, "secret")
	trusted := filepath.Join(dir, "agent.conf")
	foreignFile := filepath.Join(dir, "foreign.conf")
	foreignDir := filepath.Join(dir, "foreign-dir")
	writeFile(t, trusted, "x")
	writeFile(t, foreignFile, "x")
	writeFile(t, filepath.Join(foreignDir, "nested.conf"), "x")
	setDACL(t, foreignFile, "D:P")
	setDACL(t, foreignDir, "D:P")
	target, outside, outsideSD := outsideTarget(t, base)
	link := filepath.Join(dir, "link")
	junction(t, link, target)

	if err := ensureSecureDir(dir, ownerByName); err != nil {
		t.Fatalf("ensureSecureDir: %v", err)
	}
	requireProtected(t, dir)
	requireExists(t, trusted)
	requireGone(t, foreignFile)
	requireGone(t, foreignDir)
	requireGone(t, link)
	requireUnchanged(t, outside, outsideSD, "outside")
}

// A read-only file that another account owns, whose DACL keeps the agent out, is
// removed, both when its dir is recreated and when its dir is kept.
func TestEnsureSecureDirRemovesReadOnlyForeignFiles(t *testing.T) {
	base := t.TempDir()

	gone := filepath.Join(base, "foreign")
	goneFile := filepath.Join(gone, "foreign.conf")
	writeFile(t, goneFile, "x")
	readOnly(t, goneFile)
	setDACL(t, goneFile, "D:P")

	kept := keptOpenDir(t, base, "secret")
	keptFile := filepath.Join(kept, "foreign.conf")
	writeFile(t, keptFile, "x")
	readOnly(t, keptFile)
	setDACL(t, keptFile, "D:P")

	for _, dir := range []string{gone, kept} {
		if err := ensureSecureDir(dir, ownerByName); err != nil {
			t.Fatalf("ensureSecureDir %s: %v", dir, err)
		}
	}
	requireRealDir(t, gone)
	requireEmpty(t, gone)
	requireProtected(t, kept)
	requireGone(t, keptFile)
}

// In a closed dir, a child that another account owns is kept with its content and
// handed to the Administrators, its extra access entry gone; in an open dir it is
// removed. The kept child starts with another owner and an extra entry, so both
// checks on it can fail.
func TestEnsureSecureDirKeepsForeignChildInAClosedDir(t *testing.T) {
	base := t.TempDir()
	user := currentUser(t)

	closed := keptClosedDir(t, base, "closed")
	keptChild := filepath.Join(closed, "foreign.conf")
	writeFile(t, keptChild, "secret")
	setOwner(t, keptChild, user)
	setDACL(t, keptChild, fmt.Sprintf("D:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FA;;;%s)", user))

	open := keptOpenDir(t, base, "open")
	goneChild := filepath.Join(open, "foreign.conf")
	writeFile(t, goneChild, "x")
	setDACL(t, goneChild, "D:P")

	for _, dir := range []string{closed, open} {
		if err := ensureSecureDir(dir, ownerByName); err != nil {
			t.Fatalf("ensureSecureDir %s: %v", dir, err)
		}
	}
	requireExists(t, keptChild)
	requireOwner(t, keptChild, administratorsSID)
	requireInheritedOnly(t, keptChild)
	if got, err := os.ReadFile(keptChild); err != nil || string(got) != "secret" {
		t.Fatalf("the kept child: %q, %v", got, err)
	}
	requireGone(t, goneChild)
}

// A foreign subdir in a closed dir is kept (taken over) but, because its former owner
// set its DACL, cleaned as an open dir: its foreign file goes even though its own DACL
// looks closed.
func TestEnsureSecureDirCleansATakenOverForeignSubdir(t *testing.T) {
	base := t.TempDir()
	dir := keptClosedDir(t, base, "secret")
	sub := filepath.Join(dir, "foreign-sub")
	foreign := filepath.Join(sub, "foreign.conf")
	writeFile(t, foreign, "x")
	setOwner(t, sub, currentUser(t))
	setDACL(t, sub, "D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)")

	if err := ensureSecureDir(dir, ownerByName); err != nil {
		t.Fatalf("ensureSecureDir: %v", err)
	}
	requireExists(t, sub)
	requireOwner(t, sub, administratorsSID)
	requireGone(t, foreign)
}

// A kept subdirectory, with its file, ends with the inherited DACL only; a junction
// inside it is removed without touching the descriptor or the content of its target.
func TestEnsureSecureDirCleansAKeptSubdir(t *testing.T) {
	base := t.TempDir()
	dir := keptClosedDir(t, base, "secret")
	sub := filepath.Join(dir, "sub")
	file := filepath.Join(sub, "agent.conf")
	writeFile(t, file, "kept")
	target, outside, outsideSD := outsideTarget(t, base)
	link := filepath.Join(sub, "link")
	junction(t, link, target)

	if err := EnsureSecureDir(dir); err != nil {
		t.Fatalf("EnsureSecureDir: %v", err)
	}
	requireProtected(t, dir)
	requireInheritedOnly(t, sub)
	requireInheritedOnly(t, file)
	if got, err := os.ReadFile(file); err != nil || string(got) != "kept" {
		t.Fatalf("the file in the kept subdir: %q, %v", got, err)
	}
	requireGone(t, link)
	requireUnchanged(t, outside, outsideSD, "outside")
}

// A subdirectory the Administrators own with an empty DACL, which keeps everyone out,
// is repaired to the inherited DACL, not removed.
func TestEnsureSecureDirRepairsASubdirWithEmptyDACL(t *testing.T) {
	dir := keptClosedDir(t, t.TempDir(), "secret")
	sub := filepath.Join(dir, "sub")
	if err := os.Mkdir(sub, 0o700); err != nil {
		t.Fatal(err)
	}
	setOwner(t, sub, administrators(t))
	setDACL(t, sub, "D:P")

	if err := EnsureSecureDir(dir); err != nil {
		t.Fatalf("EnsureSecureDir: %v", err)
	}
	requireExists(t, sub)
	requireRealDir(t, sub)
	requireInheritedOnly(t, sub)
}

// A file in a kept dir that has a second name outside it is removed there; the other
// name keeps its descriptor and its content.
func TestEnsureSecureDirRemovesAFileWithASecondName(t *testing.T) {
	base := t.TempDir()
	dir := keptClosedDir(t, base, "secret")
	outside := filepath.Join(base, "outside.conf")
	writeFile(t, outside, "outside")
	outsideSD := readDescriptor(t, outside).String()
	inside := filepath.Join(dir, "agent.conf")
	if err := os.Link(outside, inside); err != nil {
		t.Fatal(err)
	}

	if err := ensureSecureDir(dir, ownerByName); err != nil {
		t.Fatalf("ensureSecureDir: %v", err)
	}
	requireGone(t, inside)
	requireUnchanged(t, outside, outsideSD, "outside")
}

// An entry the Administrators own, with an extra ACE for the Users, keeps its content
// and afterwards has only the DACL it inherits.
func TestEnsureSecureDirResetsTheACLOfAKeptChild(t *testing.T) {
	dir := keptClosedDir(t, t.TempDir(), "secret")
	child := filepath.Join(dir, "agent.conf")
	writeFile(t, child, "kept")
	setOwner(t, child, administrators(t))
	setDACL(t, child, "D:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FR;;;BU)")

	if err := EnsureSecureDir(dir); err != nil {
		t.Fatalf("EnsureSecureDir: %v", err)
	}
	requireInheritedOnly(t, child)
	if got, err := os.ReadFile(child); err != nil || string(got) != "kept" {
		t.Fatalf("the kept child: %q, %v", got, err)
	}
}

// A foreign entry of an open dir that is held open without FILE_SHARE_DELETE cannot
// be removed: EnsureSecureDir returns an error and the entry stays.
func TestEnsureSecureDirFailsWhenAForeignChildIsHeldOpen(t *testing.T) {
	dir := keptOpenDir(t, t.TempDir(), "secret")
	held := filepath.Join(dir, "foreign.conf")
	writeFile(t, held, "x")
	holdOpen(t, held)

	if err := ensureSecureDir(dir, ownerByName); err == nil {
		t.Fatal("ensureSecureDir returned no error for a foreign child it could not remove")
	}
	requireExists(t, held)
}

// A dir that is gone when it is checked is handed back for creation anew, never
// reported as secured; creating it anew yields the protected dir, and a dir that is
// back by then is an error.
func TestSecureExistingRecreatesAVanishedDir(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "secret")
	d, err := newDescriptors()
	if err != nil {
		t.Fatal(err)
	}
	var recreate bool
	err = withPrivileges(func() error {
		var err error
		recreate, err = secureExisting(dir, d, ownerByName)
		return err
	})
	if err != nil || !recreate {
		t.Fatalf("secureExisting on a missing dir: recreate %v, error %v; want true, nil", recreate, err)
	}
	if err := createSecureDir(dir, d.protected); err != nil {
		t.Fatalf("create anew: %v", err)
	}
	requireProtected(t, dir)
	if err := createSecureDir(dir, d.protected); !errors.Is(err, windows.ERROR_ALREADY_EXISTS) {
		t.Fatalf("create anew over a dir that is back: %v, want ERROR_ALREADY_EXISTS", err)
	}
}

// A removal that stops at a foreign child held open fails, and leaves the dir owned
// by the Administrators but without the inheritable entries of a closed dir: the next
// run treats it as open and removes the foreign child instead of keeping it. Owners
// come from the real lookup.
func TestEnsureSecureDirFinishesAStoppedRemoval(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "secret")
	child := filepath.Join(dir, "agent.conf")
	writeFile(t, child, "x")
	user := currentUser(t)
	setOwner(t, child, user)
	setOwner(t, dir, user)
	release := holdOpen(t, child)

	if err := EnsureSecureDir(dir); err == nil {
		t.Fatal("first run: no error for a foreign child held open")
	}
	release()
	if err := EnsureSecureDir(dir); err != nil {
		t.Fatalf("second run: %v", err)
	}
	requireProtected(t, dir)
	requireGone(t, child)
}

// A run that stops at an entry leaves the entries it already cleaned usable: a-sub,
// listed before the foreign file held open, still grants SYSTEM and the
// Administrators afterwards, in the inherited form, although the final propagation
// never ran.
func TestEnsureSecureDirLeavesCleanedEntriesUsableWhenItStops(t *testing.T) {
	dir := keptOpenDir(t, t.TempDir(), "secret")
	sub := filepath.Join(dir, "a-sub")
	if err := os.Mkdir(sub, 0o700); err != nil {
		t.Fatal(err)
	}
	setOwner(t, sub, administrators(t))
	held := filepath.Join(dir, "foreign.conf")
	writeFile(t, held, "x")
	holdOpen(t, held)

	if err := ensureSecureDir(dir, ownerByName); err == nil {
		t.Fatal("ensureSecureDir returned no error for a foreign child it could not remove")
	}
	requireInheritedOnly(t, sub)
}

// A run that stops at a foreign entry it cannot remove leaves the open dir it was
// cleaning open, a kept root as well as a kept subdir of a closed root: the next run,
// with the entry no longer held, removes it instead of taking it over.
func TestEnsureSecureDirLeavesAnOpenDirOpenWhenItStops(t *testing.T) {
	cases := []struct {
		name string
		dirs func(t *testing.T, base string) (root, open string)
	}{
		{"root", func(t *testing.T, base string) (string, string) {
			root := keptOpenDir(t, base, "secret")
			return root, root
		}},
		{"subdir", func(t *testing.T, base string) (string, string) {
			root := keptClosedDir(t, base, "secret")
			return root, keptOpenDir(t, root, "sub")
		}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			root, open := c.dirs(t, t.TempDir())
			held := filepath.Join(open, "foreign.conf")
			writeFile(t, held, "x")
			release := holdOpen(t, held)

			if err := ensureSecureDir(root, ownerByName); err == nil {
				t.Fatal("first run: no error for a foreign child held open")
			}
			release()
			if err := ensureSecureDir(root, ownerByName); err != nil {
				t.Fatalf("second run: %v", err)
			}
			requireGone(t, held)
			requireProtected(t, root)
		})
	}
}

// A run cut short after it locked a closed dir leaves it closed: the next run takes a
// child that another account owns (provisioned before) over and keeps it. The run
// stops at a sibling listed before the child, so the child is still foreign then.
func TestEnsureSecureDirLeavesAClosedDirClosedWhenItStops(t *testing.T) {
	dir := keptClosedDir(t, t.TempDir(), "secret")
	child := filepath.Join(dir, "foreign.conf")
	writeFile(t, child, "provisioned")
	setOwner(t, child, currentUser(t))
	stop := filepath.Join(dir, "a-stop.conf")
	writeFile(t, stop, "x")

	stopAt(t, dir, stop)
	requireOwner(t, child, currentUser(t).String())
	if err := ensureSecureDir(dir, ownerByName); err != nil {
		t.Fatalf("second run: %v", err)
	}
	requireOwner(t, child, administratorsSID)
	requireInheritedOnly(t, child)
	if got, err := os.ReadFile(child); err != nil || string(got) != "provisioned" {
		t.Fatalf("the kept child: %q, %v", got, err)
	}
}

// A child that is gone when the step after its classification reaches it, as a temp
// file renamed meanwhile, counts as removed: the run goes on, cleans the sibling listed
// after it and succeeds. The child is a file or a directory, one the agent would keep
// (closed dir) or remove (open dir).
func TestEnsureSecureDirSkipsAChildThatVanishes(t *testing.T) {
	cases := []struct {
		name  string
		open  bool
		child string
		isDir bool
	}{
		{"kept file", false, "a.conf", false},
		{"kept dir", false, "a-sub", true},
		{"removed file", true, "foreign.conf", false},
		{"removed dir", true, "foreign-dir", true},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			mkdir := keptClosedDir
			if c.open {
				mkdir = keptOpenDir
			}
			dir := mkdir(t, t.TempDir(), "secret")
			child := filepath.Join(dir, c.child)
			if c.isDir {
				if err := os.Mkdir(child, 0o700); err != nil {
					t.Fatal(err)
				}
			} else {
				writeFile(t, child, "x")
			}
			later := filepath.Join(dir, "z.conf")
			writeFile(t, later, "kept")
			setOwner(t, later, administrators(t))
			setDACL(t, later, "D:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FR;;;BU)")

			if err := ensureSecureDir(dir, vanishAt(t, child)); err != nil {
				t.Fatalf("ensureSecureDir: %v", err)
			}
			requireGone(t, child)
			requireProtected(t, dir)
			requireInheritedOnly(t, later)
		})
	}
}

// A child marked for deletion while another handle keeps it, which refuses every new
// open, does not count as removed: the run stops there with an error, before the
// sibling listed after it, which keeps its descriptor. With the handle closed the
// child is gone, and the next run succeeds.
func TestEnsureSecureDirFailsOnAChildWithAPendingDelete(t *testing.T) {
	dir := keptOpenDir(t, t.TempDir(), "secret")
	child := filepath.Join(dir, "frpc.toml.tmp")
	writeFile(t, child, "x")
	later := filepath.Join(dir, "z.conf")
	writeFile(t, later, "kept")
	setOwner(t, later, administrators(t))
	setDACL(t, later, "D:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FR;;;BU)")
	laterSD := readDescriptor(t, later).String()
	release := pendDelete(t, child)

	if err := ensureSecureDir(dir, ownerByName); err == nil {
		t.Fatal("first run: no error for a child with a pending delete")
	}
	requireUnchanged(t, later, laterSD, "kept")
	release()
	if err := ensureSecureDir(dir, ownerByName); err != nil {
		t.Fatalf("second run: %v", err)
	}
	requireGone(t, child)
	requireProtected(t, dir)
	requireInheritedOnly(t, later)
}

// An entry about to be deleted below a directory the agent removes fails the run, and
// the foreign directory stays; with the handle closed the next run removes it.
func TestEnsureSecureDirFailsToRemoveADirWithAPendingDelete(t *testing.T) {
	dir := keptOpenDir(t, t.TempDir(), "secret")
	foreignDir := filepath.Join(dir, "foreign-dir")
	pending := filepath.Join(foreignDir, "pending.conf")
	writeFile(t, pending, "x")
	release := pendDelete(t, pending)

	if err := ensureSecureDir(dir, ownerByName); err == nil {
		t.Fatal("first run: no error for a foreign dir that still holds an entry")
	}
	requireExists(t, foreignDir)
	release()
	if err := ensureSecureDir(dir, ownerByName); err != nil {
		t.Fatalf("second run: %v", err)
	}
	requireGone(t, foreignDir)
}

// OwnByAdministrators hands a file the agent wrote, here one the test account owns,
// to the Administrators.
func TestOwnByAdministratorsSetsTheOwner(t *testing.T) {
	path := filepath.Join(t.TempDir(), "agent.conf")
	writeFile(t, path, "x")
	user := currentUser(t)
	setOwner(t, path, user)
	requireOwner(t, path, user.String())

	if err := OwnByAdministrators(path); err != nil {
		t.Fatalf("OwnByAdministrators: %v", err)
	}
	requireOwner(t, path, administratorsSID)
}

// OwnByAdministrators refuses a junction and leaves the owner of its target alone.
func TestOwnByAdministratorsDoesNotFollowAJunction(t *testing.T) {
	base := t.TempDir()
	target := filepath.Join(base, "target")
	if err := os.Mkdir(target, 0o700); err != nil {
		t.Fatal(err)
	}
	user := currentUser(t)
	setOwner(t, target, user)
	link := filepath.Join(base, "link")
	junction(t, link, target)

	if err := OwnByAdministrators(link); err == nil {
		t.Fatal("OwnByAdministrators returned no error for a junction")
	}
	requireOwner(t, target, user.String())
}

// WriteFile hands the file it wrote to the Administrators, also an existing one the
// test account owns.
func TestWriteFileHandsTheFileToTheAdministrators(t *testing.T) {
	path := filepath.Join(t.TempDir(), "agent.conf")
	writeFile(t, path, "x")
	user := currentUser(t)
	setOwner(t, path, user)
	requireOwner(t, path, user.String())

	if err := WriteFile(path, []byte("y"), 0o600); err != nil {
		t.Fatalf("WriteFile: %v", err)
	}
	requireOwner(t, path, administratorsSID)
	if got, err := os.ReadFile(path); err != nil || string(got) != "y" {
		t.Fatalf("the content of %s: %q, %v", path, got, err)
	}
}

// EnsureDataDir and EnsureLogDir secure the data root before the directory below it:
// a junction at the root is replaced, and the directory of the same name behind it
// keeps its descriptor and its file. Securing only the directory would open the root
// by path, follow the junction and lock or remove the directory behind it.
func TestEnsureDataDirSecuresTheRootFirst(t *testing.T) {
	cases := []struct {
		name   string
		sub    string
		secure func(dir string) error
	}{
		{"EnsureDataDir", "frp", EnsureDataDir},
		{"EnsureLogDir", "logs", func(string) error { return EnsureLogDir() }},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			base := t.TempDir()
			target := filepath.Join(base, "target")
			behind := filepath.Join(target, c.sub)
			outside := filepath.Join(behind, "outside.txt")
			writeFile(t, outside, "outside")
			behindSD := readDescriptor(t, behind).String()
			outsideSD := readDescriptor(t, outside).String()
			root := filepath.Join(base, "root")
			junction(t, root, target)
			dir := filepath.Join(root, c.sub)
			t.Setenv("ADMINHELPER_MONITOR_DIR", root)
			t.Setenv("ADMINHELPER_LOG_DIR", dir)

			if err := c.secure(dir); err != nil {
				t.Fatalf("%s: %v", c.name, err)
			}
			requireRealDir(t, root)
			requireProtected(t, root)
			requireRealDir(t, dir)
			requireProtected(t, dir)
			if got := readDescriptor(t, behind).String(); got != behindSD {
				t.Fatalf("the descriptor of %s behind the junction changed: %s, was %s", behind, got, behindSD)
			}
			requireUnchanged(t, outside, outsideSD, "outside")
			if entries, err := os.ReadDir(behind); err != nil || len(entries) != 1 {
				t.Fatalf("%s behind the junction holds %d entries (%v), want only outside.txt", behind, len(entries), err)
			}
		})
	}
}
