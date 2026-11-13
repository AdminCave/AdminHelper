// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/netip"
	"os"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

// fakeHost is what the guard's seams see of the host in a test.
type fakeHost struct {
	addrs     []net.Addr
	addrsErr  error
	list      []listener
	listErr   error
	listCalls int
	names     map[int32]string
	args      map[int32][]string
	pubs      []publication
	pubsErr   error
	pubsCalls int
	// live lets the real listeners and processes of the test answer behind the fakes, for tests
	// that serve on loopback themselves.
	live bool
	// peer answers which socket took a connection; nil says the one bound to its server end.
	peer      func(server, client netip.AddrPort) (peerState, error)
	peerCalls int
	// services names the forwarding service of a process; servicesErr fails reading it.
	services    map[int32]string
	servicesErr error
}

// stubHost puts h in for the guard's seams and starts without a snapshot of the listeners.
func stubHost(t *testing.T, h *fakeHost) {
	t.Helper()
	oldAddrs, oldList, oldName, oldArgs, oldPubs := interfaceAddrs, listeners, processName, processArgs, publishedPorts
	oldPeer, oldService := peerSocket, serviceForwarder
	serviceForwarder = func(_ context.Context, pid int32) (string, error) {
		if h.live && h.services == nil && h.servicesErr == nil {
			return oldService(context.Background(), pid)
		}
		return h.services[pid], h.servicesErr
	}
	peerSocket = func(server, client netip.AddrPort) (peerState, error) {
		h.peerCalls++
		if h.peer == nil {
			return peerConnected, nil
		}
		return h.peer(server, client)
	}
	interfaceAddrs = func() ([]net.Addr, error) { return h.addrs, h.addrsErr }
	publishedPorts = func(context.Context) ([]publication, error) {
		h.pubsCalls++
		return h.pubs, h.pubsErr
	}
	listeners = func(ctx context.Context) ([]listener, error) {
		h.listCalls++
		if h.live {
			list, err := oldList(ctx)
			return append(list, h.list...), err
		}
		return h.list, h.listErr
	}
	processName = func(ctx context.Context, pid int32) (string, error) {
		name, ok := h.names[pid]
		if !ok {
			if h.live {
				return oldName(ctx, pid)
			}
			return "", errors.New("access is denied")
		}
		return name, nil
	}
	processArgs = func(ctx context.Context, pid int32) ([]string, error) {
		args, ok := h.args[pid]
		if !ok {
			if h.live {
				return oldArgs(ctx, pid)
			}
			return nil, errors.New("access is denied")
		}
		return args, nil
	}
	resetSnapshot := func() {
		snapshot.Lock()
		snapshot.list, snapshot.at = nil, time.Time{}
		snapshot.Unlock()
		publications.Lock()
		publications.list, publications.at = nil, time.Time{}
		publications.Unlock()
		redirected.Lock()
		redirected.at = nil
		redirected.Unlock()
	}
	resetSnapshot()
	t.Cleanup(func() {
		interfaceAddrs, listeners, processName, processArgs, publishedPorts = oldAddrs, oldList, oldName, oldArgs, oldPubs
		peerSocket, serviceForwarder = oldPeer, oldService
		resetSnapshot()
	})
}

func ipNet(s string) net.Addr {
	ip, n, err := net.ParseCIDR(s)
	if err != nil {
		panic(err)
	}
	n.IP = ip
	return n
}

func lst(addr string, port uint16, pid int32) listener {
	return listener{addr: netip.MustParseAddr(addr), port: port, pid: pid}
}

// allowed returns the guard's verdict on dialing address over network.
func allowed(g *Guard, network, address string) error {
	return g.control(context.Background(), network, address, nil)
}

func TestGuardLetsTheSensorsReachThisHostAlone(t *testing.T) {
	stubHost(t, &fakeHost{addrs: []net.Addr{
		ipNet("192.0.2.10/24"),
		&net.IPAddr{IP: net.ParseIP("198.51.100.5")},
		ipNet("2001:db8::10/64"),
	}, list: []listener{lst("0.0.0.0", 8080, 50), lst("::", 443, 50)}, names: map[int32]string{50: "nginx"}})
	// The extra addresses are a container's: its listeners are not in the snapshot (6379).
	g := NewGuard(netip.MustParseAddr("203.0.113.9"), netip.MustParseAddr("::ffff:203.0.113.10"))

	for _, c := range []struct{ network, address string }{
		{"tcp4", "127.0.0.1:8080"},
		{"tcp4", "127.1.2.3:8080"},
		{"tcp6", "[::1]:443"},
		{"tcp4", "192.0.2.10:443"},
		{"tcp6", "[::ffff:192.0.2.10]:443"},
		{"tcp4", "198.51.100.5:443"},
		{"tcp6", "[2001:db8::10]:443"},
		{"tcp4", "203.0.113.9:6379"},
		{"tcp4", "203.0.113.10:6379"},
		{"udp4", "127.0.0.1:53"},
		{"udp6", "[::1]:53"},
	} {
		if err := allowed(g, c.network, c.address); err != nil {
			t.Errorf("%s %s: %v, want it allowed", c.network, c.address, err)
		}
	}
}

func TestGuardRefusesEveryOtherTarget(t *testing.T) {
	stubHost(t, &fakeHost{addrs: []net.Addr{ipNet("192.0.2.10/24")}})
	g := NewGuard(netip.MustParseAddr("203.0.113.9"))

	for _, c := range []struct{ network, address, want string }{
		{"tcp4", "192.0.2.11:80", "is no address of this host"},
		{"tcp4", "203.0.113.8:80", "is no address of this host"},
		{"tcp4", "0.0.0.0:80", "is no address the agent probes"},
		{"tcp6", "[::]:80", "is no address the agent probes"},
		{"tcp4", "169.254.169.254:80", "is no address the agent probes"},
		{"tcp6", "[fe80::1%eth0]:80", "is no address the agent probes"},
		{"udp4", "224.0.0.251:5353", "is no address the agent probes"},
		{"udp6", "[ff02::1]:5353", "is no address the agent probes"},
		{"unix", "/run/docker.sock", "network unix"},
		{"ip4:icmp", "127.0.0.1", "network ip4:icmp"},
		{"tcp4", "localhost:80", "is no address"},
	} {
		err := allowed(g, c.network, c.address)
		if !errors.Is(err, ErrNotAllowed) || !strings.Contains(err.Error(), c.want) {
			t.Errorf("%s %s: %v, want ErrNotAllowed with %q", c.network, c.address, err, c.want)
		}
	}
}

func TestGuardFailsClosedWithoutTheAddressesOfThisHost(t *testing.T) {
	stubHost(t, &fakeHost{
		addrsErr: errors.New("netlink refused"),
		list:     []listener{lst("0.0.0.0", 80, 50)},
		names:    map[int32]string{50: "nginx"},
	})
	g := NewGuard()

	if err := allowed(g, "tcp4", "192.0.2.10:80"); !errors.Is(err, ErrNotAllowed) {
		t.Errorf("an address of this host it cannot read: %v, want ErrNotAllowed", err)
	}
	if err := allowed(g, "tcp4", "127.0.0.1:80"); err != nil {
		t.Errorf("loopback: %v, want it allowed without the list", err)
	}
}

func TestGuardNeverProbesTheBlockedPorts(t *testing.T) {
	var list []listener
	for _, port := range []uint16{21, 23, 3307, 9099, 9108} {
		list = append(list, lst("127.0.0.1", port, 50))
	}
	stubHost(t, &fakeHost{list: list, names: map[int32]string{50: "nginx"}})
	g := NewGuard()

	for _, port := range []string{"0", "22", "3306", "9100", "9103", "9107"} {
		for _, network := range []string{"tcp4", "udp4"} {
			err := allowed(g, network, "127.0.0.1:"+port)
			if !errors.Is(err, ErrNotAllowed) || !strings.Contains(err.Error(), "never probes") {
				t.Errorf("%s port %s: %v, want it refused", network, port, err)
			}
		}
	}
	for _, port := range []string{"21", "23", "3307", "9099", "9108"} {
		if err := allowed(g, "tcp4", "127.0.0.1:"+port); err != nil {
			t.Errorf("port %s: %v, want it allowed", port, err)
		}
	}
}

