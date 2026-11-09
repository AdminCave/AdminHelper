// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package probe

import (
	"context"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"net/netip"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// socketIn is the path of a unix socket in a directory of the test.
func socketIn(t *testing.T) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "s.sock")
	if len(path) > maxSocketPath {
		t.Fatalf("%s is too long for a unix socket; run the tests with a shorter TMPDIR", path)
	}
	return path
}

// unixFake serves serve on a unix socket and returns its path.
func unixFake(t *testing.T, serve func(*fakeConn)) (string, *fake) {
	t.Helper()
	path := socketIn(t)
	ln, err := net.Listen("unix", path)
	if err != nil {
		t.Fatal(err)
	}
	return path, serveOn(t, ln, serve)
}

// servedBy names the process of the test, which serves the sockets of the test, name.
func servedBy(t *testing.T, name string) *fakeHost {
	t.Helper()
	h := &fakeHost{names: map[int32]string{int32(os.Getpid()): name}}
	stubHost(t, h)
	return h
}

func unixProbe(params map[string]any, fields ...string) Probe {
	return Probe{Sensor: "unixsocket", Params: params, Fields: fields}
}

func TestUnixSocketSensorConnects(t *testing.T) {
	h := servedBy(t, "nginx")
	path, _ := unixFake(t, func(c *fakeConn) { c.drain() })
	ctx := context.Background()
	probe := func(path string) (map[string]any, error) {
		return unixSocketSensor(ctx, unixProbe(map[string]any{"path": path}), "")
	}

	got, err := probe(path)
	if took, ok := got["duration_ms"].(int64); err != nil || got["connected"] != true || !ok || took < 0 {
		t.Errorf("connect = %v, %v; want connected and its milliseconds", got, err)
	}
	if got, err := probe(path + ".gone"); err != nil || fmt.Sprint(got) != "map[connected:false]" {
		t.Errorf("a missing socket = %v, %v; want it not connected", got, err)
	}
	stale := socketIn(t)
	ln, err := net.ListenUnix("unix", &net.UnixAddr{Name: stale, Net: "unix"})
	if err != nil {
		t.Fatal(err)
	}
	ln.SetUnlinkOnClose(false)
	_ = ln.Close()
	if got, err := probe(stale); err != nil || fmt.Sprint(got) != "map[connected:false]" {
		t.Errorf("a socket nobody serves = %v, %v; want it not connected", got, err)
	}

	pid := int32(os.Getpid())
	for _, name := range []string{"dockerd", "containerd-shim-runc-v2", "systemd", "systemd-resolved", "sshd", "Podman.exe"} {
		h.names[pid] = name
		if _, err := probe(path); !errors.Is(err, ErrNotAllowed) || !strings.Contains(err.Error(), "belongs to "+name+", which the agent never probes") {
			t.Errorf("a socket of %s = %v, want it refused", name, err)
		}
	}
	h.names[pid] = "nginx-systemd"
	if _, err := probe(path); errors.Is(err, ErrNotAllowed) {
		t.Errorf("a socket of nginx-systemd = %v, want it allowed", err)
	}
	delete(h.names, pid)
	if _, err := probe(path); !errors.Is(err, ErrNotAllowed) || !strings.Contains(err.Error(), "cannot be read") {
		t.Errorf("a socket of a process the agent cannot read = %v, want it refused", err)
	}
}

