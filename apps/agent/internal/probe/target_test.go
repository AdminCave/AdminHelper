// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"encoding/json"
	"errors"
	"net"
	"net/netip"
	"os"
	"slices"
	"strings"
	"testing"
	"time"
)

// freshSnapshot drops the snapshot of the listeners, before and after the test, so that it reads this
// host's own.
func freshSnapshot(t *testing.T) {
	t.Helper()
	reset := func() {
		snapshot.Lock()
		snapshot.list, snapshot.at = nil, time.Time{}
		snapshot.Unlock()
	}
	reset()
	t.Cleanup(reset)
}

func TestTargetOfTakesOnlyTheKindsOfTheSensorWithWhatTheyNeed(t *testing.T) {
	long := strings.Repeat("ä", maxNameRunes)
	cases := []struct {
		name  string
		kinds []string
		t     *Target
		ok    bool
	}{
		{"no target", []string{kindPort}, nil, false},
		{"another kind", []string{kindPort}, &Target{Kind: kindProcess, Name: "nginx"}, false},
		{"an unknown kind", []string{kindPort, "bogus"}, &Target{Kind: "bogus", Name: "x"}, false},
		{"port", []string{kindPort}, &Target{Kind: kindPort, PortHint: 8080}, true},
		{"port without hint", []string{kindPort}, &Target{Kind: kindPort}, false},
		{"port hint too big", []string{kindPort}, &Target{Kind: kindPort, PortHint: 65536}, false},
		{"port hint negative", []string{kindProcess}, &Target{Kind: kindProcess, Name: "nginx", PortHint: -1}, false},
		{"loopback", []string{kindLoopback}, &Target{Kind: kindLoopback, PortHint: 65535}, true},
		{"loopback without hint", []string{kindLoopback}, &Target{Kind: kindLoopback}, false},
		{"process", []string{kindProcess}, &Target{Kind: kindProcess, Name: "php-fpm8.3", PortHint: 9000}, true},
		{"process of the longest name", []string{kindProcess}, &Target{Kind: kindProcess, Name: long}, true},
		{"process of too long a name", []string{kindProcess}, &Target{Kind: kindProcess, Name: long + "a"}, false},
		{"process without name", []string{kindProcess}, &Target{Kind: kindProcess}, false},
		{"process as a path", []string{kindProcess}, &Target{Kind: kindProcess, Name: "/usr/sbin/nginx"}, false},
		{"process as a windows path", []string{kindProcess}, &Target{Kind: kindProcess, Name: `bin\nginx.exe`}, false},
		{"process with a control character", []string{kindProcess}, &Target{Kind: kindProcess, Name: "ngi\nnx"}, false},
		{"unit", []string{kindUnit}, &Target{Kind: kindUnit, Name: "nginx.service"}, true},
		{"unit with a blank", []string{kindUnit}, &Target{Kind: kindUnit, Name: "nginx service"}, false},
		{"unit with a semicolon", []string{kindUnit}, &Target{Kind: kindUnit, Name: "a;b"}, false},
		{"container", []string{kindContainer}, &Target{Kind: kindContainer, Name: "mailcow_postfix-1"}, true},
		{"container starting with a dash", []string{kindContainer}, &Target{Kind: kindContainer, Name: "-x"}, false},
		{"container with a slash", []string{kindContainer}, &Target{Kind: kindContainer, Name: "a/b"}, false},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got, err := targetOf(Probe{Sensor: "s", Target: c.t}, c.kinds...)
			if c.ok {
				if err != nil || got != *c.t {
					t.Fatalf("targetOf = %+v, %v; want the target", got, err)
				}
				return
			}
			if !errors.Is(err, ErrInvalid) {
				t.Fatalf("targetOf = %+v, %v; want ErrInvalid", got, err)
			}
		})
	}
}

