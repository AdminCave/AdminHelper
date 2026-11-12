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
}

// stubHost puts h in for the guard's seams and starts without a snapshot of the listeners.
func stubHost(t *testing.T, h *fakeHost) {
	t.Helper()
	oldAddrs, oldList, oldName, oldArgs, oldPubs := interfaceAddrs, listeners, processName, processArgs, publishedPorts
	interfaceAddrs = func() ([]net.Addr, error) { return h.addrs, h.addrsErr }
	publishedPorts = func(context.Context) ([]publication, error) {
		h.pubsCalls++
		return h.pubs, h.pubsErr
	}
	listeners = func(context.Context) ([]listener, error) {
		h.listCalls++
		return h.list, h.listErr
	}
	processName = func(_ context.Context, pid int32) (string, error) {
		name, ok := h.names[pid]
		if !ok {
			return "", errors.New("access is denied")
		}
		return name, nil
	}
	processArgs = func(_ context.Context, pid int32) ([]string, error) {
		args, ok := h.args[pid]
		if !ok {
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
	}
	resetSnapshot()
	t.Cleanup(func() {
		interfaceAddrs, listeners, processName, processArgs, publishedPorts = oldAddrs, oldList, oldName, oldArgs, oldPubs
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
	}})
	g := NewGuard(netip.MustParseAddr("203.0.113.9"), netip.MustParseAddr("::ffff:203.0.113.10"))

	for _, c := range []struct{ network, address string }{
		{"tcp4", "127.0.0.1:8080"},
		{"tcp4", "127.1.2.3:8080"},
		{"tcp6", "[::1]:8080"},
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
	stubHost(t, &fakeHost{addrsErr: errors.New("netlink refused")})
	g := NewGuard()

	if err := allowed(g, "tcp4", "192.0.2.10:80"); !errors.Is(err, ErrNotAllowed) {
		t.Errorf("an address of this host it cannot read: %v, want ErrNotAllowed", err)
	}
	if err := allowed(g, "tcp4", "127.0.0.1:80"); err != nil {
		t.Errorf("loopback: %v, want it allowed without the list", err)
	}
}

func TestGuardNeverProbesTheBlockedPorts(t *testing.T) {
	stubHost(t, &fakeHost{})
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
	if err := allowed(g, "tcp4", "127.0.0.1:8082"); err != nil {
		t.Errorf("a port without a listener: %v, want it allowed (no process to ask)", err)
	}
	if h.listCalls != 2 {
		t.Errorf("listeners read %d times, want the failed read and one snapshot", h.listCalls)
	}
}

// TestGuardFailsClosedOnASocketSystemdHoldsAlone: a socket systemd listens on for socket activation
// tells nothing of the service behind it until that runs and holds the socket too.
func TestGuardFailsClosedOnASocketSystemdHoldsAlone(t *testing.T) {
	stubHost(t, &fakeHost{
		list: []listener{
			lst("127.0.0.1", 2222, 1), lst("0.0.0.0", 5000, 900),
			lst("127.0.0.1", 631, 1), lst("127.0.0.1", 631, 30),
			lst("0.0.0.0", 16509, 1), lst("0.0.0.0", 16509, 31),
		},
		names: map[int32]string{1: "systemd", 900: "systemd", 30: "cupsd", 31: "libvirtd"},
	})
	g := NewGuard()

	for _, c := range []struct{ address, want string }{
		{"127.0.0.1:2222", "socket activation"},
		{"127.0.0.1:5000", "socket activation"},
		{"127.0.0.1:16509", "libvirtd"},
	} {
		if err := allowed(g, "tcp4", c.address); !errors.Is(err, ErrNotAllowed) || !strings.Contains(err.Error(), c.want) {
			t.Errorf("%s: %v, want ErrNotAllowed with %q", c.address, err, c.want)
		}
	}
	if err := allowed(g, "tcp4", "127.0.0.1:631"); err != nil {
		t.Errorf("a socket systemd and the service it started hold: %v, want it allowed", err)
	}
}

func TestGuardReadsTheListenersOncePerSnapshot(t *testing.T) {
	h := &fakeHost{}
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

// localServer serves h on 127.0.0.1 and lets the guard's seams see an empty host.
func localServer(t *testing.T, h http.Handler) *httptest.Server {
	t.Helper()
	stubHost(t, &fakeHost{})
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
		list:  []listener{lst("127.0.0.1", 18080, 50)},
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
		{"127.0.0.1:8080", false},
		{"127.0.0.1:9999", false},
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
		if err := allowed(g, "tcp4", "127.0.0.1:9999"); err != nil {
			t.Fatal(err)
		}
	}
	if h.pubsCalls != 1 {
		t.Fatalf("published ports read %d times, want once within %s", h.pubsCalls, listenerTTL)
	}
	publications.Lock()
	publications.at = publications.at.Add(-listenerTTL)
	publications.Unlock()
	if err := allowed(g, "tcp4", "127.0.0.1:9999"); err != nil {
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
