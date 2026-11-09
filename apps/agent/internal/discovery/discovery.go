// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Package discovery finds out what runs on this host for the monitoring service, which matches it
// against its catalog: the service units, the listening TCP sockets with their process or container,
// the containers, the markers of the catalog's modules and the protocols of the ports beyond loopback.
// It reports metadata alone (names, ports, states), never config contents, command lines or
// environment, and runs in a frame of its own.
package discovery

import (
	"cmp"
	"context"
	"encoding/json"
	"errors"
	"net/netip"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"slices"
	"strconv"
	"strings"
	"sync"
	"time"
	"unicode/utf8"

	"adminhelper-agent/internal/execx"
	"adminhelper-agent/internal/logging"
	"adminhelper-agent/internal/probe"
)

var logger = logging.For("discovery")

const (
	// frame bounds a whole discovery; partTimeout each of its parts but the port recognition, which
	// takes what is left of the frame; toolTimeout every tool call.
	frame       = 60 * time.Second
	toolTimeout = 10 * time.Second
	// portTimeout bounds the recognition of one port; portWorkers ports are recognized at once.
	portTimeout = 10 * time.Second
	portWorkers = 4
)

// The caps of the contract the monitoring service holds the block to. A list cut at its cap makes the
// discovery partial: what fell off must not look gone. The entries of one container are cut silently,
// as the monitoring service does.
const (
	maxUnits          = 1000
	maxSockets        = 1000
	maxContainers     = 500
	maxMarkers        = 1000
	maxPorts          = 1000
	maxContainerPorts = 64
	maxMounts         = 32
	maxMarkerPaths    = 16
	maxMarkerPackages = 16
	maxPathLen        = 1024
	// The longest texts of the contract, in characters: a name, a state, a container id and image.
	maxNameLen  = 255
	maxStateLen = 64
	maxIDLen    = 128
	maxImageLen = 512
	// packageBatch is how many packages one call of a package tool asks for.
	packageBatch = 200
)

// Seams for the tests.
var (
	// linuxHost says whether the units, containers and markers of this host can be read: on Linux alone.
	linuxHost     = runtime.GOOS == "linux"
	runTool       = execx.Run
	statPath      = os.Stat
	listSockets   = probe.Listeners
	processName   = probe.ProcessName
	recognizePort = probe.RecognizePort
	partTimeout   = 20 * time.Second
)

// systemdDir exists on a host booted with systemd (sd_booted).
const systemdDir = "/run/systemd/system"

var (
	markerIDPattern = regexp.MustCompile(`^[a-z0-9][a-z0-9_.-]{0,127}$`)
	packagePattern  = regexp.MustCompile(`^[a-z0-9][a-z0-9+._-]{0,127}$`)
)

// Inventory is the report's discovery block.
type Inventory struct {
	TS         int64           `json:"ts"`
	DurationMS int64           `json:"duration_ms"`
	Partial    bool            `json:"partial"`
	Units      []Unit          `json:"units"`
	Sockets    []Socket        `json:"sockets"`
	Containers []Container     `json:"containers"`
	Markers    map[string]bool `json:"markers"`
	Ports      []Port          `json:"ports"`
}

// Unit is a service unit of systemd: its name, active and sub state.
type Unit struct {
	Name  string `json:"name"`
	State string `json:"state"`
	Sub   string `json:"sub"`
}

// Socket is a listening TCP socket: the process it belongs to and the container, if one runs it.
type Socket struct {
	Proto     string `json:"proto"`
	Addr      string `json:"addr"`
	Port      uint16 `json:"port"`
	Process   string `json:"process"`
	Container string `json:"container"`
}

// Container is a docker container in any state; pid is the process it started with, 0 if it is not
// running.
type Container struct {
	ID             string          `json:"id"`
	Name           string          `json:"name"`
	Image          string          `json:"image"`
	ComposeProject string          `json:"compose_project"`
	ComposeService string          `json:"compose_service"`
	State          string          `json:"state"`
	Health         string          `json:"health"`
	Ports          []ContainerPort `json:"ports"`
	Mounts         []string        `json:"mounts"`
	pid            int32
}

// ContainerPort is a port of a container and the host port it is published on (nil: none).
type ContainerPort struct {
	Private uint16  `json:"private"`
	Public  *uint16 `json:"public"`
	Proto   string  `json:"proto"`
}

// Port is a port beyond loopback and the protocol the service on it speaks.
type Port struct {
	Port     uint16 `json:"port"`
	Proto    string `json:"proto"`
	Protocol string `json:"protocol"`
}

