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
	"io/fs"
	"net"
	"net/http"
	"net/netip"
	"net/url"
	"os"
	"path"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

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
// machines and the processes that run them, the system bus, its keys): a probe never talks to them,
// over TCP or a unix socket.
var hostDaemons = map[string]bool{
	"dockerd": true, "containerd": true, "podman": true, "conmon": true, "crio": true, "lxd": true,
	"incusd": true, "libvirtd": true, "snapd": true, "dbus-daemon": true, "dbus-broker": true,
	"polkitd": true, "ssh-agent": true, "gpg-agent": true, "kvm": true, "firecracker": true, "crosvm": true,
	"xenconsoled": true, "xenstored": true, "kubelet": true, "buildkitd": true, "pmgdaemon": true, "pmgproxy": true,
}

// hostDaemonPrefixes start the names of more such processes: the shims of containerd, the daemons
// of libvirt and VirtualBox (virtqemud, virtlogd, VirtualBoxVM, VBoxHeadless, VBoxSVC …), QEMU, which
// runs a virtual machine and serves its monitor and consoles (qemu-system-x86, qemu-kvm; Proxmox names
// it kvm), Cloud Hypervisor (the kernel cuts the name to cloud-hyperviso), k3s and the API and console
// daemons of Proxmox VE with their workers (pvedaemon worker, pveproxy worker, spiceproxy) and of
// Proxmox Backup Server (proxmox-backup-api, proxmox-backup-proxy).
var hostDaemonPrefixes = []string{"containerd-shim", "virt", "vbox", "qemu", "cloud-hyperv", "k3s", "pvedaemon",
	"pveproxy", "spiceproxy", "proxmox-backup"}

// forwarders start the names of the processes that forward a port of this host to a port they do
// not name to the guard: rootless container networks (rootlesskit, Podman's rootlessport, slirp4netns,
// pasta and passt, whose binaries may carry a suffix such as .avx2, gvproxy, vpnkit), kube-proxy,
// kubectl (port-forward), autossh, socat, systemd-socket-proxyd (the kernel cuts the name to
// systemd-socket-), sslh with sslh-ev and sslh-select, rinetd, redir, stunnel (Debian names it
// stunnel4), 6tunnel, spiped, chisel, gost, ncat, the netcat variants (nc.openbsd, nc.traditional,
// netcat), frpc (a visitor listens here for a remote service) and frps (a tcp proxy hands its port to
// the far end of a tunnel), cloudflared (access tcp), the AWS session-manager-plugin (the kernel cuts
// the name to session-manager), wstunnel, boundary (connect), ghostunnel, rathole, and on Windows
// PuTTY, plink and KiTTY (-L) and the WSL2 relay (wslrelay, before it wslhost);
// forwarderNames are matched whole, since a prefix would take other programs too: ssh also sshd and
// ssh-agent, nc also ncurses tools, tsh (Teleport) also tshark. A probe never connects to a port or a
// socket one of them serves, since what lies behind it cannot be checked.
var forwarders = []string{"rootlesskit", "rootlessport", "slirp4netns", "pasta", "passt", "gvproxy", "vpnkit",
	"kube-proxy", "kubectl", "autossh", "socat", "systemd-socket-", "sslh", "rinetd", "redir", "stunnel",
	"6tunnel", "spiped", "chisel", "gost", "ncat", "nc.", "netcat", "frpc", "frps", "cloudflared",
	"session-manager", "wstunnel", "boundary", "ghostunnel", "rathole", "putty", "plink", "kitty", "wslrelay",
	"wslhost"}

var forwarderNames = []string{"ssh", "nc", "tsh"}

// activators names the processes that hold a listening socket for a service they start per
// connection, by processKey: systemd (socket activation), xinetd, inetd and the tcpserver of
// ucspi-tcp; superServers start the names of s6's s6-tcpserver4, s6-tcpserver6 and s6-tcpserverd.
var activators = []string{"systemd", "xinetd", "inetd", "tcpserver"}

