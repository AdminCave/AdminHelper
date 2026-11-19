// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"bytes"
	"context"
	"crypto/x509"
	"encoding/json"
	"encoding/pem"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"math"
	"net"
	"net/netip"
	"os"
	"os/exec"
	pathpkg "path"
	"path/filepath"
	"runtime"
	"slices"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/shirou/gopsutil/v4/process"

	"adminhelper-agent/internal/allowlist"
)

// The local sensors read this host's own state: a unit, a process, a listening socket, a container,
// a certificate file, a file's age. None of them connects anywhere, and none sends what it read
// beyond its fields.
func init() {
	sensors["unit"] = unitSensor
	sensors["process"] = processSensor
	sensors["socket"] = socketSensor
	sensors["container"] = containerSensor
	sensors["certfile"] = certfileSensor
	sensors["file_age"] = fileAgeSensor
}

const (
	// toolTimeout caps one call of an external tool; the probe's own timeout may end it sooner.
	toolTimeout = 10 * time.Second
	// maxPathBytes caps the path of a file sensor, as the monitoring service does.
	maxPathBytes = 1024
	// maxCertFileBytes caps what the certfile sensor reads.
	maxCertFileBytes = 1 << 20
	// maxDirEntries caps the entries file_age reads in a directory (newest_in): a spool of millions
	// of files would cost the host a long scan every interval.
	maxDirEntries = 10000
)

// The seams of the local sensors to the host; tests stand in their own.
var (
	now           = time.Now
	runTool       = allowlist.Run
	findProcesses = processesNamed
	statPath      = os.Stat
	openFile      = openChecked
)

// noParams returns an error wrapping ErrInvalid if p has params: its sensor takes none.
func noParams(p Probe) error {
	if len(p.Params) == 0 {
		return nil
	}
	keys := make([]string, 0, len(p.Params))
	for k := range p.Params {
		keys = append(keys, k)
	}
	slices.Sort(keys)
	return fmt.Errorf("%w: sensor %s takes no parameter, got %s", ErrInvalid, p.Sensor, strings.Join(keys, ", "))
}

// pathParam returns p's one parameter path, an absolute path on this host. What follows its leading
// "/" must be a local path (filepath.IsLocal): no second separator, no "..", on Windows no colon and no
// device name. So it never names a share of another host (//host/share), a pipe or a device.
func pathParam(p Probe) (string, error) {
	return pathParamNamed(p, "path")
}

// pathParamNamed is pathParam for the one parameter key.
func pathParamNamed(p Probe, key string) (string, error) {
	for k := range p.Params {
		if k != key {
			return "", fmt.Errorf("%w: sensor %s takes no parameter %s", ErrInvalid, p.Sensor, k)
		}
	}
	path, ok := p.Params[key].(string)
	if !ok || !validLocalPath(path) {
		return "", fmt.Errorf("%w: sensor %s needs an absolute local path of at most %d bytes", ErrInvalid, p.Sensor, maxPathBytes)
	}
	return path, nil
}

// validLocalPath says whether path is an absolute path of at most maxPathBytes on a local disk of
// this host.
func validLocalPath(path string) bool {
	return strings.HasPrefix(path, "/") && len(path) <= maxPathBytes && !strings.ContainsRune(path, 0) &&
		filepath.IsLocal(path[1:])
}

// unitSensor reads the state of a systemd unit (Linux), an rc.d service (FreeBSD) or a Windows service
// (measureUnit).
func unitSensor(ctx context.Context, p Probe, _ string) (map[string]any, error) {
	t, err := targetOf(p, kindUnit)
	if err != nil {
		return nil, err
	}
	if err := noParams(p); err != nil {
		return nil, err
	}
	return measureUnit(ctx, t.Name)
}

// proc is what the process sensor reads of one process.
type proc struct {
	pid     int32
	rss     uint64
	started time.Time
}

