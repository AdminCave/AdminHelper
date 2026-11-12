// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"fmt"
	"os/exec"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/shirou/gopsutil/v4/process"
)

// The rc.d services of FreeBSD, the units of that platform. They live here without a build tag, so
// the tests run on any platform with a fake service(8); the _freebsd files only wire them.

// servicePath is service(8) of the FreeBSD base system.
const servicePath = "/usr/sbin/service"

// rcNamePattern is a name service(8) takes: it runs "<dir>/<name>" for /etc/rc.d and each
// local_startup directory, so a "/" would leave the directory, a leading "." name it or its parent,
// a leading "-" be one of its options.
var rcNamePattern = regexp.MustCompile(`^[A-Za-z0-9_][A-Za-z0-9._-]{0,254}$`)

// The two answers of rc.subr's status (releng/14.3), on stdout: "<name> is running as pid <pids>."
// with every pid found, apart by blanks, exit 0; "<name> is not running.", exit 1. <name> is the
// script's name=, which may differ from its file name.
var (
	rcRunning    = regexp.MustCompile(`^\S+ is running as pid ([0-9]+(?: [0-9]+)*)\.$`)
	rcNotRunning = regexp.MustCompile(`^\S+ is not running\.$`)
)

// processStarted returns when the process pid started, in unix milliseconds; tests stand in their own.
var processStarted = func(ctx context.Context, pid int32) (int64, error) {
	p, err := process.NewProcessWithContext(ctx, pid)
	if err != nil {
		return 0, err
	}
	return p.CreateTimeWithContext(ctx)
}

// rcStatus returns the pids of the rc.d service name, none while it does not run. onestatus answers
// whether or not rc.conf enables the service. A script that does not exist, one without a status of
// its own and one whose status prints something else answer in another form: an error.
func rcStatus(ctx context.Context, name string) ([]int32, error) {
	out, err := runTool(ctx, toolTimeout, servicePath, name, "onestatus")
	var exitErr *exec.ExitError
	if err != nil && !errors.As(err, &exitErr) {
		return nil, fmt.Errorf("service %s onestatus: %w", name, err)
	}
	for line := range strings.SplitSeq(string(out), "\n") {
		line = strings.TrimSpace(line)
		if m := rcRunning.FindStringSubmatch(line); m != nil {
			var pids []int32
			for f := range strings.FieldsSeq(m[1]) {
				pid, err := strconv.ParseInt(f, 10, 32)
				if err != nil || pid <= 0 {
					return nil, fmt.Errorf("service %s onestatus: pid %q", name, f)
				}
				pids = append(pids, int32(pid))
			}
			return pids, nil
		}
		if rcNotRunning.MatchString(line) {
			return nil, nil
		}
	}
	return nil, fmt.Errorf("service %s does not exist on this host or has no status the sensor reads", name)
}

// rcOwner returns whether a process is one of the rc.d service name: a pid its status names. A child
// it forked may hold the listening socket as well; sockstat lists the parent's descriptor too.
func rcOwner(ctx context.Context, name string) (func(pid int32) bool, error) {
	pids, err := rcStatus(ctx, name)
	if err != nil {
		return nil, err
	}
	if len(pids) == 0 {
		return nil, fmt.Errorf("service %s is not running: it %w", name, errNotListening)
	}
	return func(p int32) bool { return slices.Contains(pids, p) }, nil
}

// measureRC reads the state of the rc.d service name as the active_state and sub_state of a systemd
// unit, as on Windows: active/running or inactive/stopped. While it runs, active_since is when the
// first pid of its status started. rc(8) counts no restarts.
func measureRC(ctx context.Context, name string) (map[string]any, error) {
	pids, err := rcStatus(ctx, name)
	if err != nil {
		return nil, err
	}
	if len(pids) == 0 {
		return map[string]any{"active_state": "inactive", "sub_state": "stopped"}, nil
	}
	values := map[string]any{"active_state": "active", "sub_state": "running"}
	if ms, err := processStarted(ctx, pids[0]); err == nil {
		values["active_since"] = time.UnixMilli(ms).Unix()
	}
	return values, nil
}