var superServers = []string{"s6-tcpserver"}

// activator says whether k (processKey) is one of activators or superServers.
func activator(k string) bool {
	if slices.Contains(activators, k) {
		return true
	}
	for _, prefix := range superServers {
		if strings.HasPrefix(k, prefix) {
			return true
		}
	}
	return false
}

// forwarder says whether name (processKey, or the base of an argv[0]) is one of forwarders.
func forwarder(name string) bool {
	k := processKey(name)
	if slices.Contains(forwarderNames, k) {
		return true
	}
	for _, prefix := range forwarders {
		if strings.HasPrefix(k, prefix) {
			return true
		}
	}
	return false
}

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

// controlSockets are where the services that control this host, its guests and its sessions keep
// their unix sockets: a probe never connects to a socket at or below one of them, whichever process
// serves it (neverProbedSocket). A path that ends in a slash is a directory, one that ends in a hyphen
// starts the names of such directories (ssh-agent makes /tmp/ssh-XXXXXX). OPNsense's configd runs the
// actions it reads there as root; it is a python process, which no name of hostDaemons catches.
var controlSockets = []string{
	"/run/docker.sock", "/run/docker/", "/run/containerd/", "/run/podman/", "/run/crio/", "/run/cri-dockerd.sock",
	"/run/k3s/", "/run/buildkit/", "/run/lxc/", "/run/libvirt/", "/run/qemu-server/", "/run/lxd/", "/run/incus/", "/run/snapd.socket",
	"/run/snapd-snap.socket", "/run/dbus/", "/run/systemd/", "/run/udev/", "/run/user/", "/run/xen/", "/run/xenstored/",
	"/var/lib/docker/", "/var/lib/containerd/", "/var/lib/kubelet/", "/var/lib/libvirt/", "/var/lib/lxd/", "/var/lib/incus/", "/var/snap/lxd/",
	"/tmp/.X11-unix/", "/tmp/ssh-", "/run/configd.socket",
}

// neverProbedSocket says whether path (clean and absolute) is at or below one of controlSockets;
// /var/run is the /run of older systems and of FreeBSD.
func neverProbedSocket(path string) bool {
	if rest, ok := strings.CutPrefix(path, "/var/run/"); ok {
		path = "/run/" + rest
	}
	for _, c := range controlSockets {
		prefix := strings.HasSuffix(c, "/") || strings.HasSuffix(c, "-")
		if path == c || prefix && strings.HasPrefix(path, c) {
			return true
		}
	}
	return false
}

// socketToDial returns the path to connect to for the unix socket path: path with its links resolved.
// A path at or below one of controlSockets, as given or resolved, is ErrNotAllowed; one that does not
// exist is errNoListener, and a second name of a single socket of controlSockets is ErrNotAllowed.
// Dialing the resolved path means a final link swapped after the check leads nowhere new; a directory
// on the path swapped for a link still could, so checkPeerName in dialUnix stays behind it.
func socketToDial(path string) (string, error) {
	if neverProbedSocket(path) {
		return "", fmt.Errorf("%w: %s is a socket of a service the agent never probes", ErrNotAllowed, path)
	}
	real, err := filepath.EvalSymlinks(path)
	if errors.Is(err, fs.ErrNotExist) {
		return "", errNoListener
	}
	if err != nil {
		return "", fmt.Errorf("%w: the links of %s cannot be resolved: %v", ErrNotAllowed, path, err)
	}
	if neverProbedSocket(real) {
		return "", fmt.Errorf("%w: %s leads to %s, a socket of a service the agent never probes", ErrNotAllowed, path, real)
	}
	if c, err := controlSocketFile(real); errors.Is(err, fs.ErrNotExist) {
		return "", errNoListener
	} else if err != nil {
		return "", fmt.Errorf("%w: %s cannot be read: %v", ErrNotAllowed, real, err)
	} else if c != "" {
		return "", fmt.Errorf("%w: %s is %s under another name, a socket of a service the agent never probes", ErrNotAllowed, path, c)
	}
	return real, nil
}