// processSensor counts the processes of a name, their resident memory and how long the oldest one
// runs. No process of the name is a count of 0, not an error.
func processSensor(ctx context.Context, p Probe, _ string) (map[string]any, error) {
	t, err := targetOf(p, kindProcess)
	if err != nil {
		return nil, err
	}
	if err := noParams(p); err != nil {
		return nil, err
	}
	procs, err := findProcesses(ctx, t.Name)
	if err != nil {
		return nil, fmt.Errorf("the processes cannot be read: %v", err)
	}
	values := map[string]any{"count": len(procs)}
	if len(procs) == 0 {
		return values, nil
	}
	var rss uint64
	oldest := procs[0].started
	for _, pr := range procs {
		rss += pr.rss
		if pr.started.Before(oldest) {
			oldest = pr.started
		}
	}
	values["rss_bytes"] = rss
	values["uptime_s"] = int64(now().Sub(oldest) / time.Second)
	return values, nil
}

// processesNamed returns the processes of this host named name (processKey, by namedAs). A process
// that ends while it is read is left out.
func processesNamed(ctx context.Context, name string) ([]proc, error) {
	all, err := process.ProcessesWithContext(ctx)
	if err != nil {
		return nil, err
	}
	want := processKey(name)
	var procs []proc
	for _, p := range all {
		n, err := p.NameWithContext(ctx)
		if err != nil || !namedAs(ctx, p.Pid, n, want) {
			continue
		}
		mem, err := p.MemoryInfoWithContext(ctx)
		if err != nil {
			continue
		}
		created, err := p.CreateTimeWithContext(ctx)
		if err != nil {
			continue
		}
		procs = append(procs, proc{pid: p.Pid, rss: mem.RSS, started: time.UnixMilli(created)})
	}
	return procs, ctx.Err()
}

// namedAs says whether the process pid, whose name is name, is named want (processKey) as ownedBy
// sees it: one of multicallBinaries by the applet it runs, one whose applet cannot be told by none.
func namedAs(ctx context.Context, pid int32, name, want string) bool {
	if !isMulticall(processKey(name)) {
		return processKey(name) == want
	}
	applet, err := programName(ctx, pid)
	return err == nil && processKey(applet) == want
}

// socketSensor says whether the target listens on a TCP port, and on which (resolve).
func socketSensor(ctx context.Context, p Probe, _ string) (map[string]any, error) {
	t, err := targetOf(p, kindPort, kindProcess, kindContainer, kindUnit)
	if err != nil {
		return nil, err
	}
	if err := noParams(p); err != nil {
		return nil, err
	}
	ep, err := resolve(ctx, t)
	if errors.Is(err, errNotListening) {
		return map[string]any{"listening": false}, nil
	}
	if err != nil {
		return nil, err
	}
	return map[string]any{"listening": true, "port": int(ep.port)}, nil
}

// containerSensor reads the state, health and restarts of a container. A container without a
// healthcheck has the health "none", as docker calls it.
func containerSensor(ctx context.Context, p Probe, _ string) (map[string]any, error) {
	t, err := targetOf(p, kindContainer)
	if err != nil {
		return nil, err
	}
	if err := noParams(p); err != nil {
		return nil, err
	}
	c, err := inspectContainer(ctx, t.Name)
	if err != nil {
		return nil, err
	}
	values := map[string]any{"state": c.State.Status, "restarts": c.RestartCount, "health": "none"}
	if c.State.Health != nil && c.State.Health.Status != "" {
		values["health"] = c.State.Health.Status
	}
	if started, err := time.Parse(time.RFC3339Nano, c.State.StartedAt); err == nil && c.State.Running {
		values["started_at"] = started.Unix()
	}
	return values, nil
}

// inspectContainer reads the container name with `docker inspect`; without docker the sensor is
// unsupported on this host.
func inspectContainer(ctx context.Context, name string) (containerInfo, error) {
	out, err := runTool(ctx, toolTimeout, "docker", "inspect", "--type", "container", "--", name)
	var exitErr *exec.ExitError
	switch {
	case errors.Is(err, exec.ErrNotFound):
		return containerInfo{}, fmt.Errorf("%w: docker is not installed", ErrUnsupported)
	case errors.As(err, &exitErr) && bytes.Equal(bytes.TrimSpace(out), []byte("[]")):
		return containerInfo{}, fmt.Errorf("no container %s on this host", name)
	case err != nil:
		return containerInfo{}, fmt.Errorf("docker inspect %s: %w", name, err)
	}
	var list []containerInfo
	if err := json.Unmarshal(out, &list); err != nil || len(list) != 1 {
		return containerInfo{}, fmt.Errorf("docker inspect %s: an answer of another form", name)
	}
	return list[0], nil
}

