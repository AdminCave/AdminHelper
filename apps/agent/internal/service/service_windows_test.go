// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package service

import (
	"crypto/sha256"
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
	"golang.org/x/sys/windows/svc"
	"golang.org/x/sys/windows/svc/eventlog"
	"golang.org/x/sys/windows/svc/mgr"

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

// A placed file belongs to the Administrators group, not to the installing user, also when it
// replaces one of another owner: its owner could otherwise change the DACL of the file the service
// runs as LocalSystem.
func TestPlaceFileHandsTheFileToTheAdministrators(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "AdminHelper Agent")
	if err := prepareInstallDir(dir); err != nil {
		t.Fatal(err)
	}
	dest := filepath.Join(dir, agentExeName)
	if err := os.WriteFile(dest, []byte("old"), 0o644); err != nil {
		t.Fatal(err)
	}
	for _, content := range []string{"binary", "binary"} {
		if err := placeFile(dest, []byte(content)); err != nil {
			t.Fatal(err)
		}
		if data, err := os.ReadFile(dest); err != nil || string(data) != content {
			t.Fatalf("copy = %q, %v", data, err)
		}
		assertOwnedByAdministrators(t, ownerOf(t, dest), dest)
	}
}

func ownerOf(t *testing.T, path string) *windows.SECURITY_DESCRIPTOR {
	t.Helper()
	sd, err := windows.GetNamedSecurityInfo(path, windows.SE_FILE_OBJECT, windows.OWNER_SECURITY_INFORMATION)
	if err != nil {
		t.Fatal(err)
	}
	return sd
}

// pinFakeFrpc makes content the frpc.exe the install accepts.
func pinFakeFrpc(t *testing.T, content []byte) {
	t.Helper()
	old := frpcWantSHA256
	frpcWantSHA256 = fmt.Sprintf("%x", sha256.Sum256(content))
	t.Cleanup(func() { frpcWantSHA256 = old })
}

// frpc.exe beside the installing binary is taken under either name only with the pinned hash; a
// missing one is reported, the one already in the program directory is kept.
func TestReadFrpcSource(t *testing.T) {
	pinFakeFrpc(t, []byte("frpc"))
	dir := t.TempDir()
	dest := filepath.Join(t.TempDir(), frpcExeName)

	if data, found, err := readFrpcSource(dir, dest); err != nil || found || data != nil {
		t.Errorf("empty folder: %q, %v, %v; want nothing found", data, found, err)
	}
	for _, name := range frpcSourceNames {
		path := filepath.Join(dir, name)
		if err := os.WriteFile(path, []byte("frpc"), 0o644); err != nil {
			t.Fatal(err)
		}
		if data, found, err := readFrpcSource(dir, dest); err != nil || !found || string(data) != "frpc" {
			t.Errorf("%s: %q, %v, %v; want it", name, data, found, err)
		}
		if err := os.WriteFile(path, []byte("other"), 0o644); err != nil {
			t.Fatal(err)
		}
		if _, _, err := readFrpcSource(dir, dest); err == nil {
			t.Errorf("%s with another hash was accepted", name)
		}
		if err := os.Remove(path); err != nil {
			t.Fatal(err)
		}
	}
	// Run from the program directory, frpc.exe is already in place.
	if err := os.WriteFile(dest, []byte("frpc"), 0o644); err != nil {
		t.Fatal(err)
	}
	if data, found, err := readFrpcSource(filepath.Dir(dest), dest); err != nil || !found || data != nil {
		t.Errorf("program directory: %q, %v, %v; want found, nothing to copy", data, found, err)
	}
}

// fakeAgent is the service the test binary runs when the service control manager starts a copy
// of it (TestMain): it runs until it is stopped.
type fakeAgent struct{}

func (fakeAgent) Execute(_ []string, r <-chan svc.ChangeRequest, s chan<- svc.Status) (bool, uint32) {
	s <- svc.Status{State: svc.Running, Accepts: svc.AcceptStop | svc.AcceptShutdown}
	for c := range r {
		switch c.Cmd {
		case svc.Interrogate:
			s <- c.CurrentStatus
		case svc.Stop, svc.Shutdown:
			s <- svc.Status{State: svc.StopPending}
			return false, 0
		}
	}
	return false, 0
}