// controlSocketFile returns the entry of controlSockets that names the same file as path, a second
// name (hard link) of one socket of a control service, or "": neverProbedSocket sees names, not
// files. Only the entries naming one socket are compared, under /run and /var/run; a link to a
// socket inside a directory of controlSockets is left to checkPeerName.
func controlSocketFile(path string) (string, error) {
	fi, err := os.Stat(path)
	if err != nil {
		return "", err
	}
	for _, c := range controlSockets {
		if strings.HasSuffix(c, "/") || strings.HasSuffix(c, "-") {
			continue
		}
		names := []string{c}
		if rest, ok := strings.CutPrefix(c, "/run/"); ok {
			names = append(names, "/var/run/"+rest)
		}
		for _, name := range names {
			if ci, err := os.Stat(name); err == nil && os.SameFile(fi, ci) {
				return name, nil
			}
		}
	}
	return "", nil
}

// checkPeerName refuses the socket path unless name, the address its server bound (getpeername
// on the connection), is absolute and outside controlSockets. It names the socket the connection
// reached, whichever directory or link led there after socketToDial; a relative or abstract name
// says nothing about where that socket is, so it is refused. name is slash-separated on every
// platform, so package path judges it, not filepath.
func checkPeerName(name, sock string) error {
	if !path.IsAbs(name) {
		return fmt.Errorf("%w: the server of %s bound no absolute path (%q)", ErrNotAllowed, sock, name)
	}
	if neverProbedSocket(path.Clean(name)) {
		return fmt.Errorf("%w: %s reached %s, a socket of a service the agent never probes", ErrNotAllowed, sock, name)
	}
	return nil
}

// listenerTTL is how long one snapshot of the listening sockets serves the guard.
const listenerTTL = 30 * time.Second

// listenerFresh is how old a snapshot may be to tell that nobody listens on a port: a service may
// have started since the last one.
const listenerFresh = time.Second

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
	peerSocket     = osPeerSocket
	// serviceForwarder names the service of the process pid if that service forwards the ports it
	// listens on (Windows portproxy), else "".
	serviceForwarder = osServiceForwarder
	publishedPorts   = dockerPublications
	// containerListeners returns the processes that listen on a TCP port in the network namespace
	// of a container's main process.
	containerListeners = namespaceProcesses
	dockerServes       = dockerSocketServes
	dockerdRunning     = dockerdRuns
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
	// secret marks a guard for connections that carry a secret (secretGuard); owns is the rule of
	// its target, nil for none.
	secret bool
	owns   func() func(listener) bool
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

// secretGuard returns a guard for a connection that carries a secret to ep: it judges on a snapshot
// at most listenerFresh old, and only a listener of ep's rule (endpoint.owns) may take the
// connection, never a port docker forwards.
func secretGuard(ep endpoint) *Guard {
	g := NewGuard(ep.extra...)
	g.secret, g.owns = true, ep.owns
	return g
}

// maxAge is how old a snapshot g judges on may be.
func (g *Guard) maxAge() time.Duration {
	if g.secret {
		return listenerFresh
	}
	return listenerTTL
}

// DialContext connects to address on network as net.Dialer does, if the guard allows the address
// it connects to; else the error wraps ErrNotAllowed.
func (g *Guard) DialContext(ctx context.Context, network, address string) (net.Conn, error) {
	conn, err := g.dialer.DialContext(ctx, network, address)
	if err != nil {
		return nil, err
	}
	tc, ok := conn.(*net.TCPConn)
	if !ok {
		return conn, nil
	}
	server := tc.RemoteAddr().(*net.TCPAddr).AddrPort()
	client := tc.LocalAddr().(*net.TCPAddr).AddrPort()
	if err := g.checkTaker(ctx, server, client); err != nil {
		// Reset rather than close: the service behind a redirect sees no orderly end of a session.
		_ = tc.SetLinger(0)
		_ = tc.Close()
		return nil, err
	}
	return conn, nil
}