func TestGuardNeverProbesTheListenersOfTheBlockedProcesses(t *testing.T) {
	stubHost(t, &fakeHost{
		addrs: []net.Addr{ipNet("192.0.2.10/24")},
		list: []listener{
			lst("0.0.0.0", 2222, 10),
			lst("127.0.0.1", 3307, 11),
			lst("::", 5000, 12),
			lst("192.0.2.10", 6000, 13),
			lst("127.0.0.1", 7000, 14),
			lst("127.0.0.1", 2375, 15),
			lst("127.0.0.1", 8001, 16),
			lst("127.0.0.1", 16509, 17),
			lst("127.0.0.1", 8080, 18),
			lst("127.0.0.1", 9000, 19),
			lst("127.0.0.1", 6000, 19),
		},
		names: map[int32]string{
			10: "sshd", 11: "MariaDBd.exe", 12: "nginx", 13: "mysqld", 14: "postgres",
			15: "dockerd", 16: "containerd-shim-runc-v2", 17: "virtqemud", 18: "Podman.exe", 19: "php-fpm",
		},
	})
	g := NewGuard()

	for _, c := range []struct {
		network, address string
		refused          bool
	}{
		{"tcp4", "127.0.0.1:2222", true},
		{"tcp4", "192.0.2.10:2222", true},
		{"tcp4", "127.0.0.1:3307", true},
		{"tcp4", "127.0.0.1:5000", false},
		{"tcp4", "127.0.0.1:6000", false},
		{"tcp4", "192.0.2.10:6000", true},
		{"tcp4", "127.0.0.1:7000", false},
		{"tcp4", "127.0.0.1:2375", true},
		{"tcp4", "127.0.0.1:8001", true},
		{"tcp4", "127.0.0.1:16509", true},
		{"tcp4", "127.0.0.1:8080", true},
		{"tcp4", "127.0.0.1:9000", false},
		{"udp4", "127.0.0.1:2222", false},
	} {
		err := allowed(g, c.network, c.address)
		if c.refused && (!errors.Is(err, ErrNotAllowed) || !strings.Contains(err.Error(), "which the agent never probes")) {
			t.Errorf("%s %s: %v, want it refused for its process", c.network, c.address, err)
		}
		if !c.refused && err != nil {
			t.Errorf("%s %s: %v, want it allowed", c.network, c.address, err)
		}
	}
}

func TestGuardNeverProbesAContainerPortPublishedFromABlockedOne(t *testing.T) {
	proxy := func(hostPort, containerPort string) []string {
		return []string{"/usr/bin/docker-proxy", "-proto", "tcp", "-host-ip", "0.0.0.0", "-host-port", hostPort,
			"-container-ip", "192.0.2.2", "-container-port", containerPort, "-use-listen-fd"}
	}
	stubHost(t, &fakeHost{
		list: []listener{
			lst("0.0.0.0", 13306, 40), lst("0.0.0.0", 2222, 41), lst("::", 19100, 42), lst("0.0.0.0", 8080, 43),
			lst("0.0.0.0", 8081, 44), lst("0.0.0.0", 8082, 45), lst("0.0.0.0", 8083, 46), lst("0.0.0.0", 8084, 47),
			lst("0.0.0.0", 8085, 48), lst("0.0.0.0", 8086, 49),
		},
		names: map[int32]string{
			40: "docker-proxy", 41: "docker-proxy", 42: "docker-proxy", 43: "docker-proxy", 44: "docker-proxy",
			45: "docker-proxy", 46: "docker-proxy", 47: "docker-proxy", 48: "docker-proxy", 49: "nginx",
		},
		args: map[int32][]string{
			40: proxy("13306", "3306"),
			41: {"docker-proxy", "--container-port=22", "-host-port=2222"},
			42: {"docker-proxy", "-container-port", "80", "-container-port", "9100"},
			43: proxy("8080", "80"),
			// 44: the arguments cannot be read.
			45: {"docker-proxy", "-host-port", "8082"},
			46: {"docker-proxy", "-container-port", "http"},
			47: {"docker-proxy", "--", "-container-port", "3306"},
			48: {"docker-proxy", "-container-port"},
			49: {"nginx", "-container-port", "3306"},
		},
	})
	g := NewGuard()

	for _, c := range []struct {
		address, want string
	}{
		{"127.0.0.1:13306", "forwards to port 3306 of a container"},
		{"127.0.0.1:2222", "forwards to port 22 of a container"},
		{"[::1]:19100", "forwards to port 9100 of a container"},
		{"127.0.0.1:8081", "cannot be read"},
		{"127.0.0.1:8082", "is not told"},
		{"127.0.0.1:8083", "is not told"},
		{"127.0.0.1:8084", "is not told"},
		{"127.0.0.1:8085", "is not told"},
	} {
		network := "tcp4"
		if strings.HasPrefix(c.address, "[") {
			network = "tcp6"
		}
		if err := allowed(g, network, c.address); !errors.Is(err, ErrNotAllowed) || !strings.Contains(err.Error(), c.want) {
			t.Errorf("%s: %v, want it refused: %s", c.address, err, c.want)
		}
	}
	for _, address := range []string{"127.0.0.1:8080", "127.0.0.1:8086"} {
		if err := allowed(g, "tcp4", address); err != nil {
			t.Errorf("%s: %v, want it allowed", address, err)
		}
	}
}