// publication is a TCP port of this host that docker forwards to a port of a running container.
type publication struct {
	// hostIP is the address docker forwards; invalid or unspecified for every address.
	hostIP   netip.Addr
	hostPort uint16
	to       uint16
	// pid is the container's main process: its network namespace holds the socket on port to.
	pid int32
}

// dockerSocket is where the docker daemon takes the CLI's calls by default.
var dockerSocket = "/var/run/docker.sock"

// dockerPublications returns the published TCP ports of the running containers. A host without a
// docker daemon serving its socket has none; with one, every answer of docker must be read, even
// without the CLI on the agent's PATH. Only docker on Linux forwards a port without a process
// listening on it; Docker Desktop always listens with its own.
func dockerPublications(ctx context.Context) ([]publication, error) {
	if runtime.GOOS != "linux" {
		return nil, nil
	}
	ids, err := dockerContainers(ctx)
	if err != nil {
		if !dockerServes(ctx) {
			return nil, nil
		}
		return nil, err
	}
	if len(ids) == 0 {
		return nil, nil
	}
	list, err := inspectContainers(ctx, ids)
	if err != nil {
		return nil, err
	}
	var pubs []publication
	for _, c := range list {
		if !c.State.Running {
			continue
		}
		for key, binds := range c.NetworkSettings.Ports {
			num, proto, _ := strings.Cut(key, "/")
			if proto != "tcp" {
				continue
			}
			to, err := strconv.ParseUint(num, 10, 16)
			if err != nil {
				return nil, fmt.Errorf("docker inspect: container port %q of another form", key)
			}
			for _, b := range binds {
				hostPort, err := strconv.ParseUint(b.HostPort, 10, 16)
				if err != nil {
					return nil, fmt.Errorf("docker inspect: host port %q of another form", b.HostPort)
				}
				var hostIP netip.Addr
				if b.HostIP != "" {
					if hostIP, err = netip.ParseAddr(b.HostIP); err != nil {
						return nil, fmt.Errorf("docker inspect: host address %q of another form", b.HostIP)
					}
					hostIP = hostIP.Unmap().WithZone("")
				}
				pubs = append(pubs, publication{hostIP: hostIP, hostPort: uint16(hostPort), to: uint16(to), pid: int32(c.State.Pid)})
			}
		}
	}
	return pubs, nil
}

// dockerContainers returns the IDs of every container docker knows.
func dockerContainers(ctx context.Context) ([]string, error) {
	out, err := runTool(ctx, toolTimeout, "docker", "ps", "--all", "--quiet", "--no-trunc")
	if err != nil {
		return nil, fmt.Errorf("docker ps: %w", err)
	}
	return strings.Fields(string(out)), nil
}

// goneSince returns an error unless every container of ids that list lacks is gone from docker.
func goneSince(ctx context.Context, ids []string, list []containerInfo) error {
	got := make(map[string]bool, len(list))
	for _, c := range list {
		got[c.ID] = true
	}
	var missing []string
	for _, id := range ids {
		if !got[id] {
			missing = append(missing, id)
		}
	}
	if len(missing) == 0 {
		return nil
	}
	now, err := dockerContainers(ctx)
	if err != nil {
		return err
	}
	for _, id := range missing {
		if slices.Contains(now, id) {
			return fmt.Errorf("docker inspect: container %s left out of the answer", id)
		}
	}
	return nil
}

// dockerSocketServes says whether a docker daemon may serve this host: false only when its socket
// does not exist or nobody accepts on it, and no dockerd runs (a daemon on another socket, rootless
// or by its own -H, publishes ports as much).
func dockerSocketServes(ctx context.Context) bool {
	var d net.Dialer
	conn, err := d.DialContext(ctx, "unix", dockerSocket)
	if err == nil {
		_ = conn.Close()
		return true
	}
	if !errors.Is(err, syscall.ENOENT) && !errors.Is(err, syscall.ECONNREFUSED) {
		return true
	}
	return dockerdRunning(ctx)
}

