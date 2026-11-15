// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"maps"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"slices"
	"strings"
	"testing"
	"time"
)

var aioAt = time.Date(2026, 11, 15, 4, 30, 0, 0, time.UTC)

// aioInspect is docker inspect of a container named name in state with the restart policy policy; its
// ID is the hex of the hash of name, the form docker gives and the allowlist takes.
func aioInspect(t *testing.T, name, state, policy string, pid int) string {
	t.Helper()
	b, err := json.Marshal(map[string]any{
		"Id": fmt.Sprintf("%x", sha256.Sum256([]byte(name))), "Name": "/" + name,
		"State":      map[string]any{"Status": state, "Running": state == "running", "Pid": pid},
		"HostConfig": map[string]any{"NetworkMode": "nextcloud-aio", "RestartPolicy": map[string]any{"Name": policy}},
		"Config":     map[string]any{"Image": "ghcr.io/nextcloud-releases/aio-" + name},
	})
	if err != nil {
		t.Fatal(err)
	}
	return string(b)
}

// aioHost is a mastercontainer (the target web, pid 4545) with the volume of its config, stubbed docker
// answering with the mastercontainer, the containers others and a container of another app, and
// stubbed time; it returns the root of the mastercontainer and the pids the view opened roots of.
func aioHost(t *testing.T, master string, others ...string) (string, *[]int) {
	t.Helper()
	root := t.TempDir()
	if err := os.MkdirAll(filepath.Join(root, filepath.FromSlash(aioConfigDir)), 0o755); err != nil {
		t.Fatal(err)
	}
	all := append([]string{master, aioInspect(t, "web", "running", "always", 4646)}, others...)
	stubDocker(t, master, all...)
	stubNow(t, aioAt)
	return root, stubContainerRoot(t, func(int) (*os.Root, error) { return os.OpenRoot(root) })
}

// aioMaster is the mastercontainer, running or not.
func aioMaster(t *testing.T, state string) string {
	return aioInspect(t, "nextcloud-aio-mastercontainer", state, "always", 4545)
}

// aioMark lays the marker of the daily backup, written age ago.
func aioMark(t *testing.T, root string, age time.Duration) {
	t.Helper()
	path := filepath.Join(root, filepath.FromSlash(aioBackupMarker))
	if err := os.WriteFile(path, nil, 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.Chtimes(path, aioAt.Add(-age), aioAt.Add(-age)); err != nil {
		t.Fatal(err)
	}
}

func aioTarget() Target { return Target{Kind: kindContainer, Name: "web"} }

func TestTheAIOViewCountsTheContainersAIOKeepsRunning(t *testing.T) {
	for _, c := range []struct {
		name   string
		apache string
		want   map[string]any
	}{
		{"all running", "running", map[string]any{"containers": 3, "stopped": 0, "backup": false, "backup_age_s": int64(0)}},
		{"apache stopped", "exited", map[string]any{"containers": 3, "stopped": 1, "backup": false, "backup_age_s": int64(0)}},
	} {
		t.Run(c.name, func(t *testing.T) {
			_, pids := aioHost(t, aioMaster(t, "running"),
				aioInspect(t, "nextcloud-aio-apache", c.apache, "unless-stopped", 0),
				aioInspect(t, "nextcloud-aio-nextcloud", "running", "unless-stopped", 0),
				aioInspect(t, "nextcloud-aio-database", "running", "unless-stopped", 0),
				// The containers AIO runs for a while have no restart policy; borgbackup stopped is no backup.
				aioInspect(t, "nextcloud-aio-watchtower", "exited", "no", 0),
				aioInspect(t, "nextcloud-aio-borgbackup", "exited", "no", 0),
				aioInspect(t, "nextcloud-other", "exited", "unless-stopped", 0),
			)
			got, err := nextcloudAIO(context.Background(), aioTarget())
			if err != nil {
				t.Fatal(err)
			}
			if !maps.Equal(got, c.want) {
				t.Errorf("got %v, want %v", got, c.want)
			}
			if !slices.Equal(*pids, []int{4545}) {
				t.Errorf("opened the roots of %v, want the mastercontainer's", *pids)
			}
		})
	}
}

func TestTheAIOViewTakesTheDailyBackupForNoFailure(t *testing.T) {
	root, _ := aioHost(t, aioMaster(t, "running"),
		aioInspect(t, "nextcloud-aio-apache", "exited", "unless-stopped", 0),
		aioInspect(t, "nextcloud-aio-nextcloud", "exited", "unless-stopped", 0),
		aioInspect(t, "nextcloud-aio-borgbackup", "running", "no", 0),
	)
	aioMark(t, root, 25*time.Minute)
	got, err := nextcloudAIO(context.Background(), aioTarget())
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]any{"containers": 2, "stopped": 0, "backup": true, "backup_age_s": int64(1500)}
	if !maps.Equal(got, want) {
		t.Errorf("got %v, want %v", got, want)
	}

	// A marker of a clock gone wrong is no older than now.
	aioMark(t, root, -time.Hour)
	if got, err := nextcloudAIO(context.Background(), aioTarget()); err != nil || got["backup_age_s"] != int64(0) {
		t.Errorf("a marker from the future = %v, %v; want age 0", got, err)
	}
}

func TestTheAIOViewTakesABackupFromTheInterfaceWithoutTheMarker(t *testing.T) {
	aioHost(t, aioMaster(t, "running"),
		aioInspect(t, "nextcloud-aio-apache", "exited", "unless-stopped", 0),
		aioInspect(t, "nextcloud-aio-borgbackup", "running", "no", 0),
	)
	got, err := nextcloudAIO(context.Background(), aioTarget())
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]any{"containers": 1, "stopped": 0, "backup": true, "backup_age_s": int64(0)}
	if !maps.Equal(got, want) {
		t.Errorf("got %v, want %v", got, want)
	}
}