func TestGuardNeverProbesAPortAForwarderListensOn(t *testing.T) {
	stubHost(t, &fakeHost{
		list: []listener{
			lst("0.0.0.0", 8001, 60), lst("0.0.0.0", 8002, 61), lst("0.0.0.0", 8003, 62), lst("0.0.0.0", 8004, 63),
			lst("0.0.0.0", 8005, 64), lst("0.0.0.0", 8006, 65), lst("0.0.0.0", 8007, 66), lst("::", 8008, 67),
			lst("0.0.0.0", 8009, 68), lst("0.0.0.0", 8010, 69), lst("0.0.0.0", 8011, 70),
			lst("127.0.0.1", 8012, 71), lst("127.0.0.1", 8013, 72), lst("127.0.0.1", 8014, 73),
			lst("127.0.0.1", 8015, 74), lst("127.0.0.1", 8016, 75), lst("127.0.0.1", 8017, 76),
			lst("127.0.0.1", 8018, 77), lst("127.0.0.1", 8019, 78), lst("127.0.0.1", 8020, 79),
			lst("127.0.0.1", 8021, 80), lst("127.0.0.1", 8022, 81), lst("127.0.0.1", 8023, 82),
			lst("127.0.0.1", 8024, 83), lst("127.0.0.1", 8025, 84), lst("127.0.0.1", 8026, 85),
			lst("127.0.0.1", 8027, 86),
			lst("127.0.0.1", 8028, 87), lst("127.0.0.1", 8029, 88), lst("127.0.0.1", 8030, 89),
			lst("127.0.0.1", 8031, 90), lst("127.0.0.1", 8032, 91), lst("127.0.0.1", 8033, 92),
			lst("127.0.0.1", 8034, 93), lst("127.0.0.1", 8035, 94), lst("127.0.0.1", 8036, 95),
			lst("127.0.0.1", 8037, 96), lst("127.0.0.1", 8038, 97), lst("127.0.0.1", 8039, 98),
			lst("127.0.0.1", 8040, 99), lst("127.0.0.1", 8041, 100), lst("127.0.0.1", 8042, 101),
			lst("127.0.0.1", 8043, 102), lst("127.0.0.1", 8044, 103), lst("127.0.0.1", 8045, 104),
			lst("127.0.0.1", 8046, 105), lst("127.0.0.1", 8047, 106), lst("127.0.0.1", 8048, 107),
			lst("127.0.0.1", 8049, 108), lst("127.0.0.1", 8050, 109), lst("127.0.0.1", 8051, 110),
			lst("127.0.0.1", 8052, 111), lst("127.0.0.1", 8053, 112), lst("127.0.0.1", 8054, 113),
			lst("127.0.0.1", 8055, 114), lst("127.0.0.1", 8056, 115), lst("127.0.0.1", 8057, 116),
			lst("127.0.0.1", 8058, 117),
		},
		names: map[int32]string{
			60: "rootlesskit", 61: "rootlessport", 62: "slirp4netns", 63: "pasta.avx2", 64: "passt",
			65: "kube-proxy", 66: "socat", 67: "exe", 68: "exe", 69: "exe", 70: "nginx",
			71: "ssh", 72: "kubectl", 73: "gvproxy", 74: "vpnkit", 75: "autossh", 76: "exe", 77: "exe",
			78: "exe", 79: "sshfs", 80: "systemd-socket-", 81: "sslh", 82: "sslh-ev", 83: "sslh-select",
			84: "rinetd", 85: "redir", 86: "redis-server",
			87: "stunnel4", 88: "6tunnel", 89: "spiped", 90: "chisel", 91: "gost", 92: "ncat", 93: "frpc",
			94: "PUTTY.EXE", 95: "plink.exe", 96: "kitty_portable.exe", 97: "wslrelay.exe", 98: "wslhost.exe",
			99: "frps", 100: "exe", 101: "stunnel",
			102: "cloudflared", 103: "session-manager", 104: "wstunnel", 105: "boundary", 106: "tsh",
			107: "ghostunnel", 108: "rathole", 109: "nc", 110: "nc.openbsd", 111: "netcat", 112: "cloudflared.exe",
			113: "tshark", 114: "ncurses5-config", 115: "ncdu", 116: "nchan", 117: "tsdb",
		},
		args: map[int32][]string{
			67: {"rootlessport"},
			68: {"/usr/libexec/podman/rootlessport", "--child"},
			// 69: the arguments cannot be read.
			70:  {"nginx", "-g", "daemon off;"},
			76:  {},
			77:  {"/proc/self/exe", "--child"},
			78:  {"/usr/bin/caddy", "run"},
			79:  {"sshfs", "host:/srv", "/mnt"},
			100: {"/usr/bin/chisel", "client", "server:8080", "8041:remote:22"},
		},
	})
	g := NewGuard()

	for _, c := range []struct{ address, want string }{
		{"127.0.0.1:8001", "belongs to rootlesskit"},
		{"127.0.0.1:8002", "belongs to rootlessport"},
		{"127.0.0.1:8003", "belongs to slirp4netns"},
		{"127.0.0.1:8004", "belongs to pasta.avx2"},
		{"127.0.0.1:8005", "belongs to passt"},
		{"127.0.0.1:8006", "belongs to kube-proxy"},
		{"127.0.0.1:8007", "belongs to socat"},
		{"[::1]:8008", "belongs to rootlessport"},
		{"127.0.0.1:8009", "belongs to rootlessport"},
		{"127.0.0.1:8010", "cannot be told"},
		{"127.0.0.1:8012", "belongs to ssh"},
		{"127.0.0.1:8013", "belongs to kubectl"},
		{"127.0.0.1:8014", "belongs to gvproxy"},
		{"127.0.0.1:8015", "belongs to vpnkit"},
		{"127.0.0.1:8016", "belongs to autossh"},
		{"127.0.0.1:8017", "cannot be told"},
		{"127.0.0.1:8018", "cannot be told"},
		{"127.0.0.1:8021", "belongs to systemd-socket-"},
		{"127.0.0.1:8022", "belongs to sslh"},
		{"127.0.0.1:8023", "belongs to sslh-ev"},
		{"127.0.0.1:8024", "belongs to sslh-select"},
		{"127.0.0.1:8025", "belongs to rinetd"},
		{"127.0.0.1:8026", "port 8026 belongs to redir, which forwards to an end the agent cannot check"},
		{"127.0.0.1:8028", "belongs to stunnel4"},
		{"127.0.0.1:8029", "belongs to 6tunnel"},
		{"127.0.0.1:8030", "belongs to spiped"},
		{"127.0.0.1:8031", "belongs to chisel"},
		{"127.0.0.1:8032", "belongs to gost"},
		{"127.0.0.1:8033", "belongs to ncat"},
		{"127.0.0.1:8034", "belongs to frpc"},
		{"127.0.0.1:8035", "belongs to PUTTY.EXE"},
		{"127.0.0.1:8036", "belongs to plink.exe"},
		{"127.0.0.1:8037", "belongs to kitty_portable.exe"},
		{"127.0.0.1:8038", "belongs to wslrelay.exe"},
		{"127.0.0.1:8039", "belongs to wslhost.exe"},
		{"127.0.0.1:8040", "belongs to frps"},
		{"127.0.0.1:8041", "belongs to chisel"},
		{"127.0.0.1:8042", "belongs to stunnel"},
		{"127.0.0.1:8043", "belongs to cloudflared"},
		{"127.0.0.1:8044", "belongs to session-manager"},
		{"127.0.0.1:8045", "belongs to wstunnel"},
		{"127.0.0.1:8046", "belongs to boundary"},
		{"127.0.0.1:8047", "belongs to tsh"},
		{"127.0.0.1:8048", "belongs to ghostunnel"},
		{"127.0.0.1:8049", "belongs to rathole"},
		{"127.0.0.1:8050", "belongs to nc,"},
		{"127.0.0.1:8051", "belongs to nc.openbsd"},
		{"127.0.0.1:8052", "belongs to netcat"},
		{"127.0.0.1:8053", "belongs to cloudflared.exe"},
	} {
		network := "tcp4"
		if strings.HasPrefix(c.address, "[") {
			network = "tcp6"
		}
		if err := allowed(g, network, c.address); !errors.Is(err, ErrNotAllowed) || !strings.Contains(err.Error(), c.want) {
			t.Errorf("%s: %v, want it refused: %s", c.address, err, c.want)
		}
	}
	// nginx, a reexec whose argv[0] is no forwarder, sshfs (ssh matches whole, not as a prefix),
	// redis-server (no redir), and tshark, ncurses5-config, ncdu, nchan and tsdb (tsh and nc match whole).
	for _, address := range []string{"127.0.0.1:8011", "127.0.0.1:8019", "127.0.0.1:8020", "127.0.0.1:8027",
		"127.0.0.1:8054", "127.0.0.1:8055", "127.0.0.1:8056", "127.0.0.1:8057", "127.0.0.1:8058"} {
		if err := allowed(g, "tcp4", address); err != nil {
			t.Errorf("%s: %v, want it allowed", address, err)
		}
	}
}