// Run discovers this host within ctx, in a frame of at most frame: the units, the containers, the
// listening sockets, the markers, then the protocols of the ports beyond loopback. A part that a tool
// failed or that the time cut short makes the inventory partial; a tool that is not installed does
// not, its part is empty.
func Run(ctx context.Context, markers []probe.Marker) Inventory {
	began := time.Now()
	ctx, cancel := context.WithTimeout(ctx, frame)
	defer cancel()
	inv := Inventory{TS: began.Unix()}
	whole := true
	part := func(do func(context.Context) bool) {
		ctx, cancel := context.WithTimeout(ctx, partTimeout)
		defer cancel()
		if !do(ctx) || ctx.Err() != nil {
			whole = false
		}
	}
	part(func(ctx context.Context) (ok bool) { inv.Units, ok = collectUnits(ctx); return })
	part(func(ctx context.Context) (ok bool) { inv.Containers, ok = collectContainers(ctx); return })
	part(func(ctx context.Context) (ok bool) { inv.Sockets, ok = collectSockets(ctx, inv.Containers); return })
	part(func(ctx context.Context) (ok bool) { inv.Markers, ok = checkMarkers(ctx, markers); return })
	var portsWhole bool
	inv.Ports, portsWhole = recognizePorts(ctx, inv.Sockets)
	inv.Partial = !whole || !portsWhole || ctx.Err() != nil
	inv.DurationMS = time.Since(began).Milliseconds()
	return inv
}

// collectUnits lists the service units systemd has loaded, in any state.
func collectUnits(ctx context.Context) ([]Unit, bool) {
	if !linuxHost {
		return []Unit{}, true
	}
	if _, err := statPath(systemdDir); err != nil {
		return []Unit{}, true
	}
	out, err := runTool(ctx, toolTimeout, "systemctl", "list-units", "--type=service", "--all", "--full",
		"--no-legend", "--plain", "--no-pager")
	if errors.Is(err, exec.ErrNotFound) {
		return []Unit{}, true
	}
	if err != nil {
		return []Unit{}, false
	}
	units := parseUnits(out)
	if len(units) > maxUnits {
		return units[:maxUnits], false
	}
	return units, true
}

// parseUnits reads what systemctl list-units lists: UNIT LOAD ACTIVE SUB DESCRIPTION, a unit per line.
// A unit that is not found is only named by another, not installed; one whose name the contract
// cannot carry is left out.
func parseUnits(out []byte) []Unit {
	units := []Unit{}
	for line := range strings.SplitSeq(string(out), "\n") {
		f := strings.Fields(line)
		if len(f) < 4 || f[1] == "not-found" {
			continue
		}
		u := Unit{Name: contractText(f[0], maxNameLen), State: contractText(f[2], maxStateLen),
			Sub: contractText(f[3], maxStateLen)}
		if u.Name != "" {
			units = append(units, u)
		}
	}
	return units
}

// contractText is s if the contract can carry it, else "": at most limit characters, no control
// character. The monitoring service holds the block to the same rule; a cut name would be another
// name.
func contractText(s string, limit int) string {
	if utf8.RuneCountInString(s) > limit || strings.ContainsFunc(s, func(r rune) bool { return r < 0x20 || r == 0x7f }) {
		return ""
	}
	return s
}

// inspected holds the fields of `docker inspect` the discovery reads (Engine API
// ContainerInspectResponse); Health is nil for a container without a healthcheck, a port's bindings
// null for one that is not published.
type inspected struct {
	ID     string `json:"Id"`
	Name   string
	Config struct {
		Image  string
		Labels map[string]string
	}
	State struct {
		Status string
		Pid    int32
		Health *struct{ Status string }
	}
	NetworkSettings struct {
		Ports map[string][]struct{ HostPort string }
	}
	Mounts []struct{ Destination string }
}