func TestUnixSocketSensorSpeaksHTTP(t *testing.T) {
	servedBy(t, "nginx")
	path := socketIn(t)
	ln, err := net.Listen("unix", path)
	if err != nil {
		t.Fatal(err)
	}
	srv := &http.Server{
		Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			switch r.URL.Path {
			case "/health":
				_, _ = fmt.Fprint(w, `{"status":"ok","workers":{"busy":2}}`)
			case "/moved":
				http.Redirect(w, r, "/health", http.StatusFound)
			case "/away":
				http.Redirect(w, r, "http://192.0.2.1/", http.StatusFound)
			case "/secret":
				if r.Header.Get("Authorization") != "Bearer t0ken" {
					w.WriteHeader(http.StatusUnauthorized)
				}
			}
		}),
		ErrorLog: log.New(io.Discard, "", 0),
	}
	go func() { _ = srv.Serve(ln) }()
	t.Cleanup(func() { _ = srv.Close() })
	ctx := context.Background()
	probe := func(httpPath string, fields ...string) Probe {
		return unixProbe(map[string]any{"path": path, "protocol": "http", "http_path": httpPath}, fields...)
	}

	got, err := unixSocketSensor(ctx, probe("/health", "data.workers.busy"), "")
	data, _ := got["data"].(map[string]any)
	if err != nil || got["connected"] != true || got["status_code"] != 200 || data["status"] != "ok" {
		t.Errorf("GET /health = %v, %v; want 200 and its data", got, err)
	}
	if took, ok := got["duration_ms"].(int64); !ok || took < 0 {
		t.Errorf("duration_ms = %#v, want milliseconds", got["duration_ms"])
	}
	if got, err := unixSocketSensor(ctx, probe("/moved", "status_code"), ""); err != nil || got["status_code"] != 200 {
		t.Errorf("a redirect on the socket = %v, %v; want it followed", got, err)
	}
	if _, err := unixSocketSensor(ctx, probe("/away"), ""); !errors.Is(err, ErrNotAllowed) {
		t.Errorf("a redirect off the socket = %v, want ErrNotAllowed", err)
	}
	secret := probe("/secret")
	secret.Credential = &Credential{Ref: "c1", Use: useBearer}
	if got, err := unixSocketSensor(ctx, secret, "t0ken"); err != nil || got["status_code"] != 200 {
		t.Errorf("the bearer token = %v, %v; want 200", got, err)
	}
	if _, err := unixSocketSensor(ctx, secret, "wr0ng"); !errors.Is(err, ErrDenied) || strings.Contains(err.Error(), "wr0ng") {
		t.Errorf("a wrong token = %v, want ErrDenied without the token", err)
	}
}

func TestUnixSocketSensorSpeaksTheProtocolOfItsService(t *testing.T) {
	servedBy(t, "redis-server")
	ctx := context.Background()

	path, srv := unixFake(t, func(c *fakeConn) {
		for range 3 {
			c.hear()
		}
		c.say(redisInfoAnswer)
		c.hear()
	})
	got, err := unixSocketSensor(ctx, unixProbe(map[string]any{"path": path, "protocol": "redis"}, "data.role"), "")
	data, _ := got["data"].(map[string]any)
	if err != nil || got["connected"] != true || data["role"] != "master" {
		t.Errorf("redis = %v, %v; want its INFO", got, err)
	}
	if took, ok := got["duration_ms"].(int64); !ok || took < 0 {
		t.Errorf("duration_ms = %#v, want milliseconds", got["duration_ms"])
	}
	if heard := fmt.Sprint(srv.close()); heard != "[*1 $4 INFO]" {
		t.Errorf("redis heard %s", heard)
	}

	path, _ = unixFake(t, func(c *fakeConn) {
		for range 3 {
			c.hear()
		}
	})
	if _, err := unixSocketSensor(ctx, unixProbe(map[string]any{"path": path, "protocol": "redis"}), ""); err == nil || err.Error() != "redis: closed at INFO" {
		t.Errorf("a redis that closes = %v, want its detail as the error", err)
	}

	path, _ = unixFake(t, func(c *fakeConn) {
		if c.hear() == "show stat" {
			c.say("# pxname,svname,status,\nweb,FRONTEND,OPEN,\n")
		}
	})
	got, err = unixSocketSensor(ctx, unixProbe(map[string]any{"path": path, "protocol": "haproxy"}, "data.web.FRONTEND.status"), "")
	data, _ = got["data"].(map[string]any)
	if web, _ := data["web"].(map[string]any); err != nil || fmt.Sprint(web["FRONTEND"]) != "map[status:OPEN]" {
		t.Errorf("haproxy = %v, %v; want its stats", got, err)
	}
}