// peerState is what took a connection, as the host tells it.
type peerState int

const (
	peerNone         peerState = iota // no socket of this host has the connection's ends
	peerListener                      // only the listener on the port answers, no socket of the connection
	peerConnected                     // the socket that took the connection has its exact ends
	peerListenerFull                  // only the listener answers, and its accept queue is full
)

// errPeerUnsupported: the host cannot tell which socket took a connection.
var errPeerUnsupported = errors.New("the socket that took a connection cannot be told on this system")

// peerTries and peerWait bound the wait for the kernel to list the socket that took the connection.
const (
	peerTries = 3
	peerWait  = 10 * time.Millisecond
)

// redirectTTL is how long the guard refuses a port, before it connects, after a redirect took a
// connection to it: the reset comes after the connect, and a service behind the redirect may count
// each such connection against the agent's address (max_connect_errors, fail2ban).
const redirectTTL = time.Hour

// redirected holds the ports a redirect took a connection to, with the time it was told; shared by
// every guard of the process.
var redirected struct {
	sync.Mutex
	at map[netip.AddrPort]time.Time
}

// rememberRedirect records that a redirect took a connection to server.
func rememberRedirect(server netip.AddrPort) {
	redirected.Lock()
	defer redirected.Unlock()
	now := time.Now()
	for k, at := range redirected.at {
		if now.Sub(at) >= redirectTTL {
			delete(redirected.at, k)
		}
	}
	if redirected.at == nil {
		redirected.at = map[netip.AddrPort]time.Time{}
	}
	redirected.at[server] = now
}

// checkRedirected returns an error if a redirect took a connection to ip:port within redirectTTL.
func checkRedirected(ip netip.Addr, port uint16) error {
	redirected.Lock()
	defer redirected.Unlock()
	if at, ok := redirected.at[netip.AddrPortFrom(ip, port)]; ok && time.Since(at) < redirectTTL {
		return fmt.Errorf("%w: the connection to port %d was taken by another socket than the one listening there", ErrNotAllowed, port)
	}
	return nil
}

// checkTaker returns an error unless the connection from client to server was taken by a socket
// bound to server itself: a NAT redirect hands it to another port or host, which the guard never
// checked before the connect. A container's address and a port docker publishes are left out, their
// sockets live in another network namespace.
func (g *Guard) checkTaker(ctx context.Context, server, client netip.AddrPort) error {
	ip := server.Addr().Unmap()
	if g.contained(ip) {
		return nil
	}
	if published, err := checkPublished(ctx, ip, server.Port(), g.maxAge()); err != nil || published {
		return err
	}
	for try := 1; ; try++ {
		state, err := peerSocket(server, client)
		switch {
		case errors.Is(err, errPeerUnsupported):
			return nil
		case err != nil:
			return fmt.Errorf("%w: the socket that took the connection to port %d cannot be told: %v", ErrNotAllowed, server.Port(), err)
		case state == peerConnected:
			return nil
		case try == peerTries:
			return takenElsewhere(ip, server, client, state)
		}
		select {
		case <-ctx.Done():
			return fmt.Errorf("%w: %v", ErrNotAllowed, ctx.Err())
		case <-time.After(peerWait):
		}
	}
}

// takenElsewhere judges a connection no socket of the port took, after the last try. A listener
// with a full accept queue drops the connection its handshake completed, and a service that resets
// the connection at once leaves no socket of it either; the guard's own socket then is gone too.
// Neither is a redirect: the probe is refused, the port is not remembered.
func takenElsewhere(ip netip.Addr, server, client netip.AddrPort, state peerState) error {
	if state == peerListenerFull {
		return fmt.Errorf("%w: the listen queue of port %d is full, the socket that took the connection cannot be told", ErrNotAllowed, server.Port())
	}
	own, err := peerSocket(client, server)
	switch {
	case err != nil:
		return fmt.Errorf("%w: the socket that took the connection to port %d cannot be told: %v", ErrNotAllowed, server.Port(), err)
	case own != peerConnected:
		return fmt.Errorf("%w: the connection to port %d ended before the agent could tell which socket took it", ErrNotAllowed, server.Port())
	}
	rememberRedirect(netip.AddrPortFrom(ip, server.Port()))
	return checkRedirected(ip, server.Port())
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
		if err := checkRedirected(ip, port); err != nil {
			return err
		}
		if g.secret {
			return checkOwner(ctx, ip, port, g.contained(ip), g.owns)
		}
		return checkListener(ctx, ip, port, g.contained(ip))
	}
	return nil
}