func TestGuardFailsClosedWhenItCannotTellTheListener(t *testing.T) {
	h := &fakeHost{listErr: errors.New("permission denied")}
	stubHost(t, h)
	g := NewGuard()

	if err := allowed(g, "tcp4", "127.0.0.1:8080"); !errors.Is(err, ErrNotAllowed) || !strings.Contains(err.Error(), "listening sockets") {
		t.Errorf("unreadable listeners: %v, want ErrNotAllowed", err)
	}

	// The error is not kept: the next dial reads again.
	h.listErr = nil
	h.list = []listener{lst("127.0.0.1", 8080, 20), lst("127.0.0.1", 8081, 0)}
	h.names = map[int32]string{}
	if err := allowed(g, "tcp4", "127.0.0.1:8080"); !errors.Is(err, ErrNotAllowed) || !strings.Contains(err.Error(), "cannot be read") {
		t.Errorf("a listener whose process cannot be read: %v, want ErrNotAllowed", err)
	}
	if err := allowed(g, "tcp4", "127.0.0.1:8081"); !errors.Is(err, ErrNotAllowed) || !strings.Contains(err.Error(), "cannot be read") {
		t.Errorf("a listener without an owner: %v, want ErrNotAllowed", err)
	}
	if err := allowed(g, "tcp4", "127.0.0.1:8082"); !errors.Is(err, errNoProcess) {
		t.Errorf("a port without a listener: %v, want errNoProcess", err)
	}
	if h.listCalls != 2 {
		t.Errorf("listeners read %d times, want the failed read and one snapshot", h.listCalls)
	}
}

// TestGuardFailsClosedOnASocketSystemdHoldsAlone: a socket systemd or a super-server listens on for socket
// activation tells nothing of the service behind it until that runs and holds the socket too.
func TestGuardFailsClosedOnASocketSystemdHoldsAlone(t *testing.T) {
	stubHost(t, &fakeHost{
		list: []listener{
			lst("127.0.0.1", 2222, 1), lst("0.0.0.0", 5000, 900),
			lst("127.0.0.1", 631, 1), lst("127.0.0.1", 631, 30),
			lst("0.0.0.0", 16509, 1), lst("0.0.0.0", 16509, 31),
			lst("0.0.0.0", 2323, 40), lst("0.0.0.0", 7070, 41), lst("0.0.0.0", 3690, 41), lst("0.0.0.0", 3690, 32),
			lst("0.0.0.0", 7071, 42), lst("0.0.0.0", 7072, 43), lst("::", 7073, 44),
		},
		names: map[int32]string{1: "systemd", 900: "systemd", 30: "cupsd", 31: "libvirtd", 40: "xinetd", 41: "inetd",
			32: "svnserve", 42: "tcpserver", 43: "s6-tcpserver4", 44: "s6-tcpserverd"},
	})
	g := NewGuard()

	for _, c := range []struct{ address, want string }{
		{"127.0.0.1:2222", "systemd holds port 2222 for socket activation"},
		{"127.0.0.1:5000", "socket activation"},
		{"127.0.0.1:2323", "xinetd holds port 2323 for socket activation"},
		{"127.0.0.1:7070", "inetd holds port 7070 for socket activation"},
		{"127.0.0.1:7071", "tcpserver holds port 7071 for socket activation"},
		{"127.0.0.1:7072", "s6-tcpserver4 holds port 7072 for socket activation"},
		{"127.0.0.1:7073", "s6-tcpserverd holds port 7073 for socket activation"},
		{"127.0.0.1:16509", "libvirtd"},
	} {
		if err := allowed(g, "tcp4", c.address); !errors.Is(err, ErrNotAllowed) || !strings.Contains(err.Error(), c.want) {
			t.Errorf("%s: %v, want ErrNotAllowed with %q", c.address, err, c.want)
		}
	}
	// A socket the super-server and the service it started both hold (systemd, an inetd wait service).
	for _, address := range []string{"127.0.0.1:631", "127.0.0.1:3690"} {
		if err := allowed(g, "tcp4", address); err != nil {
			t.Errorf("%s: a socket the activator and the service it started hold: %v, want it allowed", address, err)
		}
	}
}

func TestGuardReadsTheListenersOncePerSnapshot(t *testing.T) {
	h := &fakeHost{list: []listener{lst("127.0.0.1", 8080, 30)}, names: map[int32]string{30: "nginx"}}
	stubHost(t, h)
	g := NewGuard()

	for range 3 {
		if err := allowed(g, "tcp4", "127.0.0.1:8080"); err != nil {
			t.Fatal(err)
		}
	}
	if h.listCalls != 1 {
		t.Fatalf("listeners read %d times, want once within %s", h.listCalls, listenerTTL)
	}

	snapshot.Lock()
	snapshot.at = snapshot.at.Add(-listenerTTL)
	snapshot.Unlock()
	h.list = []listener{lst("127.0.0.1", 8080, 30)}
	h.names = map[int32]string{30: "sshd"}
	if err := allowed(g, "tcp4", "127.0.0.1:8080"); !errors.Is(err, ErrNotAllowed) {
		t.Errorf("after the snapshot aged: %v, want the new sshd listener refused", err)
	}
	if h.listCalls != 2 {
		t.Errorf("listeners read %d times, want a new snapshot", h.listCalls)
	}
}

// localServer serves h on 127.0.0.1 and lets the guard's seams see the test's own listeners alone.
func localServer(t *testing.T, h http.Handler) *httptest.Server {
	t.Helper()
	stubHost(t, &fakeHost{live: true})
	srv := httptest.NewServer(h)
	t.Cleanup(srv.Close)
	return srv
}

func TestHTTPClientSendsOnlyRequestsThatChangeNothing(t *testing.T) {
	var hits atomic.Int32
	srv := localServer(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
	}))
	c := NewGuard().HTTPClient(nil)

	for _, method := range []string{http.MethodGet, http.MethodHead} {
		req, _ := http.NewRequest(method, srv.URL, nil)
		resp, err := c.Do(req)
		if err != nil {
			t.Fatalf("%s: %v", method, err)
		}
		_ = resp.Body.Close()
	}
	for _, method := range []string{http.MethodPost, http.MethodPut, http.MethodDelete, http.MethodPatch, "PROPFIND"} {
		req, _ := http.NewRequest(method, srv.URL, strings.NewReader("x"))
		if resp, err := c.Do(req); !errors.Is(err, ErrInvalid) {
			if resp != nil {
				_ = resp.Body.Close()
			}
			t.Errorf("%s: %v, want ErrInvalid", method, err)
		}
	}
	if hits.Load() != 2 {
		t.Errorf("the server got %d requests, want GET and HEAD alone", hits.Load())
	}
}

func TestHTTPClientFollowsARedirectOnlyToTheSameTarget(t *testing.T) {
	var otherHits atomic.Int32
	other := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { otherHits.Add(1) }))
	defer other.Close()
	srv := localServer(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/same":
			http.Redirect(w, r, "/ok", http.StatusFound)
		case "/other-port":
			http.Redirect(w, r, other.URL+"/", http.StatusFound)
		case "/other-host":
			http.Redirect(w, r, strings.Replace(r.Host, "127.0.0.1", "http://localhost", 1)+"/ok", http.StatusFound)
		case "/other-scheme":
			http.Redirect(w, r, "https://"+r.Host+"/ok", http.StatusFound)
		case "/loop":
			http.Redirect(w, r, "/loop", http.StatusFound)
		case "/ok":
			_, _ = io.WriteString(w, "fine")
		}
	}))
	c := NewGuard().HTTPClient(nil)

	resp, err := c.Get(srv.URL + "/same")
	if err != nil {
		t.Fatalf("redirect on the same target: %v", err)
	}
	body, _ := io.ReadAll(resp.Body)
	_ = resp.Body.Close()
	if string(body) != "fine" {
		t.Fatalf("body = %q, want the redirect followed", body)
	}

	for _, path := range []string{"/other-port", "/other-host", "/other-scheme", "/loop"} {
		resp, err := c.Get(srv.URL + path)
		if resp != nil {
			_ = resp.Body.Close()
		}
		if !errors.Is(err, ErrNotAllowed) {
			t.Errorf("%s: %v, want ErrNotAllowed", path, err)
		}
	}
	if otherHits.Load() != 0 {
		t.Errorf("the other target got %d requests, want none", otherHits.Load())
	}
}