func TestUnixSocketSensorTakesItsParams(t *testing.T) {
	ctx := context.Background()
	withCredential := func(p Probe, use string) Probe {
		p.Credential = &Credential{Ref: "c1", Use: use}
		return p
	}
	const sock = "/run/app/app.sock"
	for _, c := range []struct {
		name string
		p    Probe
	}{
		{"no path", unixProbe(nil)},
		{"a relative path", unixProbe(map[string]any{"path": "run/app.sock"})},
		{"a path out of the root", unixProbe(map[string]any{"path": "/../run/app.sock"})},
		{"a path too long", unixProbe(map[string]any{"path": "/" + strings.Repeat("s", maxSocketPath)})},
		{"another protocol", unixProbe(map[string]any{"path": sock, "protocol": "smtp"})},
		{"an http_path without slash", unixProbe(map[string]any{"path": sock, "protocol": "http", "http_path": "health"})},
		{"a status_path of redis", unixProbe(map[string]any{"path": sock, "protocol": "redis", "status_path": "/status"})},
		{"a credential to connect", withCredential(unixProbe(map[string]any{"path": sock}), useBearer)},
		{"a password for http", withCredential(unixProbe(map[string]any{"path": sock, "protocol": "http"}), useRedisAuth)},
		{"another param", unixProbe(map[string]any{"path": sock, "port": 80})},
		{"a target", Probe{Sensor: "unixsocket", Target: &Target{Kind: kindLoopback, PortHint: 80}, Params: map[string]any{"path": sock}}},
	} {
		if _, err := unixSocketSensor(ctx, c.p, ""); !errors.Is(err, ErrInvalid) {
			t.Errorf("%s: %v, want ErrInvalid", c.name, err)
		}
	}
	if _, err := unixSocketSensor(ctx, unixProbe(map[string]any{"path": sock, "protocol": "fastcgi", "status_path": "/status"}), ""); !errors.Is(err, ErrUnsupported) {
		t.Errorf("the status page of FastCGI = %v, want ErrUnsupported", err)
	}
	longest := "/" + strings.Repeat("s", maxSocketPath-1)
	if got, err := unixSocketSensor(ctx, unixProbe(map[string]any{"path": longest}), ""); err != nil || got["connected"] != false {
		t.Errorf("a missing socket of the longest path = %v, %v; want it not connected", got, err)
	}
}

// rr is a record of the fake resolver.
type rr struct {
	rrtype uint16
	rdata  []byte
}

// wireName is name in the form of DNS on the wire.
func wireName(name string) []byte {
	var b []byte
	for _, l := range strings.Split(strings.TrimSuffix(name, "."), ".") {
		b = append(append(b, byte(len(l))), l...)
	}
	return append(b, 0)
}

// answerDNS answers query from zone: the records of the asked type or a CNAME in their place, no
// records for a name without that type, NXDOMAIN for a name zone lacks and SERVFAIL for
// servfail.example.org.
func answerDNS(query []byte, zone map[string][]rr) []byte {
	if len(query) < 12 {
		return nil
	}
	var labels []string
	i := 12
	for i < len(query) && query[i] != 0 {
		n := int(query[i])
		if i+1+n > len(query) {
			return nil
		}
		labels = append(labels, string(query[i+1:i+1+n]))
		i += 1 + n
	}
	if i+5 > len(query) {
		return nil
	}
	name := strings.ToLower(strings.Join(labels, ".")) + "."
	qtype := binary.BigEndian.Uint16(query[i+1:])
	records, found := zone[name]
	var rcode uint16
	switch {
	case name == "servfail.example.org.":
		rcode = 2
	case !found:
		rcode = 3
	}
	var answers []rr
	for _, r := range records {
		if r.rrtype == qtype || r.rrtype == 5 {
			answers = append(answers, r)
		}
	}
	// QR, AA, RD and RA.
	b := binary.BigEndian.AppendUint16(nil, binary.BigEndian.Uint16(query))
	b = binary.BigEndian.AppendUint16(b, 0x8580|rcode)
	b = binary.BigEndian.AppendUint16(b, 1)
	b = binary.BigEndian.AppendUint16(b, uint16(len(answers)))
	b = append(b, 0, 0, 0, 0)
	b = append(b, query[12:i+5]...)
	for _, r := range answers {
		b = append(b, 0xc0, 12)
		b = binary.BigEndian.AppendUint16(b, r.rrtype)
		b = binary.BigEndian.AppendUint16(b, 1)
		b = binary.BigEndian.AppendUint32(b, 60)
		b = binary.BigEndian.AppendUint16(b, uint16(len(r.rdata)))
		b = append(b, r.rdata...)
	}
	return b
}