func TestNoTargetAndNoParams(t *testing.T) {
	if err := noTarget(Probe{Sensor: "certfile"}); err != nil {
		t.Errorf("noTarget without a target = %v", err)
	}
	if err := noTarget(Probe{Sensor: "certfile", Target: &Target{Kind: kindLoopback, PortHint: 1}}); !errors.Is(err, ErrInvalid) {
		t.Errorf("noTarget with a target = %v, want ErrInvalid", err)
	}
	if err := noParams(Probe{Sensor: "unit"}); err != nil {
		t.Errorf("noParams without params = %v", err)
	}
	err := noParams(Probe{Sensor: "unit", Params: map[string]any{"b": 1, "a": "x"}})
	if !errors.Is(err, ErrInvalid) || !strings.HasSuffix(err.Error(), "got a, b") {
		t.Errorf("noParams with params = %v, want ErrInvalid naming a, b", err)
	}
}

func TestPathParamTakesOneAbsolutePath(t *testing.T) {
	longest := "/" + strings.Repeat("a", maxPathBytes-1)
	for _, ok := range []string{"/etc/ssl/certs/x.pem", longest} {
		got, err := pathParam(Probe{Sensor: "file_age", Params: map[string]any{"path": ok}})
		if err != nil || got != ok {
			t.Errorf("pathParam(%.20q) = %q, %v; want the path", ok, got, err)
		}
	}
	for name, params := range map[string]map[string]any{
		"none":            nil,
		"relative":        {"path": "etc/x"},
		"not a string":    {"path": 5},
		"too long":        {"path": longest + "a"},
		"with NUL":        {"path": "/etc/x\x00y"},
		"another key too": {"path": "/etc/x", "mode": "r"},
		"the root alone":  {"path": "/"},
		"a share":         {"path": "//host/share/x"},
		"a pipe":          {"path": "//./pipe/x"},
		"a device path":   {"path": "//?/C:/x"},
		"out of the root": {"path": "/../etc/x"},
		"out by a detour": {"path": "/etc/../../x"},
	} {
		if _, err := pathParam(Probe{Sensor: "file_age", Params: params}); !errors.Is(err, ErrInvalid) {
			t.Errorf("pathParam %s = %v, want ErrInvalid", name, err)
		}
	}
}

func TestPickPortTakesTheHintElseTheOnlyPort(t *testing.T) {
	two := []listener{lst("0.0.0.0", 443, 1), lst("::", 443, 1), lst("127.0.0.1", 80, 1)}
	cases := []struct {
		name string
		ls   []listener
		hint int
		want uint16
		err  error
	}{
		{"the hint among several", two, 80, 80, nil},
		{"the only port, the hint elsewhere", two[:2], 8443, 443, nil},
		{"the only port without hint", two[:2], 0, 443, nil},
		{"several without the hint", two, 8080, 0, ErrAmbiguousTarget},
		{"none", nil, 80, 0, errNotListening},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got, err := pickPort(c.ls, Target{Kind: kindProcess, Name: "nginx", PortHint: c.hint})
			if got != c.want || !errors.Is(err, c.err) || (c.err == nil) != (err == nil) {
				t.Fatalf("pickPort = %d, %v; want %d, %v", got, err, c.want, c.err)
			}
		})
	}
	_, err := pickPort(two, Target{Kind: kindProcess, Name: "nginx"})
	if want := "process nginx listens on ports 80, 443 and none is the hint 0"; !strings.HasSuffix(err.Error(), want) {
		t.Errorf("error = %q, want it to end in %q", err, want)
	}
	_, err = pickPort(nil, Target{Kind: kindPort, PortHint: 8080})
	if want := "port 8080 listens on no TCP port"; err.Error() != want {
		t.Errorf("error = %q, want %q", err, want)
	}
}

func TestDialAddrPrefersLoopback(t *testing.T) {
	a := netip.MustParseAddr
	cases := []struct {
		name     string
		ls       []listener
		fallback []netip.Addr
		want     netip.Addr
	}{
		{"loopback before another", []listener{lst("192.0.2.1", 80, 1), lst("127.0.0.1", 80, 1)}, nil, a("127.0.0.1")},
		{"IPv4 any as loopback", []listener{lst("192.0.2.1", 80, 1), lst("0.0.0.0", 80, 1)}, nil, a("127.0.0.1")},
		{"IPv6 any as loopback", []listener{lst("::", 80, 1)}, nil, a("::1")},
		{"the lowest of others", []listener{lst("192.0.2.9", 80, 1), lst("192.0.2.1", 80, 1)}, nil, a("192.0.2.1")},
		{"the lowest loopback", []listener{lst("::1", 80, 1), lst("127.0.0.1", 80, 1)}, nil, a("127.0.0.1")},
		{"only the port", []listener{lst("127.0.0.1", 81, 1), lst("192.0.2.1", 80, 1)}, nil, a("192.0.2.1")},
		{"any as the fallback", []listener{lst("0.0.0.0", 80, 1)}, []netip.Addr{a("192.0.2.5"), a("2001:db8::5")}, a("192.0.2.5")},
		{"none", []listener{lst("127.0.0.1", 81, 1)}, nil, netip.Addr{}},
	}
	for _, c := range cases {
		if got := dialAddr(c.ls, 80, c.fallback); got != c.want {
			t.Errorf("%s: dialAddr = %v, want %v", c.name, got, c.want)
		}
	}
}

