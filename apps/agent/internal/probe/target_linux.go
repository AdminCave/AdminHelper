// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package probe

import (
	"context"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"slices"
	"strconv"
	"strings"
)

// readProcFile reads a file under /proc; tests stand in their own.
var readProcFile = os.ReadFile

// unitOwner returns whether a process belongs to the systemd unit name: whether it runs in the
// unit's cgroup or one below it.
func unitOwner(ctx context.Context, name string) (func(pid int32) bool, error) {
	props, err := showUnit(ctx, name, "ControlGroup")
	if err != nil {
		return nil, err
	}
	cg := props["ControlGroup"]
	if cg == "" || cg == "/" {
		return nil, fmt.Errorf("unit %s is not running: it %w", name, errNotListening)
	}
	return func(pid int32) bool {
		return inCgroup(pid, func(path string) bool { return path == cg || strings.HasPrefix(path, cg+"/") })
	}, nil
}

// inCgroup says whether the process pid runs in a cgroup match accepts; a process that cannot be
// read does not.
func inCgroup(pid int32, match func(path string) bool) bool {
	data, err := readProcFile("/proc/" + strconv.Itoa(int(pid)) + "/cgroup")
	return err == nil && cgroupHas(data, match)
}

// containerEndpoint resolves the container target t: on its own network to its address and a port
// it listens on in its network namespace; on the host's network as the host's listeners of the
// container's processes.
func containerEndpoint(ctx context.Context, t Target) (endpoint, error) {
	c, err := inspectContainer(ctx, t.Name)
	if err != nil {
		return endpoint{}, err
	}
	if !c.State.Running || c.State.Pid <= 0 {
		return endpoint{}, fmt.Errorf("container %s is not running: it %w", t.Name, errNotListening)
	}
	mode := c.HostConfig.NetworkMode
	switch {
	case mode == "host":
		if len(c.ID) < 12 {
			return endpoint{}, fmt.Errorf("container %s has no id", t.Name)
		}
		return hostEndpoint(ctx, t, func(l listener) bool {
			return inCgroup(l.pid, func(path string) bool { return strings.Contains(path, c.ID) })
		})
	case mode == "none" || strings.HasPrefix(mode, "container:"):
		return endpoint{}, fmt.Errorf("container %s has no network of its own (%s)", t.Name, mode)
	}
	addrs := c.addrs()
	if len(addrs) == 0 {
		return endpoint{}, fmt.Errorf("container %s has no network address", t.Name)
	}
	list, err := namespaceListeners(c.State.Pid)
	if err != nil {
		return endpoint{}, err
	}
	// A socket on the container's loopback cannot be reached from the host.
	var mine []listener
	for _, l := range list {
		if l.addr.IsUnspecified() || slices.Contains(addrs, l.addr) {
			mine = append(mine, l)
		}
	}
	port, err := pickPort(mine, t)
	if err != nil {
		return endpoint{}, err
	}
	return endpoint{addr: dialAddr(mine, port, addrs), port: port, extra: addrs}, nil
}

// namespaceListeners returns the listening TCP sockets of the network namespace of the process pid.
func namespaceListeners(pid int) ([]listener, error) {
	dir := "/proc/" + strconv.Itoa(pid) + "/net/"
	data, err := readProcFile(dir + "tcp")
	if err != nil {
		return nil, fmt.Errorf("the listening sockets of the container cannot be read: %v", err)
	}
	list := parseProcNetTCP(data)
	// Without IPv6 the kernel has no tcp6 file.
	data, err = readProcFile(dir + "tcp6")
	if err != nil && !errors.Is(err, fs.ErrNotExist) {
		return nil, fmt.Errorf("the listening sockets of the container cannot be read: %v", err)
	}
	return append(list, parseProcNetTCP(data)...), nil
}