func TestMain(m *testing.M) {
	if isService, err := svc.IsWindowsService(); err == nil && isService {
		if err := svc.Run("", fakeAgent{}); err != nil {
			os.Exit(1)
		}
		os.Exit(0)
	}
	os.Exit(m.Run())
}

// runningPID waits until the service runs and returns its process.
func runningPID(t *testing.T, name string) uint32 {
	t.Helper()
	m, err := mgr.Connect()
	if err != nil {
		t.Fatal(err)
	}
	defer m.Disconnect()
	s, err := m.OpenService(name)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	deadline := time.Now().Add(30 * time.Second)
	for {
		st, err := s.Query()
		if err != nil {
			t.Fatal(err)
		}
		if st.State == svc.Running && st.ProcessId != 0 {
			return st.ProcessId
		}
		if time.Now().After(deadline) {
			t.Fatalf("%s does not run: state %d", name, st.State)
		}
		time.Sleep(100 * time.Millisecond)
	}
}

// serviceConfig returns the configuration and recovery actions of the service.
func serviceConfig(t *testing.T, name string) (mgr.Config, []mgr.RecoveryAction) {
	t.Helper()
	m, err := mgr.Connect()
	if err != nil {
		t.Fatal(err)
	}
	defer m.Disconnect()
	s, err := m.OpenService(name)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	cfg, err := s.Config()
	if err != nil {
		t.Fatal(err)
	}
	actions, err := s.RecoveryActions()
	if err != nil {
		t.Fatal(err)
	}
	return cfg, actions
}

// Installed against the real service control manager three times: a first install registers
// and starts the service; a second one from a newer binary into another folder stops it, waits
// for its process, replaces the files, points the service there and removes the agent of the
// first folder, which stays; a third one with the same files restarts it unchanged.
func TestInstallUpdatesAndMovesTheRunningService(t *testing.T) {
	name := fmt.Sprintf("AdminHelper-Agent-Test-%d", os.Getpid())
	source := fmt.Sprintf("%s-Test-%d-%d", logging.EventSource, os.Getpid(), time.Now().UnixNano())
	self, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	agent, err := os.ReadFile(self)
	if err != nil {
		t.Fatal(err)
	}
	frpcExe := []byte("fake frpc")
	pinFakeFrpc(t, frpcExe)
	src := t.TempDir()
	installer := filepath.Join(src, agentExeName)
	writeTestFile(t, installer, agent)
	writeTestFile(t, filepath.Join(src, frpcSourceNames[0]), frpcExe)
	oldDir := filepath.Join(t.TempDir(), "AdminHelper")
	newDir := filepath.Join(t.TempDir(), "AdminHelper Agent")
	// Registered after the temporary folders, so that it runs before their removal.
	t.Cleanup(func() {
		if err := uninstall(name, source); err != nil {
			t.Errorf("uninstall: %v", err)
		}
	})
	target := func(dir string) installTarget {
		return installTarget{name: name, displayName: name, eventSource: source, dir: dir, self: installer}
	}

	if err := install(target(oldDir)); err != nil {
		t.Fatalf("first install: %v", err)
	}
	first := runningPID(t, name)

	// A newer agent: bytes after the image do not keep a PE binary from running.
	newer := append(slices.Clone(agent), []byte("newer")...)
	writeTestFile(t, installer, newer)
	if err := install(target(newDir)); err != nil {
		t.Fatalf("second install: %v", err)
	}
	second := runningPID(t, name)
	if second == first {
		t.Errorf("the service still runs process %d of the first install", first)
	}
	dest := filepath.Join(newDir, agentExeName)
	for path, want := range map[string][]byte{dest: newer, filepath.Join(newDir, frpcExeName): frpcExe} {
		if data, err := os.ReadFile(path); err != nil || !slices.Equal(data, want) {
			t.Errorf("%s holds %d bytes (%v), want %d", path, len(data), err, len(want))
		}
		assertOwnedByAdministrators(t, ownerOf(t, path), path)
	}
	if _, err := os.Stat(filepath.Join(oldDir, agentExeName)); !errors.Is(err, os.ErrNotExist) {
		t.Errorf("the agent of the first folder is still there: %v", err)
	}
	if _, err := os.Stat(oldDir); err != nil {
		t.Errorf("the first folder is gone: %v", err)
	}
	cfg, actions := serviceConfig(t, name)
	if want := `"` + dest + `" run`; cfg.BinaryPathName != want {
		t.Errorf("BinaryPathName = %s, want %s", cfg.BinaryPathName, want)
	}
	if cfg.StartType != mgr.StartAutomatic || !strings.EqualFold(cfg.ServiceStartName, "LocalSystem") {
		t.Errorf("start type %d as %s, want automatic as LocalSystem", cfg.StartType, cfg.ServiceStartName)
	}
	if len(actions) != 3 {
		t.Errorf("recovery actions = %v, want three restarts", actions)
	}
	for _, a := range actions {
		if a.Type != mgr.ServiceRestart || a.Delay != 60*time.Second {
			t.Errorf("recovery action %+v, want a restart after 60 s", a)
		}
	}

	if err := install(target(newDir)); err != nil {
		t.Fatalf("third install: %v", err)
	}
	if third := runningPID(t, name); third == second {
		t.Errorf("the third install did not restart the service")
	}
}

