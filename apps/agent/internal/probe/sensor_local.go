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
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"github.com/shirou/gopsutil/v4/process"

	"adminhelper-agent/internal/execx"
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
	runTool       = execx.Run
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