// dockerdRuns says whether a process dockerd runs on this host; a process list that cannot be read
// counts as one running.
func dockerdRuns(ctx context.Context) bool {
	all, err := process.ProcessesWithContext(ctx)
	if err != nil {
		return true
	}
	for _, p := range all {
		if n, err := p.NameWithContext(ctx); err == nil && namedAs(ctx, p.Pid, n, "dockerd") {
			return true
		}
	}
	return false
}

// containerPath reads the parameter key of p, a path inside the container p targets, and maps it to
// the bind or volume mount that holds it (containerInfo.hostPath): the mount's source on this host and
// the path relative to it. The sensor then reads below the source through an os.Root, so a link in the
// container's files never leads to a file of the host outside the mount. No error names the host path;
// a path on no such mount is invalid and named in no error either.
func containerPath(ctx context.Context, p Probe, key string) (source, rel, path string, err error) {
	t, err := targetOf(p, kindContainer)
	if err != nil {
		return "", "", "", err
	}
	if path, err = pathParamNamed(p, key); err != nil {
		return "", "", "", err
	}
	// The path is mapped by its prefix: a ".." in it would leave the mount it names.
	if path != pathpkg.Clean(path) {
		return "", "", "", fmt.Errorf("%w: sensor %s needs a clean path inside the container", ErrInvalid, p.Sensor)
	}
	info, err := inspectContainer(ctx, t.Name)
	if err != nil {
		return "", "", "", err
	}
	source, rel, ok := info.hostPath(path)
	if !ok {
		return "", "", "", fmt.Errorf("%w: no bind or volume mount of container %s holds the path", ErrInvalid, t.Name)
	}
	return source, rel, path, nil
}

// openMount opens the mount source of a container path as a root and gives the path below it; its error
// names neither the source nor the path. docker inspect names a source as it was given, a link among
// them, which docker resolved when it mounted it: so does openMount. A bind of a single file (a
// certificate handed to the container) is opened through the directory that holds the resolved file,
// with the file as the path, and only while it is a regular one: a link there would be followed within
// that host directory, beyond what the bind holds.
func openMount(source, rel string) (*os.Root, string, error) {
	if rel == "." {
		if fi, err := os.Stat(source); err == nil && !fi.IsDir() {
			real, err := filepath.EvalSymlinks(source)
			if err != nil {
				return nil, "", fmt.Errorf("the mount of the container cannot be opened: %v", cause(err))
			}
			if fi, err := os.Lstat(real); err != nil || !fi.Mode().IsRegular() {
				return nil, "", errors.New("the mount of the container is no directory nor regular file")
			}
			source, rel = filepath.Dir(real), filepath.Base(real)
		}
	}
	root, err := os.OpenRoot(source)
	if err != nil {
		return nil, "", fmt.Errorf("the mount of the container cannot be opened: %v", cause(err))
	}
	return root, rel, nil
}

// maxLinks caps the links followLinks follows, as Linux does (MAXSYMLINKS).
const maxLinks = 40

// followLinks follows the links at name below root to the file they point at, which openRegular then
// opens (a link put there since is followed within root alone, like the root's own lookups). A relative
// link is followed within root alone, as certbot's live/ links into archive/; an absolute one names a
// path of the container, which may lie on another mount, and is refused. Its errors call name shown.
func followLinks(root *os.Root, name, shown string) (string, error) {
	for range maxLinks {
		fi, err := root.Lstat(name)
		if err != nil || fi.Mode()&fs.ModeSymlink == 0 {
			return name, nil // openRegular tells what is wrong with name
		}
		target, err := root.Readlink(name)
		if err != nil {
			return "", fmt.Errorf("%s cannot be read: %v", shown, cause(err))
		}
		if strings.HasPrefix(target, "/") {
			return "", fmt.Errorf("%s is a link to an absolute path", shown)
		}
		name = pathpkg.Join(pathpkg.Dir(name), target)
	}
	return "", fmt.Errorf("%s is a link of more than %d links", shown, maxLinks)
}