func TestHTTPClientReadsAtMostTheCapOfABody(t *testing.T) {
	srv := localServer(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		n := maxBodyBytes
		if r.URL.Path == "/over" {
			n++
		}
		_, _ = w.Write([]byte(strings.Repeat("x", n)))
	}))
	c := NewGuard().HTTPClient(nil)

	read := func(path string) (int, error) {
		resp, err := c.Get(srv.URL + path)
		if err != nil {
			return 0, err
		}
		defer resp.Body.Close()
		data, err := io.ReadAll(resp.Body)
		return len(data), err
	}
	if n, err := read("/exact"); err != nil || n != maxBodyBytes {
		t.Errorf("a body of the cap: %d bytes, %v; want all of it", n, err)
	}
	if n, err := read("/over"); !errors.Is(err, errBodyTooLarge) || n > maxBodyBytes {
		t.Errorf("a body beyond the cap: %d bytes, %v; want errBodyTooLarge", n, err)
	}
}

func TestHTTPClientRefusesAHugeHeader(t *testing.T) {
	srv := localServer(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Big", strings.Repeat("x", maxHeaderBytes+1))
	}))

	resp, err := NewGuard().HTTPClient(nil).Get(srv.URL)
	if err == nil {
		_ = resp.Body.Close()
		t.Fatal("a header beyond the cap: want an error")
	}
}

func TestHTTPClientDialsThroughTheGuard(t *testing.T) {
	stubHost(t, &fakeHost{})
	t.Setenv("HTTP_PROXY", "http://127.0.0.1:1")

	resp, err := NewGuard().HTTPClient(nil).Get("http://192.0.2.99:8080/")
	if resp != nil {
		_ = resp.Body.Close()
	}
	if !errors.Is(err, ErrNotAllowed) || !strings.Contains(err.Error(), "no address of this host") {
		t.Fatalf("a request to another host: %v, want ErrNotAllowed from the guard, no proxy", err)
	}
}

func TestTheHostSeamsReadTheListenersAndTheirProcesses(t *testing.T) {
	ln, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer ln.Close()
	port := uint16(ln.Addr().(*net.TCPAddr).Port)

	list, err := listenTCP(context.Background())
	if err != nil {
		t.Fatalf("listenTCP: %v", err)
	}
	var own *listener
	for i, l := range list {
		if l.port == port && l.addr == netip.MustParseAddr("127.0.0.1") {
			own = &list[i]
		}
	}
	if own == nil || own.pid != int32(os.Getpid()) {
		t.Fatalf("listenTCP = %v, want 127.0.0.1:%d of this process (%d)", list, port, os.Getpid())
	}

	name, err := nameOf(context.Background(), own.pid)
	if err != nil || name == "" {
		t.Errorf("nameOf(this process) = %q, %v; want its name", name, err)
	}
	if _, err := nameOf(context.Background(), 0); err == nil || !strings.Contains(err.Error(), "the owner is unknown") {
		t.Errorf("nameOf(0) = %v, want the owner unknown", err)
	}

	args, err := argsOf(context.Background(), own.pid)
	if err != nil || len(args) == 0 || args[len(args)-1] != os.Args[len(os.Args)-1] {
		t.Errorf("argsOf(this process) = %q, %v; want its arguments %q", args, err, os.Args)
	}
	if _, err := argsOf(context.Background(), 0); err == nil || !strings.Contains(err.Error(), "the owner is unknown") {
		t.Errorf("argsOf(0) = %v, want the owner unknown", err)
	}
}

func pub(hostIP string, hostPort, to uint16) publication {
	var ip netip.Addr
	if hostIP != "" {
		ip = netip.MustParseAddr(hostIP)
	}
	return publication{hostIP: ip, hostPort: hostPort, to: to}
}

func TestGuardNeverProbesAPortDockerForwardsToABlockedOneWithoutAListener(t *testing.T) {
	stubHost(t, &fakeHost{
		addrs: []net.Addr{ipNet("192.0.2.10/24")},
		list:  []listener{lst("127.0.0.1", 18080, 50), lst("192.0.2.10", 19107, 50), lst("127.0.0.1", 13307, 50)},
		names: map[int32]string{50: "nginx"},
		pubs: []publication{
			pub("", 13306, 3306), pub("0.0.0.0", 2222, 22), pub("::", 19100, 9100), pub("127.0.0.1", 19107, 9107),
			pub("192.0.2.10", 13307, 3306), pub("", 8080, 80), pub("", 18080, 22),
		},
	})
	g := NewGuard()

	for _, c := range []struct {
		address string
		refused bool
	}{
		{"127.0.0.1:13306", true},
		{"192.0.2.10:13306", true},
		{"127.0.0.1:2222", true},
		{"127.0.0.1:19100", true},
		{"127.0.0.1:19107", true},
		{"192.0.2.10:19107", false},
		{"192.0.2.10:13307", true},
		{"127.0.0.1:13307", false},
		// published by docker without a listener on the host (userland-proxy=false).
		{"127.0.0.1:8080", false},
		// docker forwards by NAT ahead of the listener on the port.
		{"127.0.0.1:18080", true},
	} {
		err := allowed(g, "tcp4", c.address)
		if c.refused && (!errors.Is(err, ErrNotAllowed) || !strings.Contains(err.Error(), "forwards to port")) {
			t.Errorf("%s: %v, want it refused for the container port", c.address, err)
		}
		if !c.refused && err != nil {
			t.Errorf("%s: %v, want it allowed", c.address, err)
		}
	}
}

func TestGuardRefusesWhenThePublishedPortsCannotBeRead(t *testing.T) {
	h := &fakeHost{
		list:    []listener{lst("127.0.0.1", 8080, 50)},
		names:   map[int32]string{50: "nginx"},
		pubsErr: errors.New("docker ps: exit status 1"),
	}
	stubHost(t, h)
	g := NewGuard()

	if err := allowed(g, "tcp4", "127.0.0.1:13306"); !errors.Is(err, ErrNotAllowed) || !strings.Contains(err.Error(), "published ports") {
		t.Fatalf("got %v, want it refused because the published ports cannot be read", err)
	}
	if err := allowed(g, "tcp4", "127.0.0.1:8080"); !errors.Is(err, ErrNotAllowed) || !strings.Contains(err.Error(), "published ports") {
		t.Fatalf("a port with a listener: %v, want it refused as well, docker forwards ahead of it", err)
	}
	if h.pubsCalls != 2 {
		t.Fatalf("published ports read %d times, want a new read per dial after a failure", h.pubsCalls)
	}
}

func TestGuardReadsThePublishedPortsOncePerSnapshot(t *testing.T) {
	h := &fakeHost{pubs: []publication{pub("", 8080, 80)}}
	stubHost(t, h)
	g := NewGuard()

	for range 3 {
		if err := allowed(g, "tcp4", "127.0.0.1:8080"); err != nil {
			t.Fatal(err)
		}
	}
	if h.pubsCalls != 1 {
		t.Fatalf("published ports read %d times, want once within %s", h.pubsCalls, listenerTTL)
	}
	publications.Lock()
	publications.at = publications.at.Add(-listenerTTL)
	publications.Unlock()
	if err := allowed(g, "tcp4", "127.0.0.1:8080"); err != nil {
		t.Fatal(err)
	}
	if h.pubsCalls != 2 {
		t.Fatalf("published ports read %d times, want a new read after %s", h.pubsCalls, listenerTTL)
	}
}

