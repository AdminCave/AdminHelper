// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package probe

import (
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"regexp"
	"strconv"
	"strings"

	"golang.org/x/sys/unix"
)

// reopenChecked opens for reading the very file p holds as a path, through /proc/self/fd: a file put
// at its name since p was opened is never opened. O_NONBLOCK fails the open at once where a lease on
// the file would hold it up.
var reopenChecked = func(p *os.File) (*os.File, error) {
	return os.OpenFile("/proc/self/fd/"+strconv.Itoa(int(p.Fd())), os.O_RDONLY|unix.O_NONBLOCK, 0)
}

// openRegular opens the regular file name below root for reading; its errors call it shown. It opens
// name as a path first (O_PATH, to which os.Root adds O_NOFOLLOW), so a FIFO, a device or a link at
// name is never opened for reading, and reads only the file it checked.
func openRegular(root *os.Root, name, shown string) (*os.File, error) {
	p, err := root.OpenFile(name, unix.O_PATH, 0)
	switch {
	case errors.Is(err, fs.ErrNotExist):
		return nil, fmt.Errorf("it holds no %s", shown)
	case err != nil:
		return nil, fmt.Errorf("%s cannot be read: %v", shown, cause(err))
	}
	defer p.Close()
	if fi, err := p.Stat(); err != nil || !fi.Mode().IsRegular() {
		return nil, fmt.Errorf("%s is no regular file", shown)
	}
	if err := refuseKernelFile(p, shown); err != nil {
		return nil, err
	}
	f, err := reopenChecked(p)
	if err != nil {
		return nil, fmt.Errorf("%s cannot be read: %v", shown, cause(err))
	}
	return f, nil
}

// maxCgroupBytes caps /proc/<pid>/cgroup: a line per hierarchy, a few hundred bytes on cgroup v1.
const maxCgroupBytes = 64 << 10

// dockerID is the ID docker and podman give a container.
var dockerID = regexp.MustCompile(`^[0-9a-f]{64}$`)

// openContainerRoot opens the root directory of the process pid of the container id: the cgroup of the
// process must be the container's (cgroupNames).
func openContainerRoot(pid int, id string) (*os.Root, error) {
	if !dockerID.MatchString(id) {
		return nil, errors.New("the container has no ID of the form docker gives it")
	}
	return openProcRoot(pid, func(cgroup []byte) bool { return cgroupNames(cgroup, id) })
}

// openProcRoot opens the root directory of the process pid, /proc/<pid>/root, if belongs says yes to
// its cgroup, /proc/<pid>/cgroup. It reads both through one handle on /proc/<pid>: a process that ended
// since leaves the handle on the old one (ESRCH), its pid given to another never reaches it.
func openProcRoot(pid int, belongs func(cgroup []byte) bool) (*os.Root, error) {
	dir, err := unix.Open("/proc/"+strconv.Itoa(pid), unix.O_PATH|unix.O_DIRECTORY|unix.O_CLOEXEC, 0)
	if err != nil {
		return nil, err
	}
	defer unix.Close(dir)
	fd, err := unix.Openat(dir, "cgroup", unix.O_RDONLY|unix.O_CLOEXEC, 0)
	if err != nil {
		return nil, err
	}
	f := os.NewFile(uintptr(fd), "cgroup")
	data, err := io.ReadAll(io.LimitReader(f, maxCgroupBytes+1))
	_ = f.Close()
	if err != nil {
		return nil, err
	}
	if len(data) > maxCgroupBytes || !belongs(data) {
		return nil, errors.New("its process belongs to the container no longer")
	}
	rfd, err := unix.Openat(dir, "root", unix.O_PATH|unix.O_DIRECTORY|unix.O_CLOEXEC, 0)
	if err != nil {
		return nil, err
	}
	defer unix.Close(rfd)
	return os.OpenRoot("/proc/self/fd/" + strconv.Itoa(rfd))
}

// cgroupNames says whether a cgroup of /proc/<pid>/cgroup (data) is the one of the container id, as
// docker and podman place it: /docker/<id> (cgroupfs driver), /system.slice/docker-<id>.scope (systemd
// driver), /machine.slice/libpod-<id>.scope and /libpod_parent/libpod-<id> (podman), or a cgroup below
// one. The place is fixed from the root on: a subtree delegated to a user, a unit or a guest may hold
// a cgroup of any name, but none of these parents, which only root creates.
func cgroupNames(data []byte, id string) bool {
	places := []string{"/docker/" + id, "/system.slice/docker-" + id + ".scope", "/machine.slice/libpod-" + id + ".scope", "/libpod_parent/libpod-" + id}
	for _, line := range strings.Split(string(data), "\n") {
		parts := strings.SplitN(line, ":", 3)
		if len(parts) != 3 {
			continue
		}
		for _, p := range places {
			if parts[2] == p || strings.HasPrefix(parts[2], p+"/") {
				return true
			}
		}
	}
	return false
}
