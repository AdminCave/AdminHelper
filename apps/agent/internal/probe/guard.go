// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"crypto/tls"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/netip"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	gnet "github.com/shirou/gopsutil/v4/net"
	"github.com/shirou/gopsutil/v4/process"
)

// A probe never measures another host (no LAN probe, R-1223): the guard lets a sensor connect only
// to loopback, to an address of this host or to one of its own containers, and it checks the address
// the connection is actually made to, after any name was resolved. Some services count a failed
// attempt against the host or the address that made it, or act on any bytes they get; the guard
// never connects to them, whatever port they listen on.

// blockedPort reports whether a probe never connects to port: SSH (a failed login can ban the address),
// MySQL (failed connections block the host, max_connect_errors) and raw printing (9100–9107 print
// whatever arrives).
func blockedPort(port uint16) bool {
	return port == 0 || port == 22 || port == 3306 || (port >= 9100 && port <= 9107)
}

// blockedProcesses are the processes, by name, whose TCP listeners a probe never connects to, for the
// same reasons as blockedPort: they serve on other ports too.
var blockedProcesses = map[string]bool{"sshd": true, "mysqld": true, "mariadbd": true}

// hostDaemons are the processes, by name, that control this host or its guests (containers, virtual
// machines, the system bus, its keys): a probe never talks to them, over TCP or a unix socket.
var hostDaemons = map[string]bool{
	"dockerd": true, "containerd": true, "podman": true, "conmon": true, "crio": true, "lxd": true,
	"incusd": true, "libvirtd": true, "snapd": true, "dbus-daemon": true, "dbus-broker": true,
	"polkitd": true, "ssh-agent": true, "gpg-agent": true,
}

// hostDaemonPrefixes start the names of more such processes: the shims of containerd and the
// daemons of libvirt and VirtualBox (virtqemud, virtlogd, VirtualBoxVM …).
var hostDaemonPrefixes = []string{"containerd-shim", "virt"}

// neverProbed says whether name (processKey) is a process a probe never talks to.
func neverProbed(name string) bool {
	k := processKey(name)
	if blockedProcesses[k] || hostDaemons[k] {
		return true
	}
	for _, prefix := range hostDaemonPrefixes {
		if strings.HasPrefix(k, prefix) {
			return true
		}
	}
	return false
}

// listenerTTL is how long one snapshot of the listening sockets serves the guard.
const listenerTTL = 30 * time.Second

// listener is a listening TCP socket of this host and the process it belongs to.
type listener struct {
	addr netip.Addr
	port uint16
	pid  int32
}

// The seams of the guard to the host; tests stand in their own.
var (
	interfaceAddrs = net.InterfaceAddrs
	listeners      = listenTCP
	processName    = nameOf
	processArgs    = argsOf
)

// snapshot is the last list of listeners, shared by every guard of the process.
var snapshot struct {
	sync.Mutex
	at   time.Time
	list []listener
}

// Guard dials for the sensors: only targets of this host, never a blocked port or process.
type Guard struct {
	extra  []netip.Addr
	dialer net.Dialer
}

// NewGuard returns a guard that also lets the sensors connect to extra, the addresses of this host's
// own containers.
func NewGuard(extra ...netip.Addr) *Guard {
	g := &Guard{}
	for _, a := range extra {
		g.extra = append(g.extra, a.Unmap().WithZone(""))
	}
	g.dialer = net.Dialer{ControlContext: g.control}
	return g
}

// DialContext connects to address on network as net.Dialer does, if the guard allows the address
// it connects to; else the error wraps ErrNotAllowed.
func (g *Guard) DialContext(ctx context.Context, network, address string) (net.Conn, error) {
	return g.dialer.DialContext(ctx, network, address)
}

// control runs for each address the dialer connects to, before it connects.
func (g *Guard) control(ctx context.Context, network, address string, _ syscall.RawConn) error {
	switch network {
	case "tcp4", "tcp6", "udp4", "udp6":
	default:
		return fmt.Errorf("%w: network %s", ErrNotAllowed, network)
	}
	ap, err := netip.ParseAddrPort(address)
	if err != nil {
		return fmt.Errorf("%w: %s is no address", ErrNotAllowed, address)
	}
	ip, port := ap.Addr().Unmap(), ap.Port()
	if err := g.ownAddr(ip); err != nil {
		return err
	}
	if blockedPort(port) {
		return fmt.Errorf("%w: port %d is one the agent never probes", ErrNotAllowed, port)
	}
	if network == "tcp4" || network == "tcp6" {
		return checkListener(ctx, ip, port)
	}
	return nil
}

