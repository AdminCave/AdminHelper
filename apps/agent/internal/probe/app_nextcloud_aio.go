// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os/exec"
	"strings"
	"time"
)

const (
	// aioPrefix starts the name of every container Nextcloud All-in-One runs (php/containers.json).
	aioPrefix = "nextcloud-aio-"
	// aioBorg runs a backup; started from the interface of AIO, it runs without aioBackupMarker.
	aioBorg = "nextcloud-aio-borgbackup"
	// aioKeep is the restart policy of the containers AIO keeps running; borgbackup, watchtower and
	// domaincheck run for a while and have none.
	aioKeep = "unless-stopped"
)

var (
	// aioConfigDir is the volume of the mastercontainer, relative to the root of its container.
	aioConfigDir = "mnt/docker-aio-config/data"
	// aioBackupMarker is created by daily-backup.sh before it stops the containers and removed once they
	// run again; cron.sh resumes a backup while it lies there.
	aioBackupMarker = aioConfigDir + "/daily_backup_running"
)

// nextcloudAIO counts the containers Nextcloud All-in-One keeps running beside its mastercontainer t
// and those of them that do not run, and tells if a backup runs: the daily one stops the containers on
// purpose, so stopped is 0 while it runs, and backup_age_s is how long the daily one has run. It stats
// the marker of the daily backup below the root of t and never reads it; no value and no error names a
// container or a path.
func nextcloudAIO(ctx context.Context, t Target) (map[string]any, error) {
	c, err := inspectContainer(ctx, t.Name)
	if err != nil {
		return nil, err
	}
	if !c.State.Running || c.State.Pid <= 0 {
		return nil, errors.New("the mastercontainer is not running")
	}
	type marker struct {
		age    int64
		exists bool
	}
	m, err := untilDone(ctx, func() (marker, error) {
		age, exists, err := aioMarker(c.State.Pid)
		return marker{age, exists}, err
	})
	if err != nil {
		return nil, fmt.Errorf("the mastercontainer: %w", err)
	}
	list, err := inspectAllContainers(ctx)
	if err != nil {
		return nil, err
	}
	containers, stopped, borg := 0, 0, false
	for _, x := range list {
		name := strings.TrimPrefix(x.Name, "/")
		if name == aioBorg && x.State.Running {
			borg = true
		}
		if x.ID == c.ID || !strings.HasPrefix(name, aioPrefix) || x.HostConfig.RestartPolicy.Name != aioKeep {
			continue
		}
		containers++
		if !x.State.Running {
			stopped++
		}
	}
	backup := m.exists || borg
	if backup {
		stopped = 0
	}
	return map[string]any{"containers": containers, "stopped": stopped, "backup": backup, "backup_age_s": m.age}, nil
}

// aioMarker stats aioBackupMarker below the root of the process pid without following a link at it:
// whether it is there and its age in seconds, never below 0. A config directory that is missing, or a
// marker that is no regular file, is an error.
func aioMarker(pid int) (int64, bool, error) {
	root, err := containerRoot(pid)
	if errors.Is(err, ErrUnsupported) {
		return 0, false, err
	}
	if err != nil {
		return 0, false, fmt.Errorf("its root cannot be opened: %v", cause(err))
	}
	defer root.Close()
	if fi, err := root.Lstat(aioConfigDir); err != nil || !fi.IsDir() {
		return 0, false, errors.New("it holds no config volume of All-in-One")
	}
	fi, err := root.Lstat(aioBackupMarker)
	switch {
	case errors.Is(err, fs.ErrNotExist):
		return 0, false, nil
	case err != nil:
		return 0, false, fmt.Errorf("the marker of the daily backup cannot be read: %v", cause(err))
	case !fi.Mode().IsRegular():
		return 0, false, errors.New("the marker of the daily backup is no regular file")
	}
	return max(0, int64(now().Sub(fi.ModTime())/time.Second)), true, nil
}

// inspectAllContainers returns docker inspect of every container docker knows. As in dockerPublications,
// a container removed since docker ps fails the inspect of it alone.
func inspectAllContainers(ctx context.Context) ([]containerInfo, error) {
	ids, err := dockerContainers(ctx)
	if err != nil || len(ids) == 0 {
		return nil, err
	}
	out, err := runTool(ctx, toolTimeout, "docker", append([]string{"inspect", "--type", "container"}, ids...)...)
	var exitErr *exec.ExitError
	if err != nil && !errors.As(err, &exitErr) {
		return nil, fmt.Errorf("docker inspect: %w", err)
	}
	var list []containerInfo
	if jerr := json.Unmarshal(out, &list); jerr != nil {
		if err != nil {
			return nil, fmt.Errorf("docker inspect: %w", err)
		}
		return nil, errors.New("docker inspect: an answer of another form")
	}
	if err != nil {
		if err := goneSince(ctx, ids, list); err != nil {
			return nil, err
		}
	}
	return list, nil
}