// certfileSensor reads the first certificate of a PEM file: when it expires, who issued it, whom it
// names. With a target container the path is one inside that container (containerPath). An error never
// holds what the file holds.
func certfileSensor(ctx context.Context, p Probe, _ string) (map[string]any, error) {
	var path string
	var read func() ([]byte, error)
	if p.Target == nil {
		var err error
		if path, err = pathParam(p); err != nil {
			return nil, err
		}
		read = func() ([]byte, error) { return readSmallFile(path, maxCertFileBytes) }
	} else {
		source, rel, cpath, err := containerPath(ctx, p, "path")
		if err != nil {
			return nil, err
		}
		path = cpath
		read = func() ([]byte, error) {
			root, rel, err := openMount(source, rel)
			if err != nil {
				return nil, err
			}
			defer root.Close()
			name, err := followLinks(root, rel, path)
			if err != nil {
				return nil, err
			}
			f, err := openRegular(root, name, path)
			if err != nil {
				return nil, err
			}
			defer f.Close()
			return readLimited(f, path, maxCertFileBytes)
		}
	}
	data, err := untilDone(ctx, read)
	if err != nil {
		return nil, err
	}
	for {
		var block *pem.Block
		block, data = pem.Decode(data)
		if block == nil {
			return nil, fmt.Errorf("%s holds no PEM certificate", path)
		}
		if block.Type != "CERTIFICATE" {
			continue
		}
		cert, err := x509.ParseCertificate(block.Bytes)
		if err != nil {
			return nil, fmt.Errorf("the first certificate of %s cannot be parsed", path)
		}
		return map[string]any{
			"not_after": cert.NotAfter.Unix(),
			"days_left": int64(math.Floor(cert.NotAfter.Sub(now()).Hours() / 24)),
			"issuer":    cert.Issuer.String(),
			"subject":   cert.Subject.String(),
		}, nil
	}
}

// fileAgeSensor reads whether a file exists, how long ago it was changed and its size, never what it
// holds. A file that does not exist is no error: exists is false. With newest_in instead of path it
// reads the newest regular file of a directory (newestIn), never its name. With a target container the
// path is one inside that container (containerPath).
func fileAgeSensor(ctx context.Context, p Probe, _ string) (map[string]any, error) {
	key := "path"
	if _, ok := p.Params["newest_in"]; ok {
		key = "newest_in"
	}
	var stat func() (fs.FileInfo, error)
	if p.Target == nil {
		path, err := pathParamNamed(p, key)
		if err != nil {
			return nil, err
		}
		stat = func() (fs.FileInfo, error) { return statPath(path) }
		if key == "newest_in" {
			stat = func() (fs.FileInfo, error) { return newestIn(path) }
		}
	} else {
		source, rel, path, err := containerPath(ctx, p, key)
		if err != nil {
			return nil, err
		}
		stat = func() (fs.FileInfo, error) {
			root, rel, err := openMount(source, rel)
			if err != nil {
				return nil, err
			}
			defer root.Close()
			if key == "newest_in" {
				return newestInRoot(root, rel, path)
			}
			fi, err := root.Stat(rel)
			if err != nil && !errors.Is(err, fs.ErrNotExist) {
				return nil, fmt.Errorf("%s cannot be read: %v", path, cause(err))
			}
			return fi, err
		}
	}
	fi, err := untilDone(ctx, stat)
	if errors.Is(err, fs.ErrNotExist) {
		return map[string]any{"exists": false}, nil
	}
	if err != nil {
		return nil, err
	}
	return map[string]any{
		"exists":     true,
		"age_s":      int64(now().Sub(fi.ModTime()) / time.Second),
		"size_bytes": fi.Size(),
	}, nil
}

// newestIn returns the newest regular file directly in the directory dir, fs.ErrNotExist for a
// directory without one. It reads no file and follows no link: an entry's own type and times
// (lstat) decide. openDir opens a directory and nothing else, so a FIFO put at dir is never waited on.
func newestIn(dir string) (fs.FileInfo, error) {
	d, err := openDir(nil, dir)
	if errors.Is(err, errNotDir) {
		return nil, fmt.Errorf("%s is %w", dir, errNotDir)
	}
	if err != nil {
		return nil, err
	}
	defer d.Close()
	return newestOf(d, dir, fs.DirEntry.Info)
}