// fakeResolver puts in a resolver of Go that asks a server on 127.0.0.1 answering from zone.
func fakeResolver(t *testing.T, zone map[string][]rr) {
	t.Helper()
	pc, err := net.ListenPacket("udp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	done := make(chan struct{})
	go func() {
		defer close(done)
		buf := make([]byte, 1500)
		for {
			n, addr, err := pc.ReadFrom(buf)
			if err != nil {
				return
			}
			if answer := answerDNS(buf[:n], zone); answer != nil {
				_, _ = pc.WriteTo(answer, addr)
			}
		}
	}()
	old := net.DefaultResolver
	net.DefaultResolver = &net.Resolver{PreferGo: true, Dial: func(ctx context.Context, _, _ string) (net.Conn, error) {
		var d net.Dialer
		return d.DialContext(ctx, "udp4", pc.LocalAddr().String())
	}}
	t.Cleanup(func() {
		net.DefaultResolver = old
		_ = pc.Close()
		<-done
	})
}

func TestDNSSensorAsksTheResolverOfThisHost(t *testing.T) {
	addr := func(s string) []byte { return netip.MustParseAddr(s).AsSlice() }
	pref := func(p uint16, host string) []byte {
		return append(binary.BigEndian.AppendUint16(nil, p), wireName(host)...)
	}
	srv := func(prio, weight, port uint16, host string) []byte {
		b := binary.BigEndian.AppendUint16(nil, prio)
		b = binary.BigEndian.AppendUint16(b, weight)
		return append(binary.BigEndian.AppendUint16(b, port), wireName(host)...)
	}
	fakeResolver(t, map[string][]rr{
		"svc.example.org.": {{1, addr("192.0.2.10")}, {1, addr("192.0.2.11")}, {28, addr("2001:db8::10")}},
		"example.org.": {
			{15, pref(10, "mail.example.org.")}, {15, pref(20, "mx2.example.org.")},
			{16, append([]byte{11}, "v=spf1 -all"...)},
			{2, wireName("ns1.example.org.")}, {2, wireName("ns2.example.org.")},
		},
		"alias.example.org.":       {{5, wireName("svc.example.org.")}},
		"_ldap._tcp.example.org.":  {{33, srv(0, 5, 389, "ldap.example.org.")}},
		"10.2.0.192.in-addr.arpa.": {{12, wireName("svc.example.org.")}},
	})
	ctx := context.Background()
	for _, c := range []struct{ rrtype, name, want string }{
		{"A", "svc.example.org.", "true 2"},
		{"AAAA", "svc.example.org.", "true 1"},
		{"MX", "example.org.", "true 2"},
		{"TXT", "example.org.", "true 1"},
		{"NS", "example.org.", "true 2"},
		{"SRV", "_ldap._tcp.example.org.", "true 1"},
		{"CNAME", "alias.example.org.", "true 1"},
		{"CNAME", "svc.example.org.", "false 0"},
		{"PTR", "192.0.2.10", "true 1"},
		{"PTR", "10.2.0.192.in-addr.arpa.", "true 1"},
		{"A", "missing.example.org.", "false 0"},
		{"AAAA", "example.org.", "false 0"},
	} {
		got, err := dnsSensor(ctx, dnsProbe(map[string]any{"rrtype": c.rrtype, "name": c.name}), "")
		if s := fmt.Sprintf("%v %v", got["resolved"], got["answers"]); err != nil || s != c.want {
			t.Errorf("%s %s = %v, %v; want resolved and answers %s", c.rrtype, c.name, got, err, c.want)
		}
	}
	if got, err := dnsSensor(ctx, dnsProbe(map[string]any{"name": "servfail.example.org."}), ""); err == nil {
		t.Errorf("a failing resolver = %v, want an error", got)
	}
}

func TestDNSSensorResolvesLocalhost(t *testing.T) {
	got, err := dnsSensor(context.Background(), dnsProbe(map[string]any{"name": "localhost"}), "")
	if err != nil || got["resolved"] != true {
		t.Errorf("localhost = %v, %v; want it resolved", got, err)
	}
}
