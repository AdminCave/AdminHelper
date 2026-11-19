// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"reflect"
	"testing"
	"time"

	"adminhelper-agent/internal/allowlist"
)

// stubShares stands in a Linux host with the mounts given and a stat that answers with answer; it
// returns the calls stat got.
func stubShares(t *testing.T, mounts []NetMount, answer func() ([]byte, error)) *[][]string {
	t.Helper()
	oldGOOS, oldTable, oldRun := netShareGOOS, mountTable, runTool
	t.Cleanup(func() { netShareGOOS, mountTable, runTool = oldGOOS, oldTable, oldRun })
	netShareGOOS = "linux"
	mountTable = func() ([]NetMount, error) { return mounts, nil }
	var calls [][]string
	runTool = func(_ context.Context, timeout time.Duration, name string, args ...string) ([]byte, error) {
		calls = append(calls, append([]string{name}, args...))
		if !allowlist.Allowed(name, args) {
			t.Errorf("call %q is not on the command allowlist", append([]string{name}, args...))
		}
		if timeout != shareTimeout {
			t.Errorf("timeout %s, want %s", timeout, shareTimeout)
		}
		return answer()
	}
	return &calls
}

var shareMounts = []NetMount{{"/", "ext4"}, {"/mnt/pve/backup", "nfs4"}, {"/srv/data", "xfs"}}

func shareProbe(point string) Probe {
	return Probe{Sensor: "app", Params: map[string]any{"view": "net_share_usage"}, Target: &Target{Kind: kindShare, Name: point}}
}

func TestNetShareUsageReadsTheFillOfAMountedShare(t *testing.T) {
	// 4096-byte blocks: 1000 in all, 300 free, 200 of them free to a user.
	calls := stubShares(t, shareMounts, func() ([]byte, error) { return []byte("4096 1000 300 200\n"), nil })
	got, err := appSensor(context.Background(), shareProbe("/mnt/pve/backup"), "")
	want := map[string]any{"mounted": true, "hung": false, "used_percent": 77.8, "free_gb": 0.0}
	if err != nil || !reflect.DeepEqual(got, want) {
		t.Fatalf("view = %v, %v; want %v", got, err, want)
	}
	if want := [][]string{{"stat", "-f", "-c", "%S %b %f %a", "--", "/mnt/pve/backup"}}; !reflect.DeepEqual(*calls, want) {
		t.Errorf("calls = %q, want %q", *calls, want)
	}
}

func TestNetShareUsageCountsTheFreeGigabytes(t *testing.T) {
	stubShares(t, shareMounts, func() ([]byte, error) { return []byte("1048576 10240 4096 3584\n"), nil })
	got, err := netShareUsage(context.Background(), Target{Kind: kindShare, Name: "/mnt/pve/backup"})
	if err != nil || got["free_gb"] != 3.5 || got["used_percent"] != 63.2 {
		t.Errorf("view = %v, %v; want 3.5 GB free, 63.2 %% used", got, err)
	}
}

func TestNetShareThatDoesNotAnswerInTimeHangs(t *testing.T) {
	stubShares(t, shareMounts, func() ([]byte, error) { return nil, context.DeadlineExceeded })
	got, err := netShareUsage(context.Background(), Target{Kind: kindShare, Name: "/mnt/pve/backup"})
	if want := map[string]any{"mounted": true, "hung": true}; err != nil || !reflect.DeepEqual(got, want) {
		t.Errorf("view = %v, %v; want %v", got, err, want)
	}
}

func TestNetShareProbeThatEndsIsNoHungShare(t *testing.T) {
	stubShares(t, shareMounts, func() ([]byte, error) { return nil, context.DeadlineExceeded })
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if got, err := netShareUsage(ctx, Target{Kind: kindShare, Name: "/mnt/pve/backup"}); err == nil {
		t.Errorf("view = %v, want an error: the probe's own end says nothing of the share", got)
	}
}

func TestNetShareMissingIsNotMounted(t *testing.T) {
	calls := stubShares(t, shareMounts, func() ([]byte, error) { return nil, errors.New("no stat expected") })
	got, err := netShareUsage(context.Background(), Target{Kind: kindShare, Name: "/mnt/pve/iso"})
	if want := map[string]any{"mounted": false, "hung": false}; err != nil || !reflect.DeepEqual(got, want) {
		t.Errorf("view = %v, %v; want %v", got, err, want)
	}
	if len(*calls) != 0 {
		t.Errorf("stat ran for a mount point that is not mounted: %q", *calls)
	}
}

func TestNetShareRefusesALocalFileSystem(t *testing.T) {
	calls := stubShares(t, shareMounts, func() ([]byte, error) { return nil, errors.New("no stat expected") })
	for _, point := range []string{"/srv/data", "/"} {
		if got, err := netShareUsage(context.Background(), Target{Kind: kindShare, Name: point}); !errors.Is(err, ErrInvalid) {
			t.Errorf("%s: view = %v, %v; want ErrInvalid", point, got, err)
		}
	}
	if len(*calls) != 0 {
		t.Errorf("stat ran for a local file system: %q", *calls)
	}
}

func TestNetShareIsCheckedOnLinuxAlone(t *testing.T) {
	stubShares(t, shareMounts, func() ([]byte, error) { return []byte("4096 1 1 1"), nil })
	netShareGOOS = "freebsd"
	if _, err := netShareUsage(context.Background(), Target{Kind: kindShare, Name: "/mnt/pve/backup"}); !errors.Is(err, ErrUnsupported) {
		t.Errorf("err = %v, want ErrUnsupported", err)
	}
}

func TestNetShareRefusesWhatStatWritesOutOfShape(t *testing.T) {
	for _, out := range []string{"", "4096 1000 300", "4096 1000 300 x", "0 1000 300 200", "4096 1000 1300 200", "4096 1000 300 400", "-1 1 1 1"} {
		stubShares(t, shareMounts, func() ([]byte, error) { return []byte(out), nil })
		if got, err := netShareUsage(context.Background(), Target{Kind: kindShare, Name: "/mnt/pve/backup"}); !errors.Is(err, ErrUnsupported) {
			t.Errorf("%q: view = %v, %v; want ErrUnsupported", out, got, err)
		}
	}
}