// newestInRoot is newestIn for the directory name below root, which dir names in errors. A link at name
// or in an entry is followed within root alone (os.Root): one out of it is an error.
func newestInRoot(root *os.Root, name, dir string) (fs.FileInfo, error) {
	// OpenRoot tells a file that is no directory by an error of no type of its own: Stat tells it first.
	fi, err := root.Stat(name)
	switch {
	case errors.Is(err, fs.ErrNotExist):
		return nil, fs.ErrNotExist
	case err != nil:
		return nil, fmt.Errorf("%s cannot be read: %v", dir, cause(err))
	case !fi.IsDir():
		return nil, fmt.Errorf("%s is %w", dir, errNotDir)
	}
	sub, err := root.OpenRoot(name)
	if err != nil {
		return nil, fmt.Errorf("%s cannot be read: %v", dir, cause(err))
	}
	defer sub.Close()
	// OpenRoot opened name as a directory, so "." is one: no FIFO is waited on.
	d, err := sub.Open(".")
	if err != nil {
		return nil, fmt.Errorf("%s cannot be read: %v", dir, cause(err))
	}
	defer d.Close()
	return newestOf(d, dir, func(e fs.DirEntry) (fs.FileInfo, error) { return sub.Lstat(e.Name()) })
}

// newestOf returns the newest regular file directly in the open directory d, which dir names in errors;
// info reads an entry's own type and times without following a link.
func newestOf(d *os.File, dir string, info func(fs.DirEntry) (fs.FileInfo, error)) (fs.FileInfo, error) {
	if err := refuseKernelFile(d, dir); err != nil {
		return nil, err
	}
	entries, err := d.ReadDir(maxDirEntries + 1)
	if err != nil && !errors.Is(err, io.EOF) {
		return nil, fmt.Errorf("%s cannot be listed: %v", dir, cause(err))
	}
	if len(entries) > maxDirEntries {
		return nil, fmt.Errorf("%s holds more than %d entries", dir, maxDirEntries)
	}
	var newest fs.FileInfo
	for _, e := range entries {
		if !e.Type().IsRegular() {
			continue
		}
		fi, err := info(e)
		if errors.Is(err, fs.ErrNotExist) {
			continue // removed since the directory was read
		}
		if err != nil {
			// The error of lstat quotes the entry, and newest_in never names a file.
			return nil, fmt.Errorf("an entry of %s cannot be read", dir)
		}
		if !fi.Mode().IsRegular() {
			continue // replaced since the directory was read
		}
		if newest == nil || fi.ModTime().After(newest.ModTime()) {
			newest = fi
		}
	}
	if newest == nil {
		return nil, fs.ErrNotExist
	}
	return newest, nil
}

// errNoRegularFile is what checkRegular returns for a file that is not regular.
var errNoRegularFile = errors.New("is no regular file")

// checkRegular returns an error unless f is a regular file outside the file systems of the kernel; its
// errors call it path.
func checkRegular(f *os.File, path string) error {
	if fi, err := f.Stat(); err != nil || !fi.Mode().IsRegular() {
		return fmt.Errorf("%s %w", path, errNoRegularFile)
	}
	return refuseKernelFile(f, path)
}

// readSmallFile reads the regular file path, at most limit bytes. It opens nothing else (openChecked):
// opening a device can act on it, and opening a FIFO waits for a writer.
func readSmallFile(path string, limit int64) ([]byte, error) {
	f, err := openFile(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	return readLimited(f, path, limit)
}

// readLimited reads f to its end, at most limit bytes; its errors call it path.
func readLimited(f *os.File, path string, limit int64) ([]byte, error) {
	data, err := io.ReadAll(io.LimitReader(f, limit+1))
	if err != nil {
		return nil, err
	}
	if int64(len(data)) > limit {
		return nil, fmt.Errorf("%s is larger than %d bytes", path, limit)
	}
	return data, nil
}

// untilDone runs f and returns its result, or ctx's error once ctx ends first. A file system that hangs
// (an NFS server gone, a FUSE daemon stuck) holds f beyond the probe's timeout; f's goroutine then
// ends with the agent.
func untilDone[T any](ctx context.Context, f func() (T, error)) (T, error) {
	type result struct {
		v   T
		err error
	}
	done := make(chan result, 1)
	go func() {
		v, err := f()
		done <- result{v, err}
	}()
	select {
	case r := <-done:
		return r.v, r.err
	case <-ctx.Done():
		var zero T
		return zero, ctx.Err()
	}
}