// checkOwner is checkListener on a snapshot at most listenerFresh old for a connection that carries a
// secret: every listener that takes connections to ip and port must be one owns accepts, at least one
// must listen, and docker must not forward the port. Without owns (a loopback target, a container's
// address) the fresh snapshot alone is asked.
func checkOwner(ctx context.Context, ip netip.Addr, port uint16, contained bool, owns func() func(listener) bool) error {
	if err := judgeListener(ctx, ip, port, contained, listenerFresh); err != nil {
		return err
	}
	if owns == nil || contained {
		return nil
	}
	published, err := checkPublished(ctx, ip, port, listenerFresh)
	if err != nil {
		return err
	}
	if published {
		return fmt.Errorf("%w: docker forwards port %d, the target of a secret must listen there itself", ErrNotAllowed, port)
	}
	list, err := listenersAtMost(ctx, listenerFresh)
	if err != nil {
		return fmt.Errorf("%w: the listening sockets cannot be read: %v", ErrNotAllowed, err)
	}
	match, found := owns(), false
	for _, l := range list {
		if l.port != port || !carries(l.addr, ip) {
			continue
		}
		if !match(l) {
			return fmt.Errorf("%w: port %d is held by another process than the target of the secret", ErrNotAllowed, port)
		}
		found = true
	}
	if !found {
		return fmt.Errorf("%w: the target of the secret no longer listens on port %d", ErrNotAllowed, port)
	}
	return nil
}

// contained says whether ip is one of the extra addresses, of a container of this host: its
// listeners live in the container's network namespace, which the snapshot does not see.
func (g *Guard) contained(ip netip.Addr) bool {
	return slices.Contains(g.extra, ip.WithZone(""))
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

// errNoProcess is a port of this host nobody listens on: whatever took a connection there would be
// no process the guard has checked. It does not wrap ErrNotAllowed, so the probe reports an error.
var errNoProcess = errors.New("no process listens on port")

// checkListener returns an error if a blocked process listens on ip and port, or if that cannot be
// told: a listener on the unspecified address takes connections to every address of the host. A
// socket systemd or a super-server (activator) alone holds tells nothing of the service it starts. A
// port without a listener is errNoProcess, unless docker publishes it or ip is a container's (contained).
func checkListener(ctx context.Context, ip netip.Addr, port uint16, contained bool) error {
	err := judgeListener(ctx, ip, port, contained, listenerTTL)
	if errors.Is(err, errNoProcess) {
		err = judgeListener(ctx, ip, port, contained, listenerFresh)
	}
	return err
}

// carries says whether a socket bound to bound takes connections to ip. A socket on 0.0.0.0 takes
// no IPv6 connection; one on :: may take IPv4 ones too, unless it is IPv6-only, which is not told.
func carries(bound, ip netip.Addr) bool {
	return bound == ip || (bound.IsUnspecified() && (bound.Is6() || ip.Is4()))
}

// judgeListener is checkListener on snapshots at most maxAge old. A blocked process on an
// unspecified address of either family is refused; only a socket that carries ip serves it.
func judgeListener(ctx context.Context, ip netip.Addr, port uint16, contained bool, maxAge time.Duration) error {
	list, err := listenersAtMost(ctx, maxAge)
	if err != nil {
		return fmt.Errorf("%w: the listening sockets cannot be read: %v", ErrNotAllowed, err)
	}
	holder, served := "", false
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
		if err := checkForwarder(ctx, l.pid, name, fmt.Sprintf("port %d", port)); err != nil {
			return err
		}
		if service, err := serviceForwarder(ctx, l.pid); err != nil {
			return fmt.Errorf("%w: the service of the process listening on port %d cannot be read: %v", ErrNotAllowed, port, err)
		} else if service != "" {
			return fmt.Errorf("%w: port %d belongs to the service %s, which forwards to an end the agent cannot check", ErrNotAllowed, port, service)
		}
		k := processKey(name)
		if activator(k) {
			holder = k
			continue
		}
		switch k {
		case "docker-proxy":
			if err := checkProxy(ctx, l.pid, port); err != nil {
				return err
			}
			if err := checkProxied(ctx, ip, port, maxAge); err != nil {
				return err
			}
		}
		served = served || carries(l.addr, ip)
	}
	if holder != "" && !served {
		return fmt.Errorf("%w: %s holds port %d for socket activation, the service behind it cannot be told", ErrNotAllowed, holder, port)
	}
	published, err := checkPublished(ctx, ip, port, maxAge)
	if err != nil {
		return err
	}
	if !served && !published && !contained {
		return fmt.Errorf("%w %d", errNoProcess, port)
	}
	return nil
}