// ownAddr returns an error unless ip is loopback, an address of this host or one of the extra
// addresses.
func (g *Guard) ownAddr(ip netip.Addr) error {
	switch {
	case !ip.IsValid(), ip.IsUnspecified(), ip.IsMulticast(), ip.IsLinkLocalUnicast(), ip.IsLinkLocalMulticast():
		return fmt.Errorf("%w: %s is no address the agent probes", ErrNotAllowed, ip)
	case ip.IsLoopback():
		return nil
	}
	plain := ip.WithZone("")
	for _, a := range g.extra {
		if a == plain {
			return nil
		}
	}
	// Read per dial: an address of this host may come and go.
	addrs, err := interfaceAddrs()
	if err != nil {
		return fmt.Errorf("%w: the addresses of this host cannot be read: %v", ErrNotAllowed, err)
	}
	for _, a := range addrs {
		var own net.IP
		switch x := a.(type) {
		case *net.IPNet:
			own = x.IP
		case *net.IPAddr:
			own = x.IP
		}
		if o, ok := netip.AddrFromSlice(own); ok && o.Unmap() == plain {
			return nil
		}
	}
	return fmt.Errorf("%w: %s is no address of this host", ErrNotAllowed, ip)
}

// checkListener returns an error if a blocked process listens on ip and port, or if that cannot be
// told: a listener on the unspecified address takes connections to every address of the host.
func checkListener(ctx context.Context, ip netip.Addr, port uint16) error {
	list, err := currentListeners(ctx)
	if err != nil {
		return fmt.Errorf("%w: the listening sockets cannot be read: %v", ErrNotAllowed, err)
	}
	for _, l := range list {
		if l.port != port || (l.addr != ip && !l.addr.IsUnspecified()) {
			continue
		}
		name, err := processName(ctx, l.pid)
		if err != nil {
			return fmt.Errorf("%w: the process listening on port %d cannot be read: %v", ErrNotAllowed, port, err)
		}
		if neverProbed(name) {
			return fmt.Errorf("%w: port %d belongs to %s, which the agent never probes", ErrNotAllowed, port, name)
		}
		if processKey(name) == "docker-proxy" {
			if err := checkProxy(ctx, l.pid, port); err != nil {
				return err
			}
		}
	}
	return nil
}

// checkProxy returns an error unless the docker-proxy pid, which listens on port for a container,
// forwards to a port a probe may connect to: a container may publish its SSH or MySQL port on any
// port of the host, and only the proxy's arguments name the container's port.
func checkProxy(ctx context.Context, pid int32, port uint16) error {
	args, err := processArgs(ctx, pid)
	if err != nil {
		return fmt.Errorf("%w: the docker-proxy on port %d cannot be read: %v", ErrNotAllowed, port, err)
	}
	to, ok := proxiedPort(args)
	if !ok {
		return fmt.Errorf("%w: the container port the docker-proxy on port %d forwards to is not told", ErrNotAllowed, port)
	}
	if blockedPort(to) {
		return fmt.Errorf("%w: port %d forwards to port %d of a container, one the agent never probes", ErrNotAllowed, port, to)
	}
	return nil
}

// proxiedPort reads the container port from the arguments of docker-proxy, which dockerd starts with
// -container-port <port> and which reads them with Go's flag package: one or two dashes, the value
// apart or after "=", the last one counts.
func proxiedPort(args []string) (uint16, bool) {
	value, found := "", false
	for i := 1; i < len(args); i++ {
		a := args[i]
		if a == "--" {
			break
		}
		name, v, inline := strings.Cut(strings.TrimPrefix(strings.TrimPrefix(a, "-"), "-"), "=")
		if !strings.HasPrefix(a, "-") || name != "container-port" {
			continue
		}
		if !inline {
			if i+1 >= len(args) {
				return 0, false
			}
			i++
			v = args[i]
		}
		value, found = v, true
	}
	if !found {
		return 0, false
	}
	port, err := strconv.ParseUint(value, 10, 16)
	if err != nil || port == 0 {
		return 0, false
	}
	return uint16(port), true
}

// currentListeners returns the listening TCP sockets of this host, at most listenerTTL old.
func currentListeners(ctx context.Context) ([]listener, error) {
	snapshot.Lock()
	defer snapshot.Unlock()
	if snapshot.list != nil && time.Since(snapshot.at) < listenerTTL {
		return snapshot.list, nil
	}
	list, err := listeners(ctx)
	if err != nil {
		return nil, err
	}
	if list == nil {
		list = []listener{}
	}
	snapshot.list, snapshot.at = list, time.Now()
	return list, nil
}

// listenTCP reads the listening TCP sockets of this host.
func listenTCP(ctx context.Context) ([]listener, error) {
	conns, err := gnet.ConnectionsWithContext(ctx, "tcp")
	if err != nil {
		return nil, err
	}
	var list []listener
	for _, c := range conns {
		if c.Status != "LISTEN" || c.Laddr.Port > 0xffff {
			continue
		}
		addr, err := netip.ParseAddr(c.Laddr.IP)
		if err != nil {
			continue
		}
		list = append(list, listener{addr: addr.Unmap().WithZone(""), port: uint16(c.Laddr.Port), pid: c.Pid})
	}
	return list, nil
}

