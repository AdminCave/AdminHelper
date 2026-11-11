// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build freebsd

package frpc

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"strconv"
	"time"

	"adminhelper-agent/internal/config"
)

// reloadTimeout bounds `frpc reload`, as on Linux.
const reloadTimeout = 15 * time.Second

// serviceTimeout caps every service(8) call of the FRP sync, as systemctlTimeout does on Linux.
// serviceCommand and sockstatCommand are absolute, whatever PATH the caller has. Vars only so
// tests can point them elsewhere.
var (
	serviceTimeout  = 15 * time.Second
	serviceCommand  = "/usr/sbin/service"
	sockstatCommand = "/usr/bin/sockstat"
)

// service runs one `service adminhelper_frpc <args>` under serviceTimeout and ctx. A call that one
// of them ended returns the context's error, as systemctl does on Linux. Its output goes to
// /dev/null: daemon(8) detaches from the terminal but its children would otherwise hold a pipe of
// ours open.
func service(ctx context.Context, args ...string) error {
	ctx, cancel := context.WithTimeout(ctx, serviceTimeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, serviceCommand, append([]string{rcName}, args...)...)
	cmd.WaitDelay = 2 * time.Second
	err := cmd.Run()
	if err != nil && ctx.Err() != nil {
		return ctx.Err()
	}
	return err
}

// enableFrpcService sets adminhelper_frpc_enable=YES (rc.subr's enable runs sysrc), so frpc
// starts at boot, and starts it. onestart: a start that rc.subr skips because it reads the rcvar
// as off exits 0 as well, which would pass for a started frpc. The cron job is not touched, as
// on Linux the timer is not (R-0641).
func enableFrpcService(ctx context.Context) error {
	if err := service(ctx, "enable"); err != nil {
		return fmt.Errorf("enable %s: %w", rcName, err)
	}
	if err := service(ctx, "onestart"); err != nil {
		return fmt.Errorf("start %s: %w", rcName, err)
	}
	return nil
}

// restartFrpc restarts frpc. onerestart: a plain restart does nothing while the rcvar is off,
// and exits 0 all the same.
func restartFrpc(ctx context.Context) error {
	return service(ctx, "onerestart")
}

// disableFrpc stops frpc and keeps it from starting at boot. faststop exits 0 when frpc does not
// run; a plain stop would fail then.
func disableFrpc(ctx context.Context) error {
	if err := service(ctx, "faststop"); err != nil {
		return fmt.Errorf("stop %s: %w", rcName, err)
	}
	if err := service(ctx, "disable"); err != nil {
		return fmt.Errorf("disable %s: %w", rcName, err)
	}
	return nil
}

// frpcActive reports whether the daemon(8) of adminhelper_frpc runs; `status` exits 1 when not.
// A call without an exit status is an error, not "not active", as on Linux.
func frpcActive(ctx context.Context) (bool, error) {
	err := service(ctx, "status")
	if err == nil {
		return true, nil
	}
	var exitErr *exec.ExitError
	if errors.As(err, &exitErr) && exitErr.ExitCode() > 0 {
		return false, nil
	}
	return false, fmt.Errorf("service %s status: %w", rcName, err)
}

// frpcDown reports whether frpc does not run, also while daemon(8) waits to restart it: daemon
// runs on while frpc fails, and empties the child pidfile until the next start.
func frpcDown(ctx context.Context) (bool, error) {
	active, err := frpcActive(ctx)
	if err != nil {
		return false, err
	}
	if !active {
		return true, nil
	}
	pid, err := childPid()
	if errors.Is(err, fs.ErrNotExist) {
		return true, nil
	}
	if err != nil {
		return false, fmt.Errorf("read %s: %w", rcChildPidFile, err)
	}
	return pid == "", nil
}

// childPid reads frpc's pid from the child pidfile, which root's daemon(8) writes in /var/run.
func childPid() (string, error) {
	data, err := os.ReadFile(rcChildPidFile)
	return string(bytes.TrimSpace(data)), err
}

// frpcOwnsAdminPort reports whether the frpc adminhelper_frpc runs as root listens on
// 127.0.0.1:port; the reload goes only to it. FreeBSD has no /proc/net/tcp; sockstat lists the
// sockets with their owner and pid, and the child pidfile names frpc's pid. Without one, frpc
// does not run.
func frpcOwnsAdminPort(port int) bool {
	pid, err := childPid()
	if err != nil || pid == "" {
		return false
	}
	return sockstatListens(port, "0", pid)
}

// sockstatListens asks sockstat for the IPv4 TCP sockets listening on port and reads its answer
// with sockstatListensOnLoopback. A failing sockstat counts as no listener.
func sockstatListens(port int, uid, pid string) bool {
	ctx, cancel := context.WithTimeout(context.Background(), serviceTimeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, sockstatCommand, "-4", "-l", "-q", "-n", "-P", "tcp", "-p", strconv.Itoa(port))
	cmd.WaitDelay = 2 * time.Second
	out, err := cmd.Output()
	if err != nil {
		return false
	}
	return sockstatListensOnLoopback(out, port, uid, pid)
}

// reloadFrpc has the running frpc take the proxies from frpc.toml again, over its admin API on
// loopback, as on Linux; the binary is the one adminhelper_frpc runs.
func reloadFrpc(ctx context.Context) error {
	ctx, cancel := context.WithTimeout(ctx, reloadTimeout)
	defer cancel()
	out, err := exec.CommandContext(ctx, rcFrpcBinary, "reload", "-c", config.FrpConfigFile()).CombinedOutput()
	if err != nil {
		return fmt.Errorf("frpc reload: %w: %s", err, bytes.TrimSpace(out))
	}
	return nil
}
