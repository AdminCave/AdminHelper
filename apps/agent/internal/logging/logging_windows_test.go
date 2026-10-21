// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package logging

import (
	"bytes"
	"encoding/xml"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
	"unsafe"

	"golang.org/x/sys/windows"

	"adminhelper-agent/internal/config"
)

// requireProtected fails unless the Administrators own the directory path and its
// DACL is protected and grants SYSTEM and the Administrators only.
func requireProtected(t *testing.T, path string) {
	t.Helper()
	sd, err := windows.GetNamedSecurityInfo(path, windows.SE_FILE_OBJECT,
		windows.OWNER_SECURITY_INFORMATION|windows.DACL_SECURITY_INFORMATION)
	if err != nil {
		t.Fatalf("read the security descriptor of %s: %v", path, err)
	}
	owner, _, err := sd.Owner()
	if err != nil {
		t.Fatal(err)
	}
	control, _, err := sd.Control()
	if err != nil {
		t.Fatal(err)
	}
	dacl, _, err := sd.DACL()
	if err != nil {
		t.Fatal(err)
	}
	if owner.String() != "S-1-5-32-544" || control&windows.SE_DACL_PROTECTED == 0 || dacl.AceCount != 2 {
		t.Fatalf("%s is not protected for SYSTEM and the Administrators: %s", path, sd)
	}
	for i := range uint32(dacl.AceCount) {
		var ace *windows.ACCESS_ALLOWED_ACE
		if err := windows.GetAce(dacl, i, &ace); err != nil {
			t.Fatal(err)
		}
		sid := (*windows.SID)(unsafe.Pointer(&ace.SidStart)).String()
		if ace.Header.AceType != windows.ACCESS_ALLOWED_ACE_TYPE || (sid != "S-1-5-18" && sid != "S-1-5-32-544") {
			t.Fatalf("the DACL of %s grants more than SYSTEM and the Administrators: %s", path, sd)
		}
	}
}

// Init secures the log directory, and the data root above it, before anything is
// logged: the file logger would create both on its first write, with the rights
// inherited from above.
func TestInitSecuresTheLogDirBeforeLogging(t *testing.T) {
	root := filepath.Join(t.TempDir(), "root")
	logDir := filepath.Join(root, "logs")
	t.Setenv("ADMINHELPER_MONITOR_DIR", root)
	t.Setenv("ADMINHELPER_LOG_DIR", logDir)
	prev := slog.Default()
	t.Cleanup(func() { slog.SetDefault(prev) })

	Init("info")

	info, err := os.Lstat(logDir)
	if err != nil {
		t.Fatalf("the log directory is missing after Init: %v", err)
	}
	if !info.IsDir() {
		t.Fatalf("%s is not a directory: mode %v", logDir, info.Mode())
	}
	requireProtected(t, root)
	requireProtected(t, logDir)
	if _, err := os.Lstat(filepath.Join(logDir, "agent.log")); !os.IsNotExist(err) {
		t.Fatalf("agent.log exists although nothing was logged (Lstat: %v)", err)
	}
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

// When the log directory cannot be secured, Init logs to stdout only: no agent.log
// appears, also after a log line. The test binary does not run as a service, so Init
// stays silent, as in any interactive run. The open data root holds a child of
// another account that is held open, so that it cannot be removed.
func TestInitLogsToStdoutOnlyWhenTheLogDirCannotBeSecured(t *testing.T) {
	root := t.TempDir()
	logDir := filepath.Join(root, "logs")
	holdForeignChild(t, root, "a-held.txt")
	t.Setenv("ADMINHELPER_MONITOR_DIR", root)
	t.Setenv("ADMINHELPER_LOG_DIR", logDir)
	prev := slog.Default()
	t.Cleanup(func() { slog.SetDefault(prev) })

	Init("info")
	slog.Info("a line after Init")

	if _, err := os.Lstat(filepath.Join(logDir, "agent.log")); !os.IsNotExist(err) {
		t.Fatalf("agent.log exists although the log directory could not be secured (Lstat: %v)", err)
	}
}

// loggedEvent is what the test reads of an entry in the XML of wevtutil.
type loggedEvent struct {
	EventID uint32   `xml:"System>EventID"`
	Level   int      `xml:"System>Level"`
	Data    []string `xml:"EventData>Data"`
}

// queryEvents returns the newest entries of source in the Application log. It waits up
// to 10 s for the first one: whether an entry is readable as soon as ReportEvent
// returns is not verified.
func queryEvents(t *testing.T, source string) []loggedEvent {
	t.Helper()
	query := "/q:*[System[Provider[@Name='" + source + "']]]"
	deadline := time.Now().Add(10 * time.Second)
	for {
		out, err := exec.Command("wevtutil", "qe", "Application", query, "/rd:true", "/c:5", "/f:xml").CombinedOutput()
		if err != nil {
			t.Fatalf("wevtutil qe: %v: %s", err, out)
		}
		var events []loggedEvent
		dec := xml.NewDecoder(bytes.NewReader(out))
		for {
			var ev loggedEvent
			if err := dec.Decode(&ev); errors.Is(err, io.EOF) {
				break
			} else if err != nil {
				t.Fatalf("parse the output of wevtutil: %v: %s", err, out)
			}
			events = append(events, ev)
		}
		if len(events) > 0 || time.Now().After(deadline) {
			return events
		}
		time.Sleep(250 * time.Millisecond)
	}
}

// As a Windows service, Init writes a log directory it cannot secure once as a warning
// to the Application log, with the directory and the reason in the event data. The
// open data root holds a child of another account that is held open, so that it cannot
// be removed. The source has a name of its own, so that the query finds only what this
// run wrote; it is not registered, so Windows keeps the entry without a description,
// and the test reads the XML.
func TestInitWritesAnUnsecuredLogDirToTheEventLogAsAService(t *testing.T) {
	root := t.TempDir()
	logDir := filepath.Join(root, "logs")
	holdForeignChild(t, root, "a-held.txt")
	t.Setenv("ADMINHELPER_MONITOR_DIR", root)
	t.Setenv("ADMINHELPER_LOG_DIR", logDir)
	source := fmt.Sprintf("%s-Test-%d-%d", EventSource, os.Getpid(), time.Now().UnixNano())
	var reason error
	origEnsure, origReporter, prev := ensureLogDir, serviceReporter, slog.Default()
	ensureLogDir = func() error { reason = config.EnsureLogDir(); return reason }
	serviceReporter = func() reportFunc { return eventLogWarning(source) }
	t.Cleanup(func() {
		ensureLogDir, serviceReporter = origEnsure, origReporter
		slog.SetDefault(prev)
	})

	Init("info")

	if reason == nil {
		t.Fatal("EnsureLogDir succeeded although a child of another account is held open in the data root")
	}
	events := queryEvents(t, source)
	if len(events) != 1 {
		t.Fatalf("the Application log holds %d entries of %s, want 1: %+v", len(events), source, events)
	}
	ev := events[0]
	// Level 3 is a warning.
	if ev.EventID != unsecuredLogDirEventID || ev.Level != 3 {
		t.Errorf("event ID %d, level %d, want %d and 3 (warning)", ev.EventID, ev.Level, unsecuredLogDirEventID)
	}
	data := strings.Join(ev.Data, "\n")
	for _, want := range []string{logDir, reason.Error()} {
		if !strings.Contains(data, want) {
			t.Errorf("the event data %q is missing %q", data, want)
		}
	}
}