// collectContainers lists the docker containers of this host in any state; one whose name the
// contract cannot carry is left out.
func collectContainers(ctx context.Context) ([]Container, bool) {
	if !linuxHost {
		return []Container{}, true
	}
	out, err := runTool(ctx, toolTimeout, "docker", "ps", "--all", "--quiet", "--no-trunc")
	if errors.Is(err, exec.ErrNotFound) {
		return []Container{}, true
	}
	if err != nil {
		return []Container{}, false
	}
	ids := strings.Fields(string(out))
	if len(ids) == 0 {
		return []Container{}, true
	}
	whole := true
	if len(ids) > maxContainers {
		ids, whole = ids[:maxContainers], false
	}
	out, err = runTool(ctx, toolTimeout, "docker", append([]string{"inspect", "--type", "container"}, ids...)...)
	// A container removed between ps and inspect makes inspect fail; it still prints the others. Which
	// of both made it fail is not told, so the discovery is partial either way.
	var raw []inspected
	if jerr := json.Unmarshal(out, &raw); jerr != nil {
		return []Container{}, false
	}
	containers := make([]Container, 0, len(raw))
	for _, c := range raw {
		if c := toContainer(c); c.Name != "" {
			containers = append(containers, c)
		}
	}
	slices.SortFunc(containers, func(a, b Container) int { return strings.Compare(a.Name, b.Name) })
	return containers, whole && err == nil
}

// toContainer is the contract's form of c: its name without the leading slash, the compose labels,
// its ports and the paths it mounts something at; a text the contract cannot carry is "", a mount
// path left out.
func toContainer(c inspected) Container {
	health := ""
	if c.State.Health != nil {
		health = c.State.Health.Status
	}
	mounts := []string{}
	for _, m := range c.Mounts {
		if d := contractText(m.Destination, maxPathLen); d != "" && !slices.Contains(mounts, d) {
			mounts = append(mounts, d)
		}
	}
	slices.Sort(mounts)
	return Container{
		ID:             contractText(c.ID, maxIDLen),
		Name:           contractText(strings.TrimPrefix(c.Name, "/"), maxNameLen),
		Image:          contractText(c.Config.Image, maxImageLen),
		ComposeProject: contractText(c.Config.Labels["com.docker.compose.project"], maxNameLen),
		ComposeService: contractText(c.Config.Labels["com.docker.compose.service"], maxNameLen),
		State:          contractText(c.State.Status, maxStateLen),
		Health:         contractText(health, maxStateLen),
		Ports:          containerPorts(c.NetworkSettings.Ports),
		Mounts:         mounts[:min(len(mounts), maxMounts)],
		pid:            c.State.Pid,
	}
}

// containerPorts reads a container's port map, keyed <port>/<protocol>: a port per host port it is
// published on (the same host port on IPv4 and IPv6 once), else unpublished.
func containerPorts(m map[string][]struct{ HostPort string }) []ContainerPort {
	type key struct {
		private, public uint16
		proto           string
	}
	seen := map[key]bool{}
	ports := []ContainerPort{}
	add := func(k key) {
		if seen[k] {
			return
		}
		seen[k] = true
		p := ContainerPort{Private: k.private, Proto: k.proto}
		if k.public != 0 {
			public := k.public
			p.Public = &public
		}
		ports = append(ports, p)
	}
	for spec, bindings := range m {
		portText, proto, _ := strings.Cut(spec, "/")
		private, err := strconv.ParseUint(portText, 10, 16)
		if err != nil || private == 0 || proto == "" {
			continue
		}
		published := false
		for _, b := range bindings {
			if public, err := strconv.ParseUint(b.HostPort, 10, 16); err == nil && public != 0 {
				add(key{uint16(private), uint16(public), proto})
				published = true
			}
		}
		if !published {
			add(key{uint16(private), 0, proto})
		}
	}
	slices.SortFunc(ports, func(a, b ContainerPort) int {
		pa, pb := uint16(0), uint16(0)
		if a.Public != nil {
			pa = *a.Public
		}
		if b.Public != nil {
			pb = *b.Public
		}
		return cmp.Or(cmp.Compare(a.Private, b.Private), strings.Compare(a.Proto, b.Proto), cmp.Compare(pa, pb))
	})
	return ports[:min(len(ports), maxContainerPorts)]
}