func TestTheAIOViewStatsOnlyAMarkerThatIsARegularFile(t *testing.T) {
	cases := map[string]func(t *testing.T, root string){
		"a directory": func(t *testing.T, root string) {
			if err := os.Mkdir(filepath.Join(root, filepath.FromSlash(aioBackupMarker)), 0o755); err != nil {
				t.Fatal(err)
			}
		},
		"no config volume": func(t *testing.T, root string) {
			if err := os.RemoveAll(filepath.Join(root, "mnt")); err != nil {
				t.Fatal(err)
			}
		},
	}
	if runtime.GOOS != "windows" {
		cases["a link"] = func(t *testing.T, root string) {
			target := filepath.Join(root, "elsewhere")
			if err := os.WriteFile(target, nil, 0o644); err != nil {
				t.Fatal(err)
			}
			if err := os.Symlink(target, filepath.Join(root, filepath.FromSlash(aioBackupMarker))); err != nil {
				t.Fatal(err)
			}
		}
	}
	for name, prepare := range cases {
		t.Run(name, func(t *testing.T) {
			root, _ := aioHost(t, aioMaster(t, "running"), aioInspect(t, "nextcloud-aio-apache", "running", "unless-stopped", 0))
			prepare(t, root)
			_, err := nextcloudAIO(context.Background(), aioTarget())
			if err == nil {
				t.Fatal("no error, want one")
			}
			for _, s := range []string{"nextcloud-aio-", "daily_backup", "docker-aio-config", root} {
				if strings.Contains(err.Error(), s) {
					t.Errorf("the error %q names %q", err, s)
				}
			}
		})
	}
}

func TestTheAIOViewAsksARunningMastercontainer(t *testing.T) {
	_, pids := aioHost(t, aioMaster(t, "exited"))
	if _, err := nextcloudAIO(context.Background(), aioTarget()); err == nil || err.Error() != "the mastercontainer is not running" {
		t.Errorf("a stopped mastercontainer = %v, want it not running", err)
	}
	if len(*pids) != 0 {
		t.Errorf("opened the roots of %v, want none", *pids)
	}
}

func TestTheAIOViewIsAViewOfContainers(t *testing.T) {
	if v, ok := appViews["nextcloud_aio"]; !ok || !slices.Equal(v.kinds, containerKinds) {
		t.Errorf("appViews[nextcloud_aio] = %+v, want a view of containers", v)
	}
}

// aioID is the ID aioInspect gives the container named name.
func aioID(name string) string { return fmt.Sprintf("%x", sha256.Sum256([]byte(name))) }

// stubAIOTools answers docker ps with the answers in turn (the last one repeats) and docker inspect with
// inspect.
func stubAIOTools(t *testing.T, inspect func() ([]byte, error), ps ...func() ([]byte, error)) {
	t.Helper()
	old := runTool
	runTool = func(_ context.Context, _ time.Duration, _ string, args ...string) ([]byte, error) {
		switch args[0] {
		case "ps":
			answer := ps[0]
			if len(ps) > 1 {
				ps = ps[1:]
			}
			return answer()
		case "inspect":
			return inspect()
		}
		t.Errorf("unexpected call %v", args)
		return nil, errors.New("unexpected")
	}
	t.Cleanup(func() { runTool = old })
}

func aioPS(names ...string) func() ([]byte, error) {
	return func() ([]byte, error) {
		var ids []string
		for _, n := range names {
			ids = append(ids, aioID(n))
		}
		return []byte(strings.Join(ids, "\n") + "\n"), nil
	}
}

func TestInspectAllContainersFailsWhereDockerFails(t *testing.T) {
	ok := func() ([]byte, error) { return []byte("[]"), nil }
	for name, c := range map[string]struct {
		ps      func() ([]byte, error)
		inspect func() ([]byte, error)
	}{
		"docker ps fails":             {func() ([]byte, error) { return nil, errors.New("no daemon") }, ok},
		"docker inspect cannot start": {aioPS("a"), func() ([]byte, error) { return nil, errors.New("no docker") }},
		"docker inspect fails without an answer": {aioPS("a"), func() ([]byte, error) {
			return []byte("Error: daemon gone"), &exec.ExitError{}
		}},
		"docker inspect answers in another form": {aioPS("a"), func() ([]byte, error) { return []byte("{}"), nil }},
	} {
		t.Run(name, func(t *testing.T) {
			stubAIOTools(t, c.inspect, c.ps)
			if got, err := inspectAllContainers(context.Background()); err == nil {
				t.Errorf("inspectAllContainers = %v, nil; want an error", got)
			}
		})
	}
}

func TestInspectAllContainersTakesOnlyAContainerRemovedSinceDockerPs(t *testing.T) {
	// docker prints what it found and ends with exit 1 for the rest.
	partial := func() ([]byte, error) {
		return []byte("[" + aioInspect(t, "a", "running", "unless-stopped", 0) + "]"), &exec.ExitError{}
	}
	stubAIOTools(t, partial, aioPS("a", "b"), aioPS("a"))
	got, err := inspectAllContainers(context.Background())
	if err != nil || len(got) != 1 || got[0].ID != aioID("a") {
		t.Fatalf("a container removed since docker ps = %v, %v; want the other one", got, err)
	}

	stubAIOTools(t, partial, aioPS("a", "b"))
	if got, err := inspectAllContainers(context.Background()); err == nil {
		t.Errorf("a container docker inspect skipped but docker ps still lists = %v, nil; want an error", got)
	}
}
