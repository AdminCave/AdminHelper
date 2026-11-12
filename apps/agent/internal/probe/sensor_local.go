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
)

// The seams of the local sensors to the host; tests stand in their own.
var (
	now           = time.Now
	runTool       = allowlist.Run
	findProcesses = processesNamed
	statPath      = os.Stat
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
	for k := range p.Params {
		if k != "path" {
			return "", fmt.Errorf("%w: sensor %s takes no parameter %s", ErrInvalid, p.Sensor, k)
		}
	}
	path, ok := p.Params["path"].(string)
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

// processesNamed returns the processes of this host whose name is name (processKey). A process that
// ends while it is read is left out.
func processesNamed(ctx context.Context, name string) ([]proc, error) {
	all, err := process.ProcessesWithContext(ctx)
	if err != nil {
		return nil, err
	}
	want := processKey(name)
	var procs []proc
	for _, p := range all {
		n, err := p.NameWithContext(ctx)
		if err != nil || processKey(n) != want {
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
		procs = append(procs, proc{rss: mem.RSS, started: time.UnixMilli(created)})
	}
	return procs, ctx.Err()
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
		// docker prints what it found and fails for the rest, a removed container as much as a
		// daemon gone: every container missing from the answer must be gone from docker ps, too.
		if err := goneSince(ctx, ids, list); err != nil {
			return nil, err
		}
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
				pubs = append(pubs, publication{hostIP: hostIP, hostPort: uint16(hostPort), to: uint16(to)})
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
		if n, err := p.NameWithContext(ctx); err == nil && processKey(n) == "dockerd" {
			return true
		}
	}
	return false
}

// certfileSensor reads the first certificate of a PEM file: when it expires, who issued it, whom it
// names. An error never holds what the file holds.
func certfileSensor(ctx context.Context, p Probe, _ string) (map[string]any, error) {
	if err := noTarget(p); err != nil {
		return nil, err
	}
	path, err := pathParam(p)
	if err != nil {
		return nil, err
	}
	data, err := untilDone(ctx, func() ([]byte, error) { return readSmallFile(path, maxCertFileBytes) })
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
// holds. A file that does not exist is no error: exists is false.
func fileAgeSensor(ctx context.Context, p Probe, _ string) (map[string]any, error) {
	if err := noTarget(p); err != nil {
		return nil, err
	}
	path, err := pathParam(p)
	if err != nil {
		return nil, err
	}
	fi, err := untilDone(ctx, func() (fs.FileInfo, error) { return statPath(path) })
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

// readSmallFile reads the regular file path, at most limit bytes. It opens nothing else: opening a
// device can act on it, and opening a FIFO waits for a writer.
func readSmallFile(path string, limit int64) ([]byte, error) {
	fi, err := statPath(path)
	if err != nil {
		return nil, err
	}
	if !fi.Mode().IsRegular() {
		return nil, fmt.Errorf("%s is no regular file", path)
	}
	f, err := openNoWait(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	// The file may have been swapped since the stat.
	if fi, err = f.Stat(); err != nil || !fi.Mode().IsRegular() {
		return nil, fmt.Errorf("%s is no regular file", path)
	}
	if err := refuseKernelFile(f, path); err != nil {
		return nil, err
	}
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