// checkForwarder returns an error if the process pid, named name, that serves at (a port or a
// socket) is one of forwarders. A program that runs itself anew through /proc/self/exe (Podman's rootlessport) is named
// exe by the kernel; its argv[0] tells which it is, and an argv that cannot be read is refused.
func checkForwarder(ctx context.Context, pid int32, name, at string) error {
	if processKey(name) == "exe" {
		args, err := processArgs(ctx, pid)
		if err != nil {
			return fmt.Errorf("%w: the process %s serving %s cannot be told: %v", ErrNotAllowed, name, at, err)
		}
		// An argv[0] that is again /proc/self/exe tells no more than none.
		if len(args) == 0 || processKey(filepath.Base(args[0])) == "exe" {
			return fmt.Errorf("%w: the process %s serving %s cannot be told", ErrNotAllowed, name, at)
		}
		name = filepath.Base(args[0])
	}
	if forwarder(name) {
		// name may come from argv[0], which its process sets at will: the text keeps a bounded part.
		return fmt.Errorf("%w: %s belongs to %.64s, which forwards to an end the agent cannot check", ErrNotAllowed, at, name)
	}
	return nil
}

// checkPublished returns an error if docker forwards ip and port to a port of a container a probe
// never connects to, or if that cannot be told; published says whether docker forwards them at all.
// Without its userland proxy (userland-proxy=false) docker forwards a published port by NAT alone,
// ahead of any process listening on the host port.
func checkPublished(ctx context.Context, ip netip.Addr, port uint16, maxAge time.Duration) (published bool, err error) {
	list, err := publicationsAtMost(ctx, maxAge)
	if err != nil {
		return false, fmt.Errorf("%w: the published ports of the containers cannot be read: %v", ErrNotAllowed, err)
	}
	for _, p := range list {
		if !p.forwards(ip, port) {
			continue
		}
		if blockedPort(p.to) {
			return false, fmt.Errorf("%w: port %d forwards to port %d of a container, one the agent never probes", ErrNotAllowed, port, p.to)
		}
		if err := checkInside(ctx, p, maxAge); err != nil {
			return false, err
		}
		published = published || !p.hostIP.IsValid() || carries(p.hostIP, ip)
	}
	return published, nil
}

// forwards says whether docker forwards connections to ip and port by p.
func (p publication) forwards(ip netip.Addr, port uint16) bool {
	return p.hostPort == port && (!p.hostIP.IsValid() || p.hostIP.IsUnspecified() || p.hostIP == ip)
}