func TestParseProcNetTCPReadsTheListeningSockets(t *testing.T) {
	// The kernel's format on a little-endian host, the only kind the agent is built for.
	tcp := `  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
   0: 0100007F:0CEA 00000000:0000 0A 00000000:00000000 00:00000000 00000000   113        0 2001 1 0000000000000000 100 0 0 10 0
   1: 00000000:1F90 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 2002 1 0000000000000000 100 0 0 10 0
   2: 0100007F:0050 0100007F:A1B2 01 00000000:00000000 00:00000000 00000000     0        0 2003 1 0000000000000000 20 4 30 10 -1
   3: 0A0200C0:01BB 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 2004 1 0000000000000000 100 0 0 10 0
   4: 0A0200C0:XYZW 00000000:0000 0A
   5: 0A02:01BB 00000000:0000 0A
`
	tcp6 := `  sl  local_address                         remote_address                        st tx_queue rx_queue
   0: 00000000000000000000000001000000:1F90 00000000000000000000000000000000:0000 0A 00000000:00000000
   1: 00000000000000000000000000000000:0016 00000000000000000000000000000000:0000 0A 00000000:00000000
   2: 0000000000000000FFFF00000A0200C0:01BB 00000000000000000000000000000000:0000 0A 00000000:00000000
   3: B80D0120000000000000000005000000:0050 00000000000000000000000000000000:0000 0A 00000000:00000000
`
	want := []listener{
		lst("127.0.0.1", 3306, 0), lst("0.0.0.0", 8080, 0), lst("192.0.2.10", 443, 0),
		lst("::1", 8080, 0), lst("::", 22, 0), lst("192.0.2.10", 443, 0), lst("2001:db8::5", 80, 0),
	}
	got := append(parseProcNetTCP([]byte(tcp)), parseProcNetTCP([]byte(tcp6))...)
	if !slices.Equal(got, want) {
		t.Fatalf("parseProcNetTCP = %v, want %v", got, want)
	}
	if got := parseProcNetTCP(nil); len(got) != 0 {
		t.Errorf("parseProcNetTCP(nil) = %v, want none", got)
	}
}

func TestParseSockstatReadsTheListeningSockets(t *testing.T) {
	// sockstat -46lnq -P tcp of FreeBSD 14.3: a COMMAND with a blank, an owner sockstat cannot tell,
	// IPv6 without brackets, a v4-mapped address, a socket of a TCP offload engine and one bound
	// without a port.
	out := `0        nginx      1234  6  tcp4   *:443                 *:*
0        nginx      1234  7  tcp6   *:443                 *:*
80       my daemon  2001  9  tcp4   127.0.0.1:9000        *:*
?        ?          ?     ?  tcp46  *:8080                *:*
59       unbound    77    5  tcp6   ::1:53                *:*
0        lighttpd   88    4  toe4   192.0.2.10:8443       *:*
0        haproxy    99    3  tcp6   ::ffff:192.0.2.10:81  *:*
0        sshd       100   3  tcp4   *:*                   *:*

`
	want := []listener{
		lst("0.0.0.0", 443, 1234), lst("::", 443, 1234), lst("127.0.0.1", 9000, 2001), lst("::", 8080, 0),
		lst("::1", 53, 77), lst("192.0.2.10", 8443, 88), lst("192.0.2.10", 81, 99),
	}
	got, err := parseSockstat([]byte(out))
	if err != nil || !slices.Equal(got, want) {
		t.Fatalf("parseSockstat = %v, %v, want %v", got, err, want)
	}
	if got, err := parseSockstat(nil); err != nil || len(got) != 0 {
		t.Errorf("parseSockstat(nil) = %v, %v, want none", got, err)
	}
}