func TestNeverProbedNamesTheDaemonsOfHostsAndGuests(t *testing.T) {
	for _, name := range []string{"pvedaemon", "pvedaemon worke", "pveproxy", "pveproxy worker", "spiceproxy",
		"VBoxHeadless", "VBoxSVC", "cloud-hypervisor", "cloud-hyperviso", "firecracker", "crosvm", "xenconsoled",
		"xenstored", "kvm", "qemu-system-x86", "proxmox-backup-api", "proxmox-backup-proxy", "proxmox-backup-",
		"pmgdaemon", "pmgproxy", "kubelet", "k3s-server", "k3s", "buildkitd"} {
		if !neverProbed(name) {
			t.Errorf("%s: want it never probed", name)
		}
	}
	for _, name := range []string{"nginx", "php-fpm", "postgres", "redis-server", "haproxy", "pve-exporter"} {
		if neverProbed(name) {
			t.Errorf("%s: want it probed", name)
		}
	}
}

func TestNeverProbedSocketCoversTheRuntimeDirectoriesOfTheControlServices(t *testing.T) {
	for _, c := range controlSockets {
		path := c
		if strings.HasSuffix(c, "/") || strings.HasSuffix(c, "-") {
			path += "x/s.sock"
		}
		if !neverProbedSocket(path) {
			t.Errorf("%s: want it never probed", path)
		}
	}
	for _, path := range []string{"/var/run/docker.sock", "/var/run/dbus/system_bus_socket", "/run/user/1000/docker.sock",
		"/run/user/1000/bus", "/run/systemd/private", "/run/qemu-server/100.qmp", "/var/run/libvirt/libvirt-sock",
		"/run/containerd/containerd.sock", "/tmp/ssh-XXXXabcd/agent.42", "/tmp/.X11-unix/X0",
		"/run/buildkit/buildkitd.sock", "/var/run/lxc/x.sock", "/var/run/configd.socket"} {
		if !neverProbedSocket(path) {
			t.Errorf("%s: want it never probed", path)
		}
	}
	// The sockets of the services the catalog measures stay allowed.
	for _, path := range []string{"/run/php/php8.2-fpm.sock", "/run/redis/redis-server.sock", "/var/run/redis/redis.sock",
		"/run/haproxy/admin.sock", "/run/postgresql/.s.PGSQL.5432", "/run/nginx.sock", "/run/gunicorn.sock",
		"/run/docker.socket", "/run/dockerd/x.sock", "/run/userdb/x.sock", "/tmp/sshd.sock", "/var/lib/dockerx/s.sock"} {
		if neverProbedSocket(path) {
			t.Errorf("%s: want it allowed", path)
		}
	}
}

func TestCheckPeerNameRefusesWhatItCannotPlace(t *testing.T) {
	for _, name := range []string{"", "@abstract", "rel/s.sock", "s.sock", "/run/docker.sock", "/var/run/configd.socket",
		"/run/x/../docker.sock", "/run/user/1000/bus"} {
		if err := checkPeerName(name, "/tmp/p.sock"); !errors.Is(err, ErrNotAllowed) {
			t.Errorf("%q = %v; want ErrNotAllowed", name, err)
		}
	}
	for _, name := range []string{"/run/php/php8.2-fpm.sock", "/tmp/p.sock", "/var/run/redis/redis.sock"} {
		if err := checkPeerName(name, "/tmp/p.sock"); err != nil {
			t.Errorf("%q = %v; want it allowed", name, err)
		}
	}
}

// TestGuardNeverConnectsToAPortNobodyListensOn: whatever took a connection to a port of this host
// without a listener would be no process the guard has checked (R-1374).
func TestGuardNeverConnectsToAPortNobodyListensOn(t *testing.T) {
	stubHost(t, &fakeHost{
		addrs: []net.Addr{ipNet("192.0.2.10/24"), ipNet("2001:db8::10/64")},
		list:  []listener{lst("0.0.0.0", 8080, 50), lst("192.0.2.10", 8443, 50), lst("::", 8090, 50)},
		names: map[int32]string{50: "nginx"},
		pubs:  []publication{pub("", 9443, 443), pub("127.0.0.1", 9444, 443), pub("0.0.0.0", 9445, 443)},
	})
	g := NewGuard(netip.MustParseAddr("203.0.113.9"))

	for _, address := range []string{
		"127.0.0.1:8081", "192.0.2.10:8081", "[::1]:8081",
		"127.0.0.1:8443",                    // the listener holds another address
		"192.0.2.10:9444",                   // docker publishes it on another address
		"[2001:db8::10]:8080", "[::1]:8080", // a socket on 0.0.0.0 takes no IPv6 connection
		"[::1]:9445", // nor does a publication on 0.0.0.0
	} {
		network := "tcp4"
		if strings.HasPrefix(address, "[") {
			network = "tcp6"
		}
		err := allowed(g, network, address)
		_, port, _ := net.SplitHostPort(address)
		if !errors.Is(err, errNoProcess) || errors.Is(err, ErrNotAllowed) || err.Error() != "no process listens on port "+port {
			t.Errorf("%s: %v, want %q, not ErrNotAllowed (the check is red, not unknown)", address, err, "no process listens on port "+port)
		}
	}
	for _, c := range []struct{ network, address, why string }{
		{"tcp4", "127.0.0.1:8080", "a listener on the unspecified address"},
		{"tcp6", "[2001:db8::10]:8090", "a listener on ::"},
		{"tcp4", "192.0.2.10:8090", "a listener on ::, which may take IPv4 too"},
		{"tcp4", "127.0.0.1:9445", "published by docker on 0.0.0.0"},
		{"tcp4", "192.0.2.10:8443", "a listener on the address"},
		{"tcp4", "127.0.0.1:9443", "published by docker"},
		{"tcp4", "127.0.0.1:9444", "published by docker on the address"},
		{"tcp4", "203.0.113.9:6379", "an address of a container"},
		{"udp4", "127.0.0.1:53", "udp has no listener to tell"},
	} {
		if err := allowed(g, c.network, c.address); err != nil {
			t.Errorf("%s (%s): %v, want it allowed", c.address, c.why, err)
		}
	}
}

func TestGuardDialsNoPortNobodyListensOn(t *testing.T) {
	stubHost(t, &fakeHost{})
	ln, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = ln.Close() })

	// The fake host shows no listener, so the guard must refuse before it connects.
	c, err := NewGuard().DialContext(context.Background(), "tcp4", ln.Addr().String())
	if c != nil {
		_ = c.Close()
	}
	if !errors.Is(err, errNoProcess) {
		t.Fatalf("dial = %v, want errNoProcess", err)
	}
}

// TestGuardTellsNoListenerOnAFreshSnapshot: a service that started after the last snapshot is no
// port nobody listens on.
func TestGuardTellsNoListenerOnAFreshSnapshot(t *testing.T) {
	h := &fakeHost{names: map[int32]string{50: "nginx"}}
	stubHost(t, h)
	g := NewGuard()

	if err := allowed(g, "tcp4", "127.0.0.1:8080"); !errors.Is(err, errNoProcess) {
		t.Fatalf("no listener: %v, want errNoProcess", err)
	}
	if h.listCalls != 1 || h.pubsCalls != 1 {
		t.Fatalf("read %d listener and %d publication lists, want one each on a fresh snapshot", h.listCalls, h.pubsCalls)
	}

	h.list = []listener{lst("0.0.0.0", 8080, 50)}
	snapshot.Lock()
	snapshot.at = snapshot.at.Add(-2 * listenerFresh)
	snapshot.Unlock()
	if err := allowed(g, "tcp4", "127.0.0.1:8080"); err != nil {
		t.Fatalf("a listener since the snapshot: %v, want it allowed", err)
	}
	if h.listCalls != 2 {
		t.Errorf("listeners read %d times, want the miss told on a new snapshot", h.listCalls)
	}

	h.list = nil
	if err := allowed(g, "tcp4", "127.0.0.1:8081"); !errors.Is(err, errNoProcess) {
		t.Fatalf("no listener: %v, want errNoProcess", err)
	}
	if h.listCalls != 2 {
		t.Errorf("listeners read %d times, want no new snapshot within %s", h.listCalls, listenerFresh)
	}
}

