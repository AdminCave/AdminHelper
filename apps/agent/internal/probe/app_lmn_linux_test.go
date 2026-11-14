// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"
)

// importLog is import-devices.log of two runs: an old one that completed, then one whose sync failed
// and that stopped.
const importLog = "2026-11-13 08:00:01 linuxmuster-import-devices started\n" +
	"2026-11-13 08:00:09 sophomorix-device --sync failed with return code 1\n" +
	"2026-11-13 08:00:20 linuxmuster-import-devices completed\n" +
	"2026-11-14 09:00:01 linuxmuster-import-devices started\n" +
	"2026-11-14 09:00:05 pc01: 2 errors detected in devices.csv\n" +
	"2026-11-14 09:00:09 sophomorix-device --sync failed with return code 1\n"

func TestLmnDevicesReadsTheLastRunOfTheLog(t *testing.T) {
	at := time.Unix(1_795_000_000, 0)
	stubNow(t, at)
	root := mailRoot(t)
	putHostFile(t, root, lmnDevicesCSV, "", at.Add(-2*time.Hour))
	putHostFile(t, root, lmnDevicesConf, "", at.Add(-time.Hour))
	putHostFile(t, root, lmnImportLog, importLog, at)
	got, err := lmnDevices(context.Background(), lmnUnit)
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]any{"import_pending": false, "last_import_age_s": 3600, "import_completed": false, "import_errors": 2}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
	putHostFile(t, root, lmnImportLog, importLog+"2026-11-14 09:00:30 linuxmuster-import-devices completed\n", at)
	got, err = lmnDevices(context.Background(), lmnUnit)
	if err != nil {
		t.Fatal(err)
	}
	if got["import_completed"] != true || got["import_errors"] != 2 {
		t.Fatalf("a completed run: %v", got)
	}
}

func TestLmnDevicesLeavesALogWithoutARunOut(t *testing.T) {
	root := mailRoot(t)
	at := time.Unix(1_795_000_000, 0)
	stubNow(t, at)
	putHostFile(t, root, lmnDevicesCSV, "", at)
	putHostFile(t, root, lmnImportLog, "2026-11-14 09:00:05 something else\n", at)
	got, err := lmnDevices(context.Background(), lmnUnit)
	if err != nil {
		t.Fatal(err)
	}
	if want := map[string]any{"import_pending": true}; !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
}

func TestLmnDevicesRefusesALinkedLog(t *testing.T) {
	root := mailRoot(t)
	at := time.Unix(1_795_000_000, 0)
	stubNow(t, at)
	putHostFile(t, root, lmnDevicesCSV, "", at)
	putHostFile(t, root, "etc/shadow", "root:x:\n", at)
	if err := os.MkdirAll(filepath.Join(root, "var/log/linuxmuster"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink("../../../etc/shadow", filepath.Join(root, filepath.FromSlash(lmnImportLog))); err != nil {
		t.Fatal(err)
	}
	if got, err := lmnDevices(context.Background(), lmnUnit); err == nil {
		t.Fatalf("a linked log read as %v", got)
	}
}

func TestLogTailStartsAtAWholeLine(t *testing.T) {
	root := mailRoot(t)
	putHostFile(t, root, "var/log/x.log", "first line\nsecond\nthird\n", time.Unix(1_795_000_000, 0))
	r, err := os.OpenRoot(root)
	if err != nil {
		t.Fatal(err)
	}
	defer r.Close()
	for n, want := range map[int64]string{100: "first line\nsecond\nthird\n", 10: "third\n", 3: ""} {
		got, err := logTail(r, "var/log/x.log", n)
		if err != nil {
			t.Fatal(err)
		}
		if string(got) != want {
			t.Errorf("tail %d = %q, want %q", n, got, want)
		}
	}
	if _, err := logTail(r, "var/log/none.log", 10); err == nil || !strings.Contains(err.Error(), "exist") {
		t.Fatalf("a missing log = %v", err)
	}
}