// collectSockets lists the listening TCP sockets of this host with their process and the container
// that runs it: one on the host's network by its cgroup, the cgroup of the container's first process
// or one below it, a published port by the docker-proxy that listens for it. A process name the
// contract cannot carry is "".
func collectSockets(ctx context.Context, containers []Container) ([]Socket, bool) {
	list, err := listSockets(ctx)
	if err != nil {
		return []Socket{}, false
	}
	published := map[uint16]string{}
	var running []string
	groups := map[string]probe.Cgroups{}
	for _, c := range containers {
		for _, p := range c.Ports {
			if p.Public != nil && p.Proto == "tcp" {
				published[*p.Public] = c.Name
			}
		}
		if c.State == "running" && c.pid > 0 {
			running = append(running, c.Name)
			groups[c.Name] = cgroupsOf(c.pid)
		}
	}
	names := map[int32]string{}
	inside := map[int32]string{}
	seen := map[Socket]bool{}
	sockets := []Socket{}
	for _, l := range list {
		name, ok := names[l.PID]
		if !ok {
			name = contractText(processName(ctx, l.PID), maxNameLen)
			names[l.PID] = name
		}
		s := Socket{Proto: "tcp", Addr: l.Addr.String(), Port: l.Port, Process: name}
		if l.Addr.Is6() {
			s.Proto = "tcp6"
		}
		switch {
		case name == "docker-proxy":
			s.Container = published[l.Port]
		case l.PID > 0 && len(running) > 0:
			in, ok := inside[l.PID]
			if !ok {
				own := cgroupsOf(l.PID)
				if i := slices.IndexFunc(running, func(c string) bool { return groups[c].Holds(own) }); i >= 0 {
					in = running[i]
				}
				inside[l.PID] = in
			}
			s.Container = in
		}
		if !seen[s] {
			seen[s] = true
			sockets = append(sockets, s)
		}
	}
	slices.SortFunc(sockets, func(a, b Socket) int {
		return cmp.Or(cmp.Compare(a.Port, b.Port), strings.Compare(a.Proto, b.Proto), strings.Compare(a.Addr, b.Addr),
			strings.Compare(a.Process, b.Process), strings.Compare(a.Container, b.Container))
	})
	if len(sockets) > maxSockets {
		return sockets[:maxSockets], false
	}
	return sockets, true
}

// checkMarkers says of each valid marker whether its module is installed: one of its paths exists or
// one of its packages is installed. A marker the time or a failed tool left undecided is left out.
func checkMarkers(ctx context.Context, markers []probe.Marker) (map[string]bool, bool) {
	found := map[string]bool{}
	valid := validMarkers(markers)
	if !linuxHost || len(valid) == 0 {
		return found, true
	}
	var paths, packages []string
	for _, m := range valid {
		paths = append(paths, m.Paths...)
		packages = append(packages, m.Packages...)
	}
	slices.Sort(paths)
	slices.Sort(packages)
	// The packages first: their tools end with their timeout, a stat that hangs only with ctx.
	installed, packagesWhole := installedPackages(ctx, slices.Compact(packages))
	present, pathsWhole := presentPaths(ctx, slices.Compact(paths))
	for _, m := range valid {
		switch {
		case slices.ContainsFunc(m.Paths, func(p string) bool { return present[p] }),
			slices.ContainsFunc(m.Packages, func(p string) bool { return installed[p] }):
			found[m.ID] = true
		case pathsWhole && packagesWhole:
			found[m.ID] = false
		}
	}
	return found, pathsWhole && packagesWhole
}

// validMarkers returns the markers the agent checks: an id of the contract, seen first, at most
// maxMarkerPaths absolute, clean paths and maxMarkerPackages package names. The others are left out.
func validMarkers(markers []probe.Marker) []probe.Marker {
	valid := []probe.Marker{}
	seen := map[string]bool{}
	left := 0
	for _, m := range markers {
		ok := markerIDPattern.MatchString(m.ID) && !seen[m.ID] && len(valid) < maxMarkers &&
			len(m.Paths) <= maxMarkerPaths && len(m.Packages) <= maxMarkerPackages &&
			!slices.ContainsFunc(m.Paths, func(p string) bool { return !cleanPath(p) }) &&
			!slices.ContainsFunc(m.Packages, func(p string) bool { return !packagePattern.MatchString(p) })
		if !ok {
			left++
			continue
		}
		seen[m.ID] = true
		valid = append(valid, m)
	}
	if left > 0 {
		logger.Warnf("discovery: %d markers left out (an unusable or repeated id, path or package)", left)
	}
	return valid
}

// cleanPath says whether p is an absolute path in its shortest form, without NUL.
func cleanPath(p string) bool {
	return len(p) <= maxPathLen && strings.HasPrefix(p, "/") && filepath.Clean(p) == p && !strings.ContainsRune(p, 0)
}