// takenBy serves on loopback, lets peer tell which socket took each connection and returns the
// address and the connections the server accepted.
func takenBy(t *testing.T, h *fakeHost) (string, chan net.Conn) {
	t.Helper()
	h.live = true
	stubHost(t, h)
	ln, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = ln.Close() })
	accepted := make(chan net.Conn, 4)
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			accepted <- c
		}
	}()
	return ln.Addr().String(), accepted
}

// TestGuardDropsAConnectionAnotherSocketTook: a NAT redirect hands the connection to a socket the
// guard never checked; the kernel then lists no socket with the connection's ends, or only the
// listener (R-1370).
func TestGuardDropsAConnectionAnotherSocketTook(t *testing.T) {
	for _, c := range []struct {
		name  string
		state peerState
		err   error
		want  string
	}{
		{"only the listener", peerListener, nil, "taken by another socket"},
		{"no socket", peerNone, nil, "taken by another socket"},
		{"sock_diag fails", peerNone, errors.New("sock_diag: permission denied"), "cannot be told"},
	} {
		t.Run(c.name, func(t *testing.T) {
			h := &fakeHost{peer: redirect(c.state, c.err)}
			address, accepted := takenBy(t, h)
			conn, err := NewGuard().DialContext(context.Background(), "tcp", address)
			if !errors.Is(err, ErrNotAllowed) || !strings.Contains(err.Error(), c.want) {
				t.Fatalf("dial = %v, %v; want it refused: %s", conn, err, c.want)
			}
			wantCalls := peerTries + 1 // and once about the guard's own socket
			if c.err != nil {
				wantCalls = 1
			}
			if h.peerCalls != wantCalls {
				t.Errorf("asked %d times, want %d", h.peerCalls, wantCalls)
			}
			srv := <-accepted
			defer srv.Close()
			_ = srv.SetReadDeadline(time.Now().Add(30 * time.Second))
			// A reset reads as an error that is neither the orderly end (io.EOF) nor the deadline;
			// its errno differs between Unix and Windows.
			_, err = srv.Read(make([]byte, 1))
			var ne net.Error
			if err == nil || errors.Is(err, io.EOF) || (errors.As(err, &ne) && ne.Timeout()) {
				t.Errorf("the server read %v, want the connection reset", err)
			}
		})
	}
}

// redirect answers state (and err) about the port the guard dialed, the first end it asks about,
// and finds the guard's own socket: a redirect leaves the connection standing at the agent's end.
func redirect(state peerState, err error) func(server, client netip.AddrPort) (peerState, error) {
	var dialed netip.AddrPort
	return func(server, client netip.AddrPort) (peerState, error) {
		if !dialed.IsValid() {
			dialed = server
		}
		if server == dialed {
			return state, err
		}
		return peerConnected, nil
	}
}

// TestGuardRefusesAFullQueueOrAnEndedConnectionWithoutRememberingIt: a listener whose accept queue is
// full, and a service that resets the connection at once, leave no socket of the connection either;
// the probe is refused for what it is, and the port stays open to the next one (R-1409).
func TestGuardRefusesAFullQueueOrAnEndedConnectionWithoutRememberingIt(t *testing.T) {
	for _, c := range []struct {
		name      string
		peer      func(*fakeHost) func(server, client netip.AddrPort) (peerState, error)
		want      string
		wantCalls int
	}{
		{"the accept queue is full", func(*fakeHost) func(netip.AddrPort, netip.AddrPort) (peerState, error) {
			return redirect(peerListenerFull, nil)
		}, "listen queue of port", peerTries},
		{"the connection ended", func(h *fakeHost) func(netip.AddrPort, netip.AddrPort) (peerState, error) {
			var dialed, own netip.AddrPort
			return func(server, client netip.AddrPort) (peerState, error) {
				if h.peerCalls > peerTries {
					if server != own || client != dialed {
						t.Errorf("asked about %s from %s, want the guard's own end %s from %s", server, client, own, dialed)
					}
					return peerListener, nil
				}
				dialed, own = server, client
				return peerListener, nil
			}
		}, "ended before the agent could tell", peerTries + 1},
		{"the guard's own socket cannot be told", func(*fakeHost) func(netip.AddrPort, netip.AddrPort) (peerState, error) {
			var dialed netip.AddrPort
			return func(server, client netip.AddrPort) (peerState, error) {
				if !dialed.IsValid() {
					dialed = server
				}
				if server == dialed {
					return peerNone, nil
				}
				return peerNone, errors.New("sock_diag: permission denied")
			}
		}, "cannot be told", peerTries + 1},
	} {
		t.Run(c.name, func(t *testing.T) {
			h := &fakeHost{}
			h.peer = c.peer(h)
			address, accepted := takenBy(t, h)
			_, err := NewGuard().DialContext(context.Background(), "tcp", address)
			if !errors.Is(err, ErrNotAllowed) || !strings.Contains(err.Error(), c.want) || strings.Contains(err.Error(), "taken by another socket") {
				t.Fatalf("dial = %v; want it refused: %s", err, c.want)
			}
			if h.peerCalls != c.wantCalls {
				t.Errorf("asked %d times, want %d", h.peerCalls, c.wantCalls)
			}
			(<-accepted).Close()

			h.peer = nil
			conn, err := NewGuard().DialContext(context.Background(), "tcp", address)
			if err != nil {
				t.Fatalf("the next dial = %v, want the port not remembered", err)
			}
			_ = conn.Close()
		})
	}
}

// TestGuardRemembersARedirectedPort: after a redirect took a connection to a port, the guard
// refuses the port before it connects, so the service behind the redirect sees no further
// connection, until redirectTTL has passed.
func TestGuardRemembersARedirectedPort(t *testing.T) {
	h := &fakeHost{peer: redirect(peerListener, nil)}
	address, accepted := takenBy(t, h)
	g := NewGuard()
	if _, err := g.DialContext(context.Background(), "tcp", address); !errors.Is(err, ErrNotAllowed) {
		t.Fatalf("first dial = %v, want it refused", err)
	}
	(<-accepted).Close()

	calls := h.peerCalls
	for i := 0; i < 2; i++ {
		_, err := NewGuard().DialContext(context.Background(), "tcp", address)
		if !errors.Is(err, ErrNotAllowed) || !strings.Contains(err.Error(), "taken by another socket") {
			t.Fatalf("dial %d after the redirect = %v, want it refused", i+2, err)
		}
	}
	if h.peerCalls != calls {
		t.Errorf("asked the kernel %d more times, want the port refused before the connect", h.peerCalls-calls)
	}
	select {
	case c := <-accepted:
		c.Close()
		t.Fatal("the guard connected again to a port a redirect took")
	case <-time.After(100 * time.Millisecond):
	}

	h.peer = nil
	redirected.Lock()
	for k := range redirected.at {
		redirected.at[k] = redirected.at[k].Add(-redirectTTL)
	}
	redirected.Unlock()
	conn, err := g.DialContext(context.Background(), "tcp", address)
	if err != nil {
		t.Fatalf("dial after redirectTTL: %v, want it connected", err)
	}
	_ = conn.Close()
}

// TestGuardWaitsForTheKernelToListTheTaker: the socket that took a connection may show a moment
// after the connect returns.
func TestGuardWaitsForTheKernelToListTheTaker(t *testing.T) {
	h := &fakeHost{}
	h.peer = func(server, client netip.AddrPort) (peerState, error) {
		if h.peerCalls < peerTries {
			return peerNone, nil
		}
		return peerConnected, nil
	}
	address, _ := takenBy(t, h)
	conn, err := NewGuard().DialContext(context.Background(), "tcp", address)
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	_ = conn.Close()
}