// nameOf returns the name of the process pid; an unknown owner (pid 0) is an error.
func nameOf(ctx context.Context, pid int32) (string, error) {
	if pid <= 0 {
		return "", errors.New("the owner is unknown")
	}
	p, err := process.NewProcessWithContext(ctx, pid)
	if err != nil {
		return "", err
	}
	return p.NameWithContext(ctx)
}

// argsOf returns the arguments of the process pid, its name first.
func argsOf(ctx context.Context, pid int32) ([]string, error) {
	if pid <= 0 {
		return nil, errors.New("the owner is unknown")
	}
	p, err := process.NewProcessWithContext(ctx, pid)
	if err != nil {
		return nil, err
	}
	return p.CmdlineSliceWithContext(ctx)
}

const (
	// maxBodyBytes caps what a sensor reads of an HTTP response.
	maxBodyBytes = 1 << 20
	// maxHeaderBytes caps the header of an HTTP response.
	maxHeaderBytes = 64 << 10
	// maxRedirects is as many redirects as an HTTP sensor follows.
	maxRedirects = 5
)

// errBodyTooLarge is the error of a read beyond maxBodyBytes.
var errBodyTooLarge = fmt.Errorf("the response is larger than %d bytes", maxBodyBytes)

// HTTPClient returns the HTTP client of the sensors: it dials through g, uses no proxy, keeps no
// connection, sends only GET and HEAD, follows a redirect only to the same scheme, host and port,
// and reads at most maxBodyBytes of a body.
func (g *Guard) HTTPClient(tlsConf *tls.Config) *http.Client {
	return httpClient(g.DialContext, tlsConf)
}

// httpClient is the client of HTTPClient, dialing with dial.
func httpClient(dial func(ctx context.Context, network, addr string) (net.Conn, error), tlsConf *tls.Config) *http.Client {
	base := &http.Transport{
		Proxy:                  nil,
		DialContext:            dial,
		TLSClientConfig:        tlsConf,
		DisableKeepAlives:      true,
		MaxResponseHeaderBytes: maxHeaderBytes,
	}
	return &http.Client{Transport: readOnly{base}, CheckRedirect: sameTarget}
}

// readOnly sends only requests that change nothing and caps the bodies of their responses.
type readOnly struct{ base http.RoundTripper }

func (t readOnly) RoundTrip(req *http.Request) (*http.Response, error) {
	if req.Method != "" && req.Method != http.MethodGet && req.Method != http.MethodHead {
		if req.Body != nil {
			_ = req.Body.Close()
		}
		return nil, fmt.Errorf("%w: method %s", ErrInvalid, req.Method)
	}
	resp, err := t.base.RoundTrip(req)
	if err != nil {
		return nil, err
	}
	resp.Body = &cappedBody{rc: resp.Body, left: maxBodyBytes}
	return resp, nil
}

// cappedBody returns errBodyTooLarge once more than left bytes were read.
type cappedBody struct {
	rc   io.ReadCloser
	left int64
	over bool
}

func (b *cappedBody) Read(p []byte) (int, error) {
	if b.over {
		return 0, errBodyTooLarge
	}
	// One byte beyond the cap tells a body of exactly the cap from a larger one.
	if int64(len(p)) > b.left+1 {
		p = p[:b.left+1]
	}
	n, err := b.rc.Read(p)
	if int64(n) > b.left {
		n, b.left, b.over = int(b.left), 0, true
		return n, errBodyTooLarge
	}
	b.left -= int64(n)
	return n, err
}

func (b *cappedBody) Close() error { return b.rc.Close() }

// sameTarget lets a redirect through only to the scheme, host and port of the first request.
func sameTarget(req *http.Request, via []*http.Request) error {
	if len(via) >= maxRedirects {
		return fmt.Errorf("%w: more than %d redirects", ErrNotAllowed, maxRedirects)
	}
	first := via[0].URL
	if !strings.EqualFold(req.URL.Scheme, first.Scheme) || !strings.EqualFold(req.URL.Hostname(), first.Hostname()) ||
		effectivePort(req.URL) != effectivePort(first) {
		return fmt.Errorf("%w: a redirect to another target", ErrNotAllowed)
	}
	return nil
}

// effectivePort is the port u connects to.
func effectivePort(u *url.URL) string {
	if p := u.Port(); p != "" {
		return p
	}
	switch strings.ToLower(u.Scheme) {
	case "https":
		return "443"
	case "http":
		return "80"
	}
	return ""
}