func TestParseSockstatFailsOnALineOfAnotherForm(t *testing.T) {
	good := "0 nginx 1234 6 tcp4 *:443 *:*\n"
	for _, line := range []string{
		"0 nginx 1234 6 tcp4 *:443",             // a column short
		"0 nginx x 6 tcp4 *:443 *:*",            // a pid that is none
		"0 nginx 0 6 tcp4 *:443 *:*",            // pid 0
		"0 nginx 1234 6 udp4 *:53 *:*",          // another protocol
		"0 nginx 1234 6 tcp5 *:443 *:*",         // another family
		"0 nginx 1234 6 tcp4 443 *:*",           // no port
		"0 nginx 1234 6 tcp4 *:0 *:*",           // port 0
		"0 nginx 1234 6 tcp4 *:65536 *:*",       // a port past 16 bits
		"0 nginx 1234 6 tcp4 300.1.2.3:443 *:*", // an address that is none
	} {
		if got, err := parseSockstat([]byte(good + line + "\n")); err == nil || !strings.Contains(err.Error(), "line 2 ") {
			t.Errorf("parseSockstat(%q) = %v, %v, want line 2 refused", line, got, err)
		}
	}
}

func TestCgroupHasReadsEveryHierarchy(t *testing.T) {
	v1 := []byte("12:pids:/system.slice/docker-abc.scope\n1:name=systemd:/system.slice/docker-abc.scope\n")
	v2 := []byte("0::/system.slice/nginx.service\n")
	is := func(want string) func(string) bool { return func(p string) bool { return p == want } }
	if !cgroupHas(v1, is("/system.slice/docker-abc.scope")) || !cgroupHas(v2, is("/system.slice/nginx.service")) {
		t.Error("cgroupHas misses the cgroup of a v1 or v2 file")
	}
	if cgroupHas(v2, is("/system.slice")) || cgroupHas(nil, is("")) || cgroupHas([]byte("garbage"), is("")) {
		t.Error("cgroupHas matches what the file does not name")
	}
}

func TestContainerInfoReadsDockerInspect(t *testing.T) {
	var list []containerInfo
	if err := json.Unmarshal([]byte(inspectJSON(t, "running", "healthy", "bridge")), &list); err != nil || len(list) != 1 {
		t.Fatalf("unmarshal = %v, %d entries", err, len(list))
	}
	c := list[0]
	if c.ID != containerID || c.RestartCount != 3 || c.State.Pid != 4242 || !c.State.Running || c.State.Health.Status != "healthy" {
		t.Fatalf("containerInfo = %+v", c)
	}
	want := []netip.Addr{netip.MustParseAddr("192.0.2.5"), netip.MustParseAddr("192.0.2.6"), netip.MustParseAddr("2001:db8::5")}
	if got := c.addrs(); !slices.Equal(got, want) {
		t.Errorf("addrs = %v, want %v: IPv4 first, each once, none empty", got, want)
	}
}