// checkProxied returns an error unless docker publishes ip and port, on which a docker-proxy listens:
// only the publication names the container whose process checkPublished judges. A container started
// since the last list was read is looked for in a fresh one.
func checkProxied(ctx context.Context, ip netip.Addr, port uint16, maxAge time.Duration) error {
	for _, age := range []time.Duration{maxAge, listenerFresh} {
		list, err := publicationsAtMost(ctx, age)
		if err != nil {
			return fmt.Errorf("%w: the published ports of the containers cannot be read: %v", ErrNotAllowed, err)
		}
		if slices.ContainsFunc(list, func(p publication) bool { return p.forwards(ip, port) }) {
			return nil
		}
	}
	return fmt.Errorf("%w: the docker-proxy on port %d serves no port docker publishes there", ErrNotAllowed, port)
}

// checkInside judges the processes that listen on the container port p forwards to, in the
// container's network namespace, as checkListener judges those of the host: a forwarder inside a
// container leads as far as one outside. Processes that cannot be told are refused.
func checkInside(ctx context.Context, p publication, maxAge time.Duration) error {
	pids, err := insideAtMost(ctx, p.pid, p.to, maxAge)
	if err != nil {
		return fmt.Errorf("%w: the process behind port %d of a container cannot be told: %v", ErrNotAllowed, p.to, err)
	}
	at := fmt.Sprintf("port %d of a container", p.to)
	for _, pid := range pids {
		name, err := processName(ctx, pid)
		if err != nil {
			return fmt.Errorf("%w: the process listening on %s cannot be read: %v", ErrNotAllowed, at, err)
		}
		if neverProbed(name) {
			return fmt.Errorf("%w: %s belongs to %s, which the agent never probes", ErrNotAllowed, at, name)
		}
		if err := checkForwarder(ctx, pid, name, at); err != nil {
			return err
		}
	}
	return nil
}

// insideKey names a container port by the container's main process.
type insideKey struct {
	pid  int32
	port uint16
}

// inside holds the processes last found on container ports, shared by every guard of the process:
// telling them walks the descriptors of every process in the container.
var inside struct {
	sync.Mutex
	found map[insideKey]insideFound
}

type insideFound struct {
	at   time.Time
	pids []int32
}

// insideAtMost returns the processes listening on port in the network namespace of pid, at most
// maxAge old.
func insideAtMost(ctx context.Context, pid int32, port uint16, maxAge time.Duration) ([]int32, error) {
	inside.Lock()
	defer inside.Unlock()
	k := insideKey{pid, port}
	if f, ok := inside.found[k]; ok && time.Since(f.at) < maxAge {
		return f.pids, nil
	}
	pids, err := containerListeners(ctx, pid, port)
	if err != nil {
		return nil, err
	}
	if inside.found == nil {
		inside.found = map[insideKey]insideFound{}
	}
	// Containers come and go: what no snapshot may use any more goes.
	for old, f := range inside.found {
		if time.Since(f.at) >= listenerTTL {
			delete(inside.found, old)
		}
	}
	inside.found[k] = insideFound{time.Now(), pids}
	return pids, nil
}

// publications is the last list of the published ports, shared by every guard of the process.
var publications struct {
	sync.Mutex
	at   time.Time
	list []publication
}

// publicationsAtMost returns the published ports of the running containers, at most maxAge old.
func publicationsAtMost(ctx context.Context, maxAge time.Duration) ([]publication, error) {
	publications.Lock()
	defer publications.Unlock()
	if publications.list != nil && time.Since(publications.at) < maxAge {
		return publications.list, nil
	}
	list, err := publishedPorts(ctx)
	if err != nil {
		return nil, err
	}
	if list == nil {
		list = []publication{}
	}
	publications.list, publications.at = list, time.Now()
	return list, nil
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
	return listenersAtMost(ctx, listenerTTL)
}

// listenersAtMost returns the listening TCP sockets of this host, at most maxAge old.
func listenersAtMost(ctx context.Context, maxAge time.Duration) ([]listener, error) {
	snapshot.Lock()
	defer snapshot.Unlock()
	if snapshot.list != nil && time.Since(snapshot.at) < maxAge {
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
