// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os/exec"
	"os/user"
	"path/filepath"
	"regexp"
	"strings"
)

var (
	// pm2Unit is the unit `pm2 startup` writes for a user, pm2-<user>; the user is a name of
	// useradd's default NAME_REGEX.
	pm2Unit = regexp.MustCompile(`^pm2-([a-z_][a-z0-9_-]*)$`)
	// pm2Home and pm2Dial find the home directory of a user and reach the daemon's socket; tests
	// stand in their own.
	pm2Home = func(name string) (string, error) {
		u, err := user.Lookup(name)
		if err != nil {
			return "", err
		}
		return u.HomeDir, nil
	}
	pm2Dial = dialUnix
)

// pm2Proc is the part of a process of pm2 jlist pm2Apps reads; the rest (pm2_env carries the
// process's whole environment) stays unread.
type pm2Proc struct {
	Env *struct {
		Status      string `json:"status"`
		RestartTime *int64 `json:"restart_time"`
	} `json:"pm2_env"`
}

// pm2Apps counts the apps of the pm2 daemon of unit pm2-<user>: all, those errored, those stopped,
// and the sum of their restarts (counted since the daemon started them, the server takes the growth).
// pm2 jlist runs as the user, never as root, and only while the daemon runs: without one it would
// start a daemon of its own and print its banner. Never a name.
//
// Checked against pm2 7.1.2: jlist prints a JSON array, of each app pm2_env.status (constants.js:
// online, stopping, stopped, launching, errored, one-launch-status, waiting restart) and
// pm2_env.restart_time; the daemon listens on ~/.pm2/rpc.sock (PM2_HOME).
func pm2Apps(ctx context.Context, t Target) (map[string]any, error) {
	m := pm2Unit.FindStringSubmatch(strings.TrimSuffix(t.Name, ".service"))
	if m == nil || m[1] == "root" {
		return nil, fmt.Errorf("%w: unit %s is no pm2 of a user other than root", ErrUnsupported, t.Name)
	}
	home, err := pm2Home(m[1])
	if err != nil {
		return nil, fmt.Errorf("%w: the user of unit %s is unknown", ErrUnsupported, t.Name)
	}
	sock := filepath.Join(home, ".pm2", "rpc.sock")
	if !validLocalPath(sock) || len(sock) > maxSocketPath {
		return nil, fmt.Errorf("%w: the user of unit %s has no home the agent reads", ErrUnsupported, t.Name)
	}
	conn, err := pm2Dial(ctx, sock)
	switch {
	case errors.Is(err, errNoListener) && !ended(ctx):
		return nil, fmt.Errorf("%w: the daemon of unit %s does not run", ErrUnsupported, t.Name)
	case err != nil:
		return nil, netErr(ctx, err)
	}
	_ = conn.Close()
	out, err := runTool(ctx, toolTimeout, "runuser", "-u", m[1], "--", "pm2", "jlist")
	var exitErr *exec.ExitError
	switch {
	case errors.Is(err, exec.ErrNotFound):
		return nil, fmt.Errorf("%w: runuser is not installed", ErrUnsupported)
	case errors.As(err, &exitErr) && exitErr.ExitCode() == 127:
		// runuser could not find the command it was to run.
		return nil, fmt.Errorf("%w: pm2 is not installed", ErrUnsupported)
	case err != nil:
		return nil, toolError("pm2", err)
	}
	var procs []pm2Proc
	if json.Unmarshal(out, &procs) != nil {
		return nil, errors.New("pm2: an answer of another form")
	}
	var restarts int64
	errored, stopped := 0, 0
	for _, p := range procs {
		if p.Env == nil || p.Env.Status == "" || p.Env.RestartTime == nil {
			return nil, errors.New("pm2: an answer of another form")
		}
		switch p.Env.Status {
		case "errored":
			errored++
		case "stopped":
			stopped++
		}
		restarts += *p.Env.RestartTime
	}
	return map[string]any{
		"apps": len(procs), "apps_errored": errored, "apps_stopped": stopped, "restarts": restarts,
	}, nil
}