func TestResolveFindsWhereATargetListens(t *testing.T) {
	h := &fakeHost{
		list: []listener{
			lst("0.0.0.0", 443, 7), lst("::", 443, 7), lst("127.0.0.1", 80, 8), lst("192.0.2.1", 8080, 9),
			lst("0.0.0.0", 22, 0), lst("127.0.0.1", 9000, 10),
		},
		names: map[int32]string{7: "nginx", 8: "Nginx.EXE", 9: "java", 10: "php-fpm"},
	}
	stubHost(t, h)
	ctx := context.Background()
	cases := []struct {
		name string
		t    Target
		want string
		err  error
	}{
		{"a port", Target{Kind: kindPort, PortHint: 443}, "127.0.0.1:443", nil},
		{"a port on another address", Target{Kind: kindPort, PortHint: 8080}, "192.0.2.1:8080", nil},
		{"a port nobody listens on", Target{Kind: kindPort, PortHint: 8081}, "", errNotListening},
		{"a process of any case, with .exe", Target{Kind: kindProcess, Name: "nginx", PortHint: 80}, "127.0.0.1:80", nil},
		{"a process of several ports", Target{Kind: kindProcess, Name: "NGINX"}, "", ErrAmbiguousTarget},
		{"a process of one port", Target{Kind: kindProcess, Name: "php-fpm", PortHint: 9001}, "127.0.0.1:9000", nil},
		{"a process listening nowhere", Target{Kind: kindProcess, Name: "sshd"}, "", errNotListening},
		{"loopback", Target{Kind: kindLoopback, PortHint: 6379}, "127.0.0.1:6379", nil},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			ep, err := resolve(ctx, c.t)
			if !errors.Is(err, c.err) || (c.err == nil) != (err == nil) {
				t.Fatalf("resolve = %v, %v; want %v", ep, err, c.err)
			}
			if c.err == nil && netip.AddrPortFrom(ep.addr, ep.port).String() != c.want {
				t.Errorf("resolve = %v:%d, want %s", ep.addr, ep.port, c.want)
			}
		})
	}
	if h.listCalls != 1 {
		t.Errorf("the listeners were read %d times, want once for the snapshot", h.listCalls)
	}

	h.listErr = errors.New("netlink: permission denied")
	stubHost(t, h)
	if _, err := resolve(ctx, Target{Kind: kindLoopback, PortHint: 1}); err != nil {
		t.Errorf("resolve(loopback) = %v, want it without reading the listeners", err)
	}
	if _, err := resolve(ctx, Target{Kind: kindPort, PortHint: 443}); err == nil || !strings.Contains(err.Error(), "cannot be read") {
		t.Errorf("resolve without listeners = %v, want an error", err)
	}
}

func TestResolveFindsAListenerOfThisHost(t *testing.T) {
	ln, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer ln.Close()
	port := ln.Addr().(*net.TCPAddr).Port
	freshSnapshot(t)
	ctx := context.Background()

	ep, err := resolve(ctx, Target{Kind: kindPort, PortHint: port})
	if err != nil || ep.addr != netip.MustParseAddr("127.0.0.1") || int(ep.port) != port {
		t.Fatalf("resolve(port %d) = %v:%d, %v", port, ep.addr, ep.port, err)
	}
	name, err := nameOf(ctx, int32(os.Getpid()))
	if err != nil {
		t.Fatal(err)
	}
	ep, err = resolve(ctx, Target{Kind: kindProcess, Name: name, PortHint: port})
	if err != nil || int(ep.port) != port {
		t.Fatalf("resolve(process %s) = %v:%d, %v; want its port %d", name, ep.addr, ep.port, err, port)
	}
}

func TestSocketSensorSaysWhetherAndWhereTheTargetListens(t *testing.T) {
	stubHost(t, &fakeHost{
		list:  []listener{lst("0.0.0.0", 443, 7), lst("0.0.0.0", 80, 7), lst("127.0.0.1", 5432, 8)},
		names: map[int32]string{7: "nginx", 8: "postgres"},
	})
	run := func(target Target) Result {
		p := Probe{ID: "s1", Sensor: "socket", Target: &target, TimeoutS: 5, Fields: []string{"listening", "port"}}
		return Run(context.Background(), p, start, nil)
	}
	res := run(Target{Kind: kindProcess, Name: "postgres"})
	if res.Status != StatusOK || res.Values["listening"] != true || res.Values["port"] != 5432 {
		t.Errorf("postgres = %+v, want listening on 5432", res)
	}
	res = run(Target{Kind: kindPort, PortHint: 6379})
	if res.Status != StatusOK || res.Values["listening"] != false || len(res.Values) != 1 {
		t.Errorf("port 6379 = %+v, want not listening and no port", res)
	}
	res = run(Target{Kind: kindProcess, Name: "nginx"})
	if res.Status != StatusAmbiguousTarget || !strings.Contains(res.Error, "80, 443") {
		t.Errorf("nginx = %+v, want ambiguous between 80 and 443", res)
	}
	res = run(Target{Kind: kindLoopback, PortHint: 80})
	if res.Status != StatusInvalid {
		t.Errorf("a loopback target = %+v, want invalid: the socket sensor reads listeners", res)
	}
}