// TestGuardAsksAboutTheConnectionsOwnEnds: the guard asks for the socket bound to the address it
// dialed, with the connection's local end as the remote one.
func TestGuardAsksAboutTheConnectionsOwnEnds(t *testing.T) {
	h := &fakeHost{}
	var gotServer, gotClient netip.AddrPort
	h.peer = func(server, client netip.AddrPort) (peerState, error) {
		gotServer, gotClient = server, client
		return peerConnected, nil
	}
	address, _ := takenBy(t, h)
	conn, err := NewGuard().DialContext(context.Background(), "tcp", address)
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	defer conn.Close()
	if gotServer.String() != address || gotClient != conn.LocalAddr().(*net.TCPAddr).AddrPort() {
		t.Errorf("asked about %s from %s, want %s from %s", gotServer, gotClient, address, conn.LocalAddr())
	}
}

// TestGuardLeavesTheTakerOfContainersAndUnsupportedHostsAlone: a container's sockets and docker's
// published ports live in another network namespace, and a host without sock_diag cannot tell.
func TestGuardLeavesTheTakerOfContainersAndUnsupportedHostsAlone(t *testing.T) {
	refuse := func(netip.AddrPort, netip.AddrPort) (peerState, error) { return peerNone, nil }

	h := &fakeHost{peer: refuse}
	address, _ := takenBy(t, h)
	if conn, err := NewGuard(netip.MustParseAddr("127.0.0.1")).DialContext(context.Background(), "tcp", address); err != nil {
		t.Errorf("a container's address: %v, want it connected", err)
	} else {
		_ = conn.Close()
	}
	if h.peerCalls != 0 {
		t.Errorf("asked %d times about a container's address, want never", h.peerCalls)
	}

	h = &fakeHost{peer: refuse}
	address, _ = takenBy(t, h)
	port := netip.MustParseAddrPort(address).Port()
	h.pubs = []publication{pub("", port, 8080)}
	if conn, err := NewGuard().DialContext(context.Background(), "tcp", address); err != nil {
		t.Errorf("a port docker publishes: %v, want it connected", err)
	} else {
		_ = conn.Close()
	}
	if h.peerCalls != 0 {
		t.Errorf("asked %d times about a published port, want never", h.peerCalls)
	}

	h = &fakeHost{peer: func(netip.AddrPort, netip.AddrPort) (peerState, error) { return peerNone, errPeerUnsupported }}
	address, _ = takenBy(t, h)
	if conn, err := NewGuard().DialContext(context.Background(), "tcp", address); err != nil {
		t.Errorf("a host without sock_diag: %v, want it connected", err)
	} else {
		_ = conn.Close()
	}
}

// TestGuardNeverProbesAPortAForwardingServiceListensOn: Windows forwards ports with netsh portproxy
// through the process of the service iphlpsvc, a svchost no name tells apart (R-1370).
func TestGuardNeverProbesAPortAForwardingServiceListensOn(t *testing.T) {
	h := &fakeHost{
		list:     []listener{lst("127.0.0.1", 8080, 90), lst("127.0.0.1", 8081, 91)},
		names:    map[int32]string{90: "svchost.exe", 91: "svchost.exe"},
		services: map[int32]string{90: "iphlpsvc"},
	}
	stubHost(t, h)
	g := NewGuard()
	if err := allowed(g, "tcp4", "127.0.0.1:8080"); !errors.Is(err, ErrNotAllowed) ||
		!strings.Contains(err.Error(), "port 8080 belongs to the service iphlpsvc, which forwards") {
		t.Errorf("a portproxy port: %v, want it refused", err)
	}
	if err := allowed(g, "tcp4", "127.0.0.1:8081"); err != nil {
		t.Errorf("another svchost: %v, want it allowed", err)
	}

	h.servicesErr = errors.New("access is denied")
	if err := allowed(g, "tcp4", "127.0.0.1:8081"); !errors.Is(err, ErrNotAllowed) || !strings.Contains(err.Error(), "cannot be read") {
		t.Errorf("an unreadable service manager: %v, want it refused", err)
	}
}

// TestGuardChecksTheTargetAfreshBeforeASecret: a guard for a connection with a secret judges on a
// snapshot at most listenerFresh old and lets only a listener of the target's rule take it (R-1425).
func TestGuardChecksTheTargetAfreshBeforeASecret(t *testing.T) {
	h := &fakeHost{list: []listener{lst("0.0.0.0", 8090, 50)}, names: map[int32]string{50: "java", 60: "nginx"}}
	stubHost(t, h)
	ep := endpoint{addr: netip.MustParseAddr("127.0.0.1"), port: 8090, owns: func() func(listener) bool {
		return func(l listener) bool { return l.pid == 50 }
	}}
	age := func() {
		snapshot.Lock()
		snapshot.at = snapshot.at.Add(-2 * listenerFresh)
		snapshot.Unlock()
	}

	if err := allowed(secretGuard(ep), "tcp4", "127.0.0.1:8090"); err != nil {
		t.Fatalf("the target itself: %v, want it allowed", err)
	}

	// Another process took the port since the snapshot: the plain guard still judges on it, the
	// guard for a secret reads a new one and refuses.
	h.list = []listener{lst("0.0.0.0", 8090, 60)}
	age()
	calls := h.listCalls
	if err := allowed(NewGuard(), "tcp4", "127.0.0.1:8090"); err != nil || h.listCalls != calls {
		t.Fatalf("plain guard: %v after %d reads, want it allowed on the snapshot it has", err, h.listCalls-calls)
	}
	if err := allowed(secretGuard(ep), "tcp4", "127.0.0.1:8090"); !errors.Is(err, ErrNotAllowed) {
		t.Fatalf("another process on the port: %v, want ErrNotAllowed", err)
	}
	if h.listCalls == calls {
		t.Error("the guard for a secret judged without a new snapshot")
	}

	// A second socket that carries the address, of another process, may take the connection too.
	h.list = []listener{lst("0.0.0.0", 8090, 50), lst("127.0.0.1", 8090, 60)}
	age()
	if err := allowed(secretGuard(ep), "tcp4", "127.0.0.1:8090"); !errors.Is(err, ErrNotAllowed) {
		t.Fatalf("a second listener of another process: %v, want ErrNotAllowed", err)
	}
	// One on another address does not.
	h.list = []listener{lst("0.0.0.0", 8090, 50), lst("192.0.2.10", 8090, 60)}
	age()
	if err := allowed(secretGuard(ep), "tcp4", "127.0.0.1:8090"); err != nil {
		t.Fatalf("a listener on another address: %v, want it allowed", err)
	}

	// The target has gone: no listener left.
	h.list = nil
	age()
	if err := allowed(secretGuard(ep), "tcp4", "127.0.0.1:8090"); err == nil {
		t.Fatal("no listener: allowed, want an error")
	}

	// A port docker forwards goes to a container, not to the target.
	h.list = []listener{lst("0.0.0.0", 8090, 50)}
	h.pubs = []publication{{hostPort: 8090, to: 8080}}
	age()
	publications.Lock()
	publications.at = publications.at.Add(-2 * listenerFresh)
	publications.Unlock()
	if err := allowed(secretGuard(ep), "tcp4", "127.0.0.1:8090"); !errors.Is(err, ErrNotAllowed) {
		t.Fatalf("a published port: %v, want ErrNotAllowed", err)
	}
	if err := allowed(NewGuard(), "tcp4", "127.0.0.1:8090"); err != nil {
		t.Fatalf("plain guard on a published port: %v, want it allowed", err)
	}

	// Without a rule (a loopback target) the fresh snapshot alone is asked.
	h.pubs = nil
	h.list = []listener{lst("0.0.0.0", 8090, 60)}
	age()
	if err := allowed(secretGuard(endpoint{addr: ep.addr, port: ep.port}), "tcp4", "127.0.0.1:8090"); err != nil {
		t.Fatalf("no rule: %v, want it allowed", err)
	}
}