// presentPaths returns which of paths exist and whether it got to check all of them. A stat that
// hangs (a network file system that went away) is left behind when ctx ends.
func presentPaths(ctx context.Context, paths []string) (map[string]bool, bool) {
	type result struct {
		path string
		ok   bool
	}
	results := make(chan result, len(paths))
	stat := statPath // the goroutine may outlive the call
	go func() {
		for _, p := range paths {
			if ctx.Err() != nil {
				return
			}
			_, err := stat(p)
			results <- result{p, err == nil}
		}
	}()
	present := map[string]bool{}
	for range paths {
		select {
		case r := <-results:
			if r.ok {
				present[r.path] = true
			}
		case <-ctx.Done():
			return present, false
		}
	}
	return present, true
}

// installedPackages returns which of names dpkg or rpm, whichever this host has, count as installed,
// and whether every call answered.
func installedPackages(ctx context.Context, names []string) (map[string]bool, bool) {
	installed := map[string]bool{}
	whole := true
	for batch := range slices.Chunk(names, packageBatch) {
		// dpkg-query exits 1 if a package is not known, 2 on a fatal error (dpkg-query(1)).
		out, err := runTool(ctx, toolTimeout, "dpkg-query", append([]string{"--show",
			`--showformat=${Package}\t${db:Status-Abbrev}\n`, "--"}, batch...)...)
		if errors.Is(err, exec.ErrNotFound) {
			break
		}
		var exitErr *exec.ExitError
		if err != nil && !(errors.As(err, &exitErr) && exitErr.ExitCode() == 1) {
			whole = false
		}
		for name := range dpkgInstalled(out) {
			installed[name] = true
		}
	}
	for batch := range slices.Chunk(names, packageBatch) {
		// rpm -q exits non-zero if a package is not installed; its answer tells which are. A name begins
		// with a letter or digit (packagePattern), so rpm reads none as an option.
		out, err := runTool(ctx, toolTimeout, "rpm", append([]string{"--query", `--queryformat=%{NAME}\n`}, batch...)...)
		if errors.Is(err, exec.ErrNotFound) {
			break
		}
		var exitErr *exec.ExitError
		if err != nil && !errors.As(err, &exitErr) {
			whole = false
		}
		for line := range strings.SplitSeq(string(out), "\n") {
			if slices.Contains(batch, line) {
				installed[line] = true
			}
		}
	}
	return installed, whole
}

// dpkgInstalled reads the answer of dpkg-query, a package and its status abbreviation per line, and
// returns the packages whose status is installed (the second letter i).
func dpkgInstalled(out []byte) map[string]bool {
	installed := map[string]bool{}
	for line := range strings.SplitSeq(string(out), "\n") {
		name, status, ok := strings.Cut(line, "\t")
		if ok && len(status) >= 2 && status[1] == 'i' {
			installed[name] = true
		}
	}
	return installed
}

// recognizePorts recognizes the protocol of every port listened on beyond loopback, but those the
// agent never probes, portWorkers at once, each in at most portTimeout, in what is left of ctx. A port
// it cannot connect to or that the guard refuses is left out. It says whether ctx left time for all.
func recognizePorts(ctx context.Context, sockets []Socket) ([]Port, bool) {
	ports := candidates(sockets)
	whole := true
	if len(ports) > maxPorts {
		ports, whole = ports[:maxPorts], false
	}
	protocols := make([]string, len(ports))
	next := make(chan int)
	var wg sync.WaitGroup
	for range min(portWorkers, len(ports)) {
		wg.Go(func() {
			for i := range next {
				pctx, cancel := context.WithTimeout(ctx, portTimeout)
				if name, err := recognizePort(pctx, ports[i]); err == nil {
					protocols[i] = name
				}
				cancel()
			}
		})
	}
feed:
	for i := range ports {
		select {
		case next <- i:
		case <-ctx.Done():
			break feed
		}
	}
	close(next)
	wg.Wait()
	found := []Port{}
	for i, port := range ports {
		if protocols[i] != "" {
			found = append(found, Port{Port: port, Proto: "tcp", Protocol: protocols[i]})
		}
	}
	return found, whole && ctx.Err() == nil
}

// candidates are the ports listened on beyond loopback, in order, without one the agent never connects
// to or one a socket of a process it never probes listens on.
func candidates(sockets []Socket) []uint16 {
	never := map[uint16]bool{}
	for _, s := range sockets {
		if probe.NeverProbed(s.Port, s.Process) {
			never[s.Port] = true
		}
	}
	var ports []uint16
	for _, s := range sockets {
		if never[s.Port] || slices.Contains(ports, s.Port) {
			continue
		}
		if addr, err := netip.ParseAddr(s.Addr); err == nil && !addr.IsLoopback() {
			ports = append(ports, s.Port)
		}
	}
	slices.Sort(ports)
	return ports
}
