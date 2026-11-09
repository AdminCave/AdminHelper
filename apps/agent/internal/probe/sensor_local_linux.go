// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package probe

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"regexp"
	"strconv"
	"strings"
	"time"

	"golang.org/x/sys/unix"
)

// unitPattern is a systemd unit name (systemd.unit(5)), template instances included.
var unitPattern = regexp.MustCompile(`^[A-Za-z0-9:_.@\\-]{1,255}$`)

// The seams of the unit sensor to the host; tests stand in their own.
var (
	// systemdBooted says whether systemd runs this host, the test of sd_booted(3).
	systemdBooted = func() bool {
		_, err := os.Stat("/run/systemd/system")
		return err == nil
	}
	// monotonicNow reads CLOCK_MONOTONIC, the clock of systemd's …Monotonic timestamps.
	monotonicNow = func() (time.Duration, error) {
		var ts unix.Timespec
		if err := unix.ClockGettime(unix.CLOCK_MONOTONIC, &ts); err != nil {
			return 0, err
		}
		return time.Duration(ts.Nano()), nil
	}
)

// showUnit reads the properties props of the systemd unit name. A unit systemd does not know is an
// error, a host without systemd ErrUnsupported.
func showUnit(ctx context.Context, name string, props ...string) (map[string]string, error) {
	if !systemdBooted() {
		return nil, fmt.Errorf("%w: systemd does not run this host", ErrUnsupported)
	}
	out, err := runTool(ctx, toolTimeout, "systemctl", "show", "-p", "LoadState,"+strings.Join(props, ","), "--", name)
	if errors.Is(err, exec.ErrNotFound) {
		return nil, fmt.Errorf("%w: systemctl is not installed", ErrUnsupported)
	}
	if err != nil {
		return nil, fmt.Errorf("systemctl show %s: %w", name, err)
	}
	values := map[string]string{}
	for line := range strings.SplitSeq(string(out), "\n") {
		if k, v, ok := strings.Cut(line, "="); ok {
			values[k] = v
		}
	}
	switch values["LoadState"] {
	case "":
		return nil, fmt.Errorf("systemctl show %s: an answer of another form", name)
	case "not-found":
		return nil, fmt.Errorf("unit %s does not exist on this host", name)
	}
	return values, nil
}

// measureUnit reads the state of the systemd unit name; restarts only for a service, active_since only
// while it is active.
func measureUnit(ctx context.Context, name string) (map[string]any, error) {
	props, err := showUnit(ctx, name, "ActiveState", "SubState", "NRestarts", "ActiveEnterTimestampMonotonic")
	if err != nil {
		return nil, err
	}
	values := map[string]any{"active_state": props["ActiveState"], "sub_state": props["SubState"]}
	if n, err := strconv.Atoi(props["NRestarts"]); err == nil {
		values["restarts"] = n
	}
	if props["ActiveState"] == "active" {
		if since, ok := activeSince(props["ActiveEnterTimestampMonotonic"]); ok {
			values["active_since"] = since
		}
	}
	return values, nil
}

// activeSince turns systemd's monotonic timestamp (µs since boot) into unix seconds. The monotonic
// one is read, not ActiveEnterTimestamp: that one is formatted in a locale and a time zone.
func activeSince(monotonicUS string) (int64, bool) {
	us, err := strconv.ParseInt(monotonicUS, 10, 64)
	if err != nil || us <= 0 {
		return 0, false
	}
	mono, err := monotonicNow()
	if err != nil {
		return 0, false
	}
	ago := mono - time.Duration(us)*time.Microsecond
	return now().Add(-ago).Unix(), true
}

// refuseKernelFile returns an error if f lies in a file system of the kernel: reading a file there can
// change the kernel's state (/proc/kmsg hands out each message once).
func refuseKernelFile(f *os.File, path string) error {
	conn, err := f.SyscallConn()
	if err != nil {
		return fmt.Errorf("the file system of %s cannot be read: %v", path, err)
	}
	var st unix.Statfs_t
	var statErr error
	if err := conn.Control(func(fd uintptr) { statErr = unix.Fstatfs(int(fd), &st) }); err != nil {
		statErr = err
	}
	if statErr != nil {
		return fmt.Errorf("the file system of %s cannot be read: %v", path, statErr)
	}
	switch uint32(st.Type) {
	case unix.PROC_SUPER_MAGIC, unix.SYSFS_MAGIC, unix.DEBUGFS_MAGIC, unix.TRACEFS_MAGIC,
		unix.SECURITYFS_MAGIC, unix.EFIVARFS_MAGIC:
		return fmt.Errorf("%s lies in a file system of the kernel", path)
	}
	return nil
}

// openNoWait opens path to read without waiting: a FIFO swapped in since the stat does not block.
func openNoWait(path string) (*os.File, error) {
	return os.OpenFile(path, os.O_RDONLY|unix.O_NONBLOCK|unix.O_NOCTTY, 0)
}