func writeTestFile(t *testing.T, path string, data []byte) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, data, 0o755); err != nil {
		t.Fatal(err)
	}
}

// Purge removes the program and data directories the agent set up; the running binary, which
// cannot delete itself, stays until the next restart. A folder of another owner stays, a missing
// one is no error.
func TestPurgeRemovesTheDirectoriesButTheRunningBinary(t *testing.T) {
	root := t.TempDir()
	prog := filepath.Join(root, "AdminHelper Agent")
	data := filepath.Join(root, "data")
	foreign := filepath.Join(root, "foreign")
	for _, dir := range []string{prog, data, foreign} {
		if err := prepareInstallDir(dir); err != nil {
			t.Fatal(err)
		}
	}
	self := filepath.Join(prog, agentExeName)
	for _, path := range []string{self, filepath.Join(prog, frpcExeName), filepath.Join(foreign, "keep"),
		filepath.Join(data, "frp", "frpc.toml"), filepath.Join(data, "logs", "agent.log")} {
		writeTestFile(t, path, []byte("x"))
	}
	user, err := windows.GetCurrentProcessToken().GetTokenUser()
	if err != nil {
		t.Fatal(err)
	}
	if err := windows.SetNamedSecurityInfo(foreign, windows.SE_FILE_OBJECT, windows.OWNER_SECURITY_INFORMATION,
		user.User.Sid, nil, nil, nil); err != nil {
		t.Fatal(err)
	}

	err = purge([]string{prog, data, filepath.Join(root, "missing"), foreign}, self)
	if err == nil || !strings.Contains(err.Error(), foreign) {
		t.Errorf("purge = %v, want an error about %s only", err, foreign)
	}
	for _, gone := range []string{filepath.Join(prog, frpcExeName), data} {
		if _, err := os.Stat(gone); !errors.Is(err, os.ErrNotExist) {
			t.Errorf("%s is still there: %v", gone, err)
		}
	}
	for _, kept := range []string{self, filepath.Join(foreign, "keep")} {
		if _, err := os.Stat(kept); err != nil {
			t.Errorf("%s is gone: %v", kept, err)
		}
	}
}

// Only an absolute path below a volume root can be purged; the check runs without deleting.
func TestPurgeable(t *testing.T) {
	for dir, want := range map[string]bool{
		`AdminHelper`:                        false,
		`\AdminHelper`:                       false,
		`C:\`:                                false,
		`C:`:                                 false,
		`\\server\share`:                     false,
		`\\server\share\`:                    false,
		`C:\ProgramData\AdminHelper`:         true,
		`\\server\share\AdminHelper`:         true,
		`C:\Program Files\AdminHelper Agent`: true,
	} {
		if got := purgeable(dir); got != want {
			t.Errorf("purgeable(%q) = %v, want %v", dir, got, want)
		}
	}
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
