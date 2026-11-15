// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"testing"
	"time"
)

var lmnUnit = Target{Kind: kindUnit, Name: "linuxmuster-webui.service"}

// putHostFile writes content to name below root, modified at.
func putHostFile(t *testing.T, root, name, content string, at time.Time) {
	t.Helper()
	full := filepath.Join(root, filepath.FromSlash(name))
	if err := os.MkdirAll(filepath.Dir(full), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(full, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Chtimes(full, at, at); err != nil {
		t.Fatal(err)
	}
}

func TestLmnDevicesComparesTheListWithTheLastImport(t *testing.T) {
	at := time.Unix(1_795_000_000, 0)
	stubNow(t, at)
	root := mailRoot(t)
	putHostFile(t, root, lmnDevicesCSV, "r100;pc01;pcs;00:00:5e:00:53:01;192.0.2.10;;;;classroom-studentcomputer;;1;;;;SETUP;\n", at.Add(-2*time.Hour))
	putHostFile(t, root, lmnDevicesConf, "host pc01 {}\n", at.Add(-time.Hour))
	got, err := lmnDevices(context.Background(), lmnUnit)
	if err != nil {
		t.Fatal(err)
	}
	if want := map[string]any{"import_pending": false, "last_import_age_s": 3600}; !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
	putHostFile(t, root, lmnDevicesCSV, "changed\n", at.Add(-time.Minute))
	got, err = lmnDevices(context.Background(), lmnUnit)
	if err != nil {
		t.Fatal(err)
	}
	if got["import_pending"] != true {
		t.Fatalf("a list changed after the import: %v", got)
	}
}

func TestLmnDevicesReadsTheFileOfTheSchool(t *testing.T) {
	at := time.Unix(1_795_000_000, 0)
	stubNow(t, at)
	root := mailRoot(t)
	putHostFile(t, root, lmnDevicesCSV, "", at.Add(-2*time.Hour))
	// The import of another school wrote devices.conf after the change; the default school's file is older.
	putHostFile(t, root, lmnDevicesConf, "", at.Add(-3*time.Hour))
	putHostFile(t, root, lmnDevicesConfAll, "", at.Add(-time.Hour))
	got, err := lmnDevices(context.Background(), lmnUnit)
	if err != nil {
		t.Fatal(err)
	}
	if want := map[string]any{"import_pending": true, "last_import_age_s": 10800}; !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
	// Without the file of the school (an older linuxmuster-base7) devices.conf stands in.
	if err := os.Remove(filepath.Join(root, filepath.FromSlash(lmnDevicesConf))); err != nil {
		t.Fatal(err)
	}
	got, err = lmnDevices(context.Background(), lmnUnit)
	if err != nil {
		t.Fatal(err)
	}
	if want := map[string]any{"import_pending": false, "last_import_age_s": 3600}; !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
}

func TestLmnDevicesWithoutAnImport(t *testing.T) {
	stubNow(t, time.Unix(1_795_000_000, 0))
	root := mailRoot(t)
	putHostFile(t, root, lmnDevicesCSV, "", time.Unix(1_794_000_000, 0))
	got, err := lmnDevices(context.Background(), lmnUnit)
	if err != nil {
		t.Fatal(err)
	}
	if want := map[string]any{"import_pending": true}; !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
}

func TestLmnDevicesWithoutLinuxmuster(t *testing.T) {
	mailRoot(t)
	if _, err := lmnDevices(context.Background(), lmnUnit); !errors.Is(err, ErrUnsupported) {
		t.Fatalf("no devices.csv = %v, want unsupported", err)
	}
}

func TestLmnLinboCountsImagesWithAStaleTorrent(t *testing.T) {
	at := time.Unix(1_795_000_000, 0)
	root := mailRoot(t)
	img := func(name string, age time.Duration) {
		putHostFile(t, root, lmnImageDir+"/"+name, "x", at.Add(-age))
	}
	// Current torrent, old torrent, no torrent; one level down; and what is no image or is staged.
	img("ubuntu/ubuntu.qcow2", 2*time.Hour)
	img("ubuntu/ubuntu.qcow2.torrent", time.Hour)
	img("ubuntu/ubuntu-20261101.qdiff", time.Hour)
	img("ubuntu/ubuntu-20261101.qdiff.torrent", 2*time.Hour)
	img("win11/win11.qcow2", time.Hour)
	img("win11/win11.qcow2.info", time.Hour)
	img("tools.iso", time.Hour)
	img("tools.iso.torrent", time.Hour)
	img("ubuntu/backups/202611010000/ubuntu.qcow2", time.Hour)
	img(".incoming/new.qcow2", time.Hour)
	img("start.conf.ubuntu", time.Hour)
	got, err := lmnLinbo(context.Background(), lmnUnit)
	if err != nil {
		t.Fatal(err)
	}
	if want := map[string]any{"images": 4, "torrents_stale": 2}; !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
}

func TestLmnLinboLeavesOutAnImageThatIsGone(t *testing.T) {
	root := mailRoot(t)
	putHostFile(t, root, lmnImageDir+"/kept.qcow2", "x", time.Unix(1_795_000_000, 0))
	r, err := hostRoot()
	if err != nil {
		t.Fatal(err)
	}
	defer r.Close()
	if _, err := torrentStale(r, lmnImageDir+"/gone.qcow2"); !errors.Is(err, errImageGone) {
		t.Fatalf("an image that is gone = %v, want errImageGone", err)
	}
	got, err := lmnLinbo(context.Background(), lmnUnit)
	if err != nil || got["images"] != 1 {
		t.Fatalf("got %v, %v; want the image that is there", got, err)
	}
}

func TestLmnLinboWithoutImages(t *testing.T) {
	root := mailRoot(t)
	if _, err := lmnLinbo(context.Background(), lmnUnit); !errors.Is(err, ErrUnsupported) {
		t.Fatalf("no image directory = %v, want unsupported", err)
	}
	putHostFile(t, root, lmnImageDir, "no directory", time.Unix(1_795_000_000, 0))
	if _, err := lmnLinbo(context.Background(), lmnUnit); err == nil || errors.Is(err, ErrUnsupported) {
		t.Fatalf("a file as image directory = %v", err)
	}
}
