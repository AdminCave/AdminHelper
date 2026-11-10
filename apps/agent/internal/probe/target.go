// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"bufio"
	"bytes"
	"context"
	"encoding/binary"
	"encoding/hex"
	"errors"
	"fmt"
	"net/netip"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"unicode"
)

// The kinds of target a probe names (Target.Kind).
const (
	kindLoopback  = "loopback"
	kindPort      = "port"
	kindProcess   = "process"
	kindUnit      = "unit"
	kindContainer = "container"
)

// maxNameRunes caps the name of a target, as the monitoring service does.
const maxNameRunes = 255

// containerPattern is a container name or id as docker gives them.
var containerPattern = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9_.-]{0,254}$`)

// errNotListening: the target exists but listens on no TCP port, or it does not run.
var errNotListening = errors.New("listens on no TCP port")

// endpoint is where a probe's target listens: the address and port a sensor connects to, and the
// addresses of the container it belongs to, which the guard lets the sensor reach as well.
type endpoint struct {
	addr  netip.Addr
	port  uint16
	extra []netip.Addr
}

// targetOf returns p's target if its kind is one of kinds and it carries what that kind needs: a port
// hint for loopback and port, a valid name for the others. Else the error wraps ErrInvalid.
func targetOf(p Probe, kinds ...string) (Target, error) {
	if p.Target == nil {
		return Target{}, fmt.Errorf("%w: sensor %s needs a target", ErrInvalid, p.Sensor)
	}
	t := *p.Target
	if !slices.Contains(kinds, t.Kind) {
		return Target{}, fmt.Errorf("%w: sensor %s takes no target of kind %q", ErrInvalid, p.Sensor, t.Kind)
	}
	if t.PortHint < 0 || t.PortHint > 0xffff {
		return Target{}, fmt.Errorf("%w: port hint %d", ErrInvalid, t.PortHint)
	}
	var ok bool
	switch t.Kind {
	case kindLoopback, kindPort:
		ok = t.PortHint > 0
	case kindProcess:
		ok = validProcessName(t.Name)
	case kindUnit:
		ok = unitPattern.MatchString(t.Name)
	case kindContainer:
		ok = containerPattern.MatchString(t.Name)
	}
	if !ok {
		return Target{}, fmt.Errorf("%w: %s target %q", ErrInvalid, t.Kind, t.Name)
	}
	return t, nil
}

// noTarget returns an error wrapping ErrInvalid if p names a target: its sensor names its object in
// the params.
func noTarget(p Probe) error {
	if p.Target != nil {
		return fmt.Errorf("%w: sensor %s takes no target", ErrInvalid, p.Sensor)
	}
	return nil
}

// validProcessName says whether name can be the name of a process: no path, no control character.
func validProcessName(name string) bool {
	if name == "" || len([]rune(name)) > maxNameRunes || strings.ContainsAny(name, `/\`) {
		return false
	}
	return !strings.ContainsFunc(name, unicode.IsControl)
}

// processKey is the form in which two process names are compared: the guard's (blockedProcesses),
// without case and without ".exe".
func processKey(name string) string {
	return strings.TrimSuffix(strings.ToLower(name), ".exe")
}

// resolve returns where t listens on this host. The port is t's port hint if t listens on it, else
// the one port t listens on; several ports without the hint are ErrAmbiguousTarget, none at all
// errNotListening. A loopback target is its port hint on 127.0.0.1, unchecked.
func resolve(ctx context.Context, t Target) (endpoint, error) {
	switch t.Kind {
	case kindLoopback:
		return endpoint{addr: netip.AddrFrom4([4]byte{127, 0, 0, 1}), port: uint16(t.PortHint)}, nil
	case kindPort:
		return hostEndpoint(ctx, t, func(l listener) bool { return l.port == uint16(t.PortHint) })
	case kindProcess:
		return hostEndpoint(ctx, t, ownedBy(ctx, t.Name))
	case kindUnit:
		owns, err := unitOwner(ctx, t.Name)
		if err != nil {
			return endpoint{}, err
		}
		return hostEndpoint(ctx, t, func(l listener) bool { return owns(l.pid) })
	case kindContainer:
		return containerEndpoint(ctx, t)
	}
	return endpoint{}, fmt.Errorf("%w: target kind %q", ErrInvalid, t.Kind)
}

// hostEndpoint resolves t among the listening sockets of this host that match.
func hostEndpoint(ctx context.Context, t Target, match func(listener) bool) (endpoint, error) {
	list, err := currentListeners(ctx)
	if err != nil {
		return endpoint{}, fmt.Errorf("the listening sockets cannot be read: %v", err)
	}
	var mine []listener
	for _, l := range list {
		if match(l) {
			mine = append(mine, l)
		}
	}
	port, err := pickPort(mine, t)
	if err != nil {
		return endpoint{}, err
	}
	return endpoint{addr: dialAddr(mine, port, nil), port: port}, nil
}

// ownedBy matches the listeners of the processes named name. A listener whose process cannot be read
// is not counted as one of them.
func ownedBy(ctx context.Context, name string) func(listener) bool {
	want := processKey(name)
	names := map[int32]string{}
	return func(l listener) bool {
		got, ok := names[l.pid]
		if !ok {
			n, err := processName(ctx, l.pid)
			if err == nil {
				got = processKey(n)
			}
			names[l.pid] = got
		}
		return got != "" && got == want
	}
}

// pickPort returns the port of t among the ports ls listen on: the port hint if it is one of them,
// else the only one.
func pickPort(ls []listener, t Target) (uint16, error) {
	var ports []uint16
	for _, l := range ls {
		if !slices.Contains(ports, l.port) {
			ports = append(ports, l.port)
		}
	}
	switch {
	case t.PortHint > 0 && slices.Contains(ports, uint16(t.PortHint)):
		return uint16(t.PortHint), nil
	case len(ports) == 1:
		return ports[0], nil
	case len(ports) == 0:
		return 0, fmt.Errorf("%s %s %w", t.Kind, targetName(t), errNotListening)
	}
	slices.Sort(ports)
	shown := make([]string, len(ports))
	for i, p := range ports {
		shown[i] = strconv.Itoa(int(p))
	}
	return 0, fmt.Errorf("%w: %s %s listens on ports %s and none is the hint %d", ErrAmbiguousTarget,
		t.Kind, targetName(t), strings.Join(shown, ", "), t.PortHint)
}

// targetName is how an error names t.
func targetName(t Target) string {
	if t.Kind == kindPort {
		return strconv.Itoa(t.PortHint)
	}
	return t.Name
}

// dialAddr returns the address to connect to of those of ls that listen on port: loopback first, a
// listener on the unspecified address counting as loopback; else fallback, if valid, for a listener
// on the unspecified address; else the lowest address.
func dialAddr(ls []listener, port uint16, fallback []netip.Addr) netip.Addr {
	var best netip.Addr
	for _, l := range ls {
		if l.port != port {
			continue
		}
		a := l.addr
		if a.IsUnspecified() {
			if len(fallback) > 0 {
				a = fallback[0]
			} else if a.Is4() {
				a = netip.AddrFrom4([4]byte{127, 0, 0, 1})
			} else {
				a = netip.IPv6Loopback()
			}
		}
		if !best.IsValid() || (a.IsLoopback() && !best.IsLoopback()) ||
			(a.IsLoopback() == best.IsLoopback() && a.Less(best)) {
			best = a
		}
	}
	return best
}

// parseProcNetTCP returns the listening sockets of a /proc/<pid>/net/tcp or tcp6 file, without
// their process. The kernel prints each 32-bit word of an address as the number its bytes make in
// the host's byte order.
func parseProcNetTCP(data []byte) []listener {
	var list []listener
	sc := bufio.NewScanner(bytes.NewReader(data))
	for sc.Scan() {
		f := strings.Fields(sc.Text())
		if len(f) < 4 || f[3] != "0A" {
			continue
		}
		ip, port, ok := strings.Cut(f[1], ":")
		if !ok {
			continue
		}
		raw, err := hex.DecodeString(ip)
		if err != nil || (len(raw) != 4 && len(raw) != 16) {
			continue
		}
		b := make([]byte, 0, len(raw))
		for i := 0; i < len(raw); i += 4 {
			b = binary.NativeEndian.AppendUint32(b, binary.BigEndian.Uint32(raw[i:i+4]))
		}
		addr, _ := netip.AddrFromSlice(b)
		p, err := strconv.ParseUint(port, 16, 16)
		if err != nil {
			continue
		}
		list = append(list, listener{addr: addr.Unmap(), port: uint16(p)})
	}
	return list
}

// parseSockstat reads what `sockstat -46lnq -P tcp` lists on FreeBSD (sockstat(1), releng/14.3): USER
// COMMAND PID FD PROTO LOCAL FOREIGN, one line per descriptor that holds a socket. COMMAND may hold a
// blank, so the columns count from the end. LOCAL is the address and the port apart at the last ":"
// (IPv6 without brackets), "*" the unspecified address of PROTO's family (tcp4, tcp6, tcp46); a PID "?"
// is an owner sockstat could not tell (0, as gopsutil gives it). -l lists each TCP socket without a
// peer, so one bound that does not listen yet counts as a listener: the guard errs on the careful
// side; one without a local port is left out. A line of any other form fails the whole read: a
// listener the guard does not see would let a probe through to a port it refuses.
func parseSockstat(out []byte) ([]listener, error) {
	var list []listener
	for n, line := range strings.Split(string(out), "\n") {
		f := strings.Fields(line)
		if len(f) == 0 {
			continue
		}
		bad := fmt.Errorf("sockstat: line %d has another form", n+1)
		if len(f) < 7 {
			return nil, bad
		}
		pidText, proto, local := f[len(f)-5], f[len(f)-3], f[len(f)-2]
		var pid int32
		if pidText != "?" {
			p, err := strconv.ParseInt(pidText, 10, 32)
			if err != nil || p <= 0 {
				return nil, bad
			}
			pid = int32(p)
		}
		family, ok := strings.CutPrefix(proto, "tcp")
		if !ok {
			family, ok = strings.CutPrefix(proto, "toe") // a socket a TCP offload engine carries
		}
		if !ok || (family != "4" && family != "6" && family != "46") {
			return nil, bad
		}
		i := strings.LastIndexByte(local, ':')
		if i < 0 {
			return nil, bad
		}
		host, portText := local[:i], local[i+1:]
		if portText == "*" {
			continue
		}
		port, err := strconv.ParseUint(portText, 10, 16)
		if err != nil || port == 0 {
			return nil, bad
		}
		var addr netip.Addr
		switch {
		case host == "*" && family == "4":
			addr = netip.IPv4Unspecified()
		case host == "*":
			addr = netip.IPv6Unspecified()
		default:
			if addr, err = netip.ParseAddr(host); err != nil {
				return nil, bad
			}
		}
		list = append(list, listener{addr: addr.Unmap().WithZone(""), port: uint16(port), pid: pid})
	}
	return list, nil
}

// cgroupHas says whether a line of a /proc/<pid>/cgroup file names a cgroup that match accepts.
func cgroupHas(data []byte, match func(path string) bool) bool {
	for line := range strings.SplitSeq(string(data), "\n") {
		parts := strings.SplitN(line, ":", 3)
		if len(parts) == 3 && match(parts[2]) {
			return true
		}
	}
	return false
}

// Cgroups are the cgroups a process runs in: its path in each hierarchy, keyed by the hierarchy
// ("<id>:<controllers>") of its line in /proc/<pid>/cgroup.
type Cgroups map[string]string

// parseCgroups reads a /proc/<pid>/cgroup file.
func parseCgroups(data []byte) Cgroups {
	c := Cgroups{}
	for line := range strings.SplitSeq(string(data), "\n") {
		parts := strings.SplitN(line, ":", 3)
		if len(parts) == 3 {
			c[parts[0]+":"+parts[1]] = parts[2]
		}
	}
	return c
}

// Holds says whether the process that runs in p runs in one of the cgroups c or below it, in a
// hierarchy both name: the processes of a container run in the cgroup of its first one or below it.
// The root holds every process and counts for none; a path that merely names c's, as one a user may
// create in the cgroup delegated to them, does not count either.
func (c Cgroups) Holds(p Cgroups) bool {
	for h, path := range c {
		if path == "" || path == "/" {
			continue
		}
		if q, ok := p[h]; ok && (q == path || strings.HasPrefix(q, path+"/")) {
			return true
		}
	}
	return false
}

// containerInfo holds the fields of `docker inspect` the container sensor and target read (Engine
// API ContainerInspectResponse); Health is nil for a container without a healthcheck.
type containerInfo struct {
	ID           string `json:"Id"`
	RestartCount int
	State        struct {
		Status    string
		Running   bool
		Pid       int
		StartedAt string
		Health    *struct{ Status string }
	}
	HostConfig struct {
		NetworkMode string
	}
	NetworkSettings struct {
		Networks map[string]struct {
			IPAddress         string
			GlobalIPv6Address string
		}
	}
}

// addrs returns the valid addresses of c's networks, IPv4 first.
func (c containerInfo) addrs() []netip.Addr {
	var out []netip.Addr
	for _, n := range c.NetworkSettings.Networks {
		for _, s := range []string{n.IPAddress, n.GlobalIPv6Address} {
			if a, err := netip.ParseAddr(s); err == nil && !slices.Contains(out, a.Unmap()) {
				out = append(out, a.Unmap())
			}
		}
	}
	slices.SortFunc(out, func(a, b netip.Addr) int { return a.Compare(b) })
	return out
}
